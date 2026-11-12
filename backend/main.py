"""Runnable local API. Demo actions never claim that a physical device is online."""
import asyncio
from contextlib import asynccontextmanager, contextmanager, suppress
from datetime import datetime, timedelta
import hashlib
import hmac
import json
import logging
import os
from pathlib import Path
import re
import secrets
import sqlite3
import uuid
from fastapi import FastAPI, Depends, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator
from backend.domain import TZ, SLOTS, REMINDER_INTERVAL_SECONDS, REMINDER_MAX_COUNT, GRACE_SECONDS, now_local, seed_state, rebuild_tasks, tick, add_alert, complete, confirm_reminder, public_state
from backend.wechat_notifications import WechatNotifications, NotificationError
from backend.medicine_support import initialize_support, install_support, reconcile_support, clear_support

ROOT = Path(__file__).resolve().parent.parent
DEMO_PHONE, DEMO_PASSWORD = '13800000000', 'Demo12345'

def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()

def hash_password(password, salt=None):
    salt = salt or secrets.token_hex(16)
    key = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 200_000).hex()
    return salt + ':' + key

def password_matches(password, saved):
    return hmac.compare_digest(hash_password(password, saved.split(':')[0]), saved)

class Payload(BaseModel):
    model_config = ConfigDict(extra='forbid')

    @model_validator(mode='before')
    @classmethod
    def trim_labels(cls, data):
        if isinstance(data, dict):
            return {key: value.strip() if isinstance(value, str) and key != 'password' else value for key, value in data.items()}
        return data

class Login(Payload):
    phone: str = Field(pattern=r'^1\d{10}$')
    password: str = Field(min_length=1, max_length=64)

class Registration(Login):
    name: str = Field(min_length=1, max_length=24)

    @field_validator('password')
    @classmethod
    def strong_password(cls, value):
        if len(value) < 8 or not re.search(r'[A-Za-z]', value) or not re.search(r'\d', value):
            raise ValueError('密码至少 8 位，且同时包含字母和数字')
        return value

class Plan(Payload):
    medicine: str = Field(min_length=1, max_length=60)
    dosage: str = Field(min_length=1, max_length=40)
    slotKey: str = Field(pattern=r'^(morning|noon|evening)$')
    time: str = Field(pattern=r'^([01]\d|2[0-3]):[0-5]\d$')
    days: list[StrictInt] = Field(min_length=1, max_length=7)
    note: str = Field(default='', max_length=160)

    @field_validator('days')
    @classmethod
    def valid_days(cls, value):
        if any(type(day) is not int or not 0 <= day <= 6 for day in value) or len(set(value)) != len(value):
            raise ValueError('星期必须是 0 到 6 的不重复整数')
        return sorted(value)

class Toggle(Payload):
    enabled: bool

class WechatAuthorization(Payload):
    code: str = Field(min_length=1, max_length=512)
    templateId: str = Field(min_length=1, max_length=256)

class Elder(Payload):
    name: str = Field(min_length=1, max_length=30)
    age: int = Field(ge=0, le=120)
    relation: str = Field(min_length=1, max_length=12)
    address: str = Field(default='', max_length=100)
    emergencyContact: str = Field(default='', max_length=60)
    conditions: list[str] = Field(default_factory=list, max_length=12)
    homeTitle: str = Field(min_length=1, max_length=24)

    @field_validator('conditions')
    @classmethod
    def short_conditions(cls, value):
        if any(len(item) > 30 for item in value):
            raise ValueError('单个备注不能超过 30 字')
        return value

class DevicePayload(Payload):
    deviceCode: str = Field(min_length=1, max_length=60)
    battery: int | None = Field(default=None, ge=0, le=100)

class DeviceEvent(DevicePayload):
    eventId: str = Field(min_length=1, max_length=80)
    slotKey: str = Field(pattern=r'^(morning|noon|evening)$')
    occurredAt: datetime

    @field_validator('occurredAt')
    @classmethod
    def explicit_timezone(cls, value):
        if value.tzinfo is None:
            raise ValueError('设备时间必须包含时区，例如 +08:00')
        return value.astimezone(TZ)

class Database:
    def __init__(self, path):
        self.path = Path(path)

    @contextmanager
    def transaction(self):
        connection = sqlite3.connect(self.path, timeout=20)
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA foreign_keys=ON')
        try:
            connection.execute('BEGIN IMMEDIATE')
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.transaction() as db:
            for statement in [
                'CREATE TABLE IF NOT EXISTS users (id TEXT PRIMARY KEY, phone TEXT UNIQUE NOT NULL, name TEXT NOT NULL, password TEXT NOT NULL, is_demo INTEGER NOT NULL DEFAULT 0)',
                'CREATE TABLE IF NOT EXISTS states (user_id TEXT PRIMARY KEY REFERENCES users(id), content TEXT NOT NULL)',
                'CREATE TABLE IF NOT EXISTS sessions (token_hash TEXT PRIMARY KEY, user_id TEXT REFERENCES users(id), expires_at TEXT NOT NULL)',
                'CREATE TABLE IF NOT EXISTS login_attempts (phone TEXT PRIMARY KEY, failures INTEGER NOT NULL, locked_until TEXT)',
                'CREATE TABLE IF NOT EXISTS device_keys (token_hash TEXT PRIMARY KEY, user_id TEXT UNIQUE REFERENCES users(id), device_code TEXT UNIQUE NOT NULL)',
                'CREATE TABLE IF NOT EXISTS device_events (user_id TEXT REFERENCES users(id), event_id TEXT, content TEXT NOT NULL, PRIMARY KEY(user_id, event_id))',
            ]:
                db.execute(statement)
            initialize_support(db)
            if not db.execute('SELECT id FROM users WHERE phone=?', (DEMO_PHONE,)).fetchone():
                self.create_user(db, DEMO_PHONE, '演示家属', DEMO_PASSWORD, True)

    def create_user(self, db, phone, name, password, demo=False):
        user_id = uuid.uuid4().hex
        db.execute('INSERT INTO users VALUES (?,?,?,?,?)', (user_id, phone, name, hash_password(password), int(demo)))
        db.execute('INSERT INTO states VALUES (?,?)', (user_id, json.dumps(seed_state(name, demo), ensure_ascii=False)))
        return user_id

    def load(self, db, user_id):
        return json.loads(db.execute('SELECT content FROM states WHERE user_id=?', (user_id,)).fetchone()['content'])

    def save(self, db, user_id, state):
        state['meta']['updatedAt'] = now_local().isoformat(timespec='seconds')
        reconcile_support(db, user_id, state)
        db.execute('UPDATE states SET content=? WHERE user_id=?', (json.dumps(state, ensure_ascii=False), user_id))

    def session(self, db, user_id):
        raw = secrets.token_urlsafe(32)
        db.execute('DELETE FROM sessions WHERE expires_at<?', (now_local().isoformat(),))
        db.execute('INSERT INTO sessions VALUES (?,?,?)', (digest(raw), user_id, (now_local() + timedelta(days=1)).isoformat()))
        user = db.execute('SELECT name,is_demo FROM users WHERE id=?', (user_id,)).fetchone()
        return {'token': raw, 'name': user['name'], 'isDemo': bool(user['is_demo'])}

def create_app(db_path=None, clock=None, notification_config=None, notification_transport=None, scheduler_interval=5):
    database = Database(db_path or os.environ.get('MEDGUARD_DB', ROOT / 'backend' / 'data' / 'medguard.sqlite3'))
    current_time = clock or now_local
    notifications = WechatNotifications(database, current_time, notification_config, notification_transport)

    def advance_rules(dispatch=True):
        with database.transaction() as db:
            for row in db.execute('SELECT states.user_id,states.content,users.is_demo FROM states JOIN users ON users.id=states.user_id').fetchall():
                state = json.loads(row['content'])
                now = current_time()
                tick(state, now)
                notifications.capture(db, row['user_id'], state, now, bool(row['is_demo']))
                database.save(db, row['user_id'], state)
        if dispatch:
            notifications.dispatch()

    async def scheduler():
        while True:
            await asyncio.sleep(scheduler_interval)
            await asyncio.to_thread(advance_rules, False)

    async def notification_scheduler():
        while True:
            await asyncio.sleep(scheduler_interval)
            try:
                await asyncio.to_thread(notifications.dispatch)
            except Exception:
                # Keep rule advancement alive, and never log HTTP URLs or keys.
                logging.getLogger(__name__).warning('微信通知派发中断；未确认结果不会自动重发。')

    @asynccontextmanager
    async def lifespan(app):
        database.initialize()
        notifications.initialize()
        timer = asyncio.create_task(scheduler())
        notification_timer = asyncio.create_task(notification_scheduler())
        yield
        timer.cancel()
        notification_timer.cancel()
        with suppress(asyncio.CancelledError):
            await timer
        with suppress(asyncio.CancelledError):
            await notification_timer

    app = FastAPI(title='安心药伴 · 家庭用药陪伴', version='0.2.0', lifespan=lifespan)
    app.state.database = database
    app.state.notifications = notifications
    app.state.advance_rules = advance_rules
    app.add_middleware(CORSMiddleware, allow_origins=['null'],
        allow_origin_regex=r'https?://(127\.0\.0\.1|localhost)(:\d+)?',
        allow_methods=['GET', 'POST', 'PATCH', 'PUT', 'DELETE'], allow_headers=['Authorization', 'Content-Type'])

    def bearer(authorization):
        if not authorization or not authorization.startswith('Bearer '):
            raise HTTPException(401, '请先登录')
        return authorization[7:]

    def family(authorization: str | None = Header(default=None)):
        with database.transaction() as db:
            row = db.execute('SELECT user_id,expires_at FROM sessions WHERE token_hash=?', (digest(bearer(authorization)),)).fetchone()
            if not row or datetime.fromisoformat(row['expires_at']) <= now_local():
                raise HTTPException(401, '登录已过期，请重新登录')
            return row['user_id']

    def device(authorization: str | None = Header(default=None)):
        with database.transaction() as db:
            row = db.execute('SELECT user_id,device_code FROM device_keys WHERE token_hash=?', (digest(bearer(authorization)),)).fetchone()
            if not row:
                raise HTTPException(401, '设备密钥无效')
            return dict(row)

    def change(user_id, operation):
        with database.transaction() as db:
            state = database.load(db, user_id)
            tick(state, current_time())
            operation(state)
            database.save(db, user_id, state)
            return public_state(state, current_time())

    def find_task(state, task_id):
        task = next((t for t in state['tasks'] if t['id'] == task_id), None)
        if not task:
            raise HTTPException(404, '没有找到这个药格')
        return task

    @app.get('/health')
    def health():
        return {'status': 'healthy', 'service': '安心药伴', 'storage': 'sqlite', 'hardwareRequired': False}

    @app.post('/api/auth/demo')
    def demo_login():
        with database.transaction() as db:
            return database.session(db, db.execute('SELECT id FROM users WHERE phone=?', (DEMO_PHONE,)).fetchone()['id'])

    @app.post('/api/auth/register')
    def register(body: Registration):
        with database.transaction() as db:
            if db.execute('SELECT id FROM users WHERE phone=?', (body.phone,)).fetchone():
                raise HTTPException(409, '该手机号已经注册')
            return database.session(db, database.create_user(db, body.phone, body.name, body.password))

    @app.post('/api/auth/login')
    def login(body: Login):
        failure, result = None, None
        # Commit failed attempts before returning an HTTP error.
        with database.transaction() as db:
            attempt = db.execute('SELECT * FROM login_attempts WHERE phone=?', (body.phone,)).fetchone()
            failures = attempt['failures'] if attempt else 0
            until = datetime.fromisoformat(attempt['locked_until']) if attempt and attempt['locked_until'] else None
            if until and now_local() < until:
                failure = (429, {'message': '尝试次数已用完，请稍后重试', 'remainingAttempts': 0,
                                 'retryAfter': max(1, int((until - now_local()).total_seconds()))})
            else:
                if until:
                    failures = 0
                user = db.execute('SELECT * FROM users WHERE phone=?', (body.phone,)).fetchone()
                valid = password_matches(body.password, user['password']) if user else password_matches(body.password, hash_password('placeholder'))
                if not user or not valid:
                    failures += 1
                    locked = (now_local() + timedelta(seconds=60)).isoformat() if failures >= 3 else None
                    db.execute('INSERT OR REPLACE INTO login_attempts VALUES (?,?,?)', (body.phone, failures, locked))
                    failure = (429 if locked else 401, {'message': '手机号或密码不正确',
                               'remainingAttempts': max(0, 3 - failures), 'retryAfter': 60 if locked else 0})
                else:
                    db.execute('DELETE FROM login_attempts WHERE phone=?', (body.phone,))
                    result = database.session(db, user['id'])
        if failure:
            raise HTTPException(*failure)
        return result

    @app.post('/api/auth/logout')
    def logout(user_id=Depends(family), authorization: str = Header()):
        with database.transaction() as db:
            db.execute('DELETE FROM sessions WHERE token_hash=?', (digest(bearer(authorization)),))
        return {'ok': True}

    @app.get('/api/state')
    def state(user_id=Depends(family)):
        return change(user_id, lambda state: None)

    @app.get('/api/notifications/wechat')
    def wechat_notification_status(user_id=Depends(family)):
        return notifications.status(user_id)

    @app.post('/api/notifications/wechat/authorize')
    def authorize_wechat_notifications(body: WechatAuthorization, user_id=Depends(family)):
        try:
            return notifications.authorize(user_id, body.code, body.templateId)
        except NotificationError as error:
            raise HTTPException(error.status, error.message) from None

    @app.patch('/api/profile')
    def profile(body: Elder, user_id=Depends(family)):
        return change(user_id, lambda state: state.update(elder=body.model_dump()))

    @app.post('/api/plans', status_code=201)
    def add_plan(body: Plan, user_id=Depends(family)):
        def update(state):
            if len(state['plans']) >= 50:
                raise HTTPException(409, '一个家庭最多保留 50 项计划')
            validate_slot_time(state, body.model_dump())
            state['plans'].append(dict(body.model_dump(), id=uuid.uuid4().hex, enabled=True))
            rebuild_tasks(state, current_time())
        return change(user_id, update)

    @app.patch('/api/plans/{plan_id}')
    def toggle_plan(plan_id: str, body: Toggle, user_id=Depends(family)):
        def update(state):
            plan = next((p for p in state['plans'] if p['id'] == plan_id), None)
            if not plan:
                raise HTTPException(404, '没有找到这项计划')
            if body.enabled:
                validate_slot_time(state, plan, plan_id)
            plan['enabled'] = body.enabled
            rebuild_tasks(state, current_time())
        return change(user_id, update)

    @app.put('/api/plans/{plan_id}')
    def edit_plan(plan_id: str, body: Plan, user_id=Depends(family)):
        def update(state):
            plan = next((p for p in state['plans'] if p['id'] == plan_id), None)
            if not plan:
                raise HTTPException(404, '没有找到这项计划')
            details = body.model_dump()
            if plan['enabled']:
                validate_slot_time(state, details, plan_id)
            plan.update(details)
            rebuild_tasks(state, current_time())
        return change(user_id, update)

    @app.delete('/api/plans/{plan_id}')
    def delete_plan(plan_id: str, user_id=Depends(family)):
        def update(state):
            plan = next((p for p in state['plans'] if p['id'] == plan_id), None)
            if not plan:
                raise HTTPException(404, '没有找到这项计划')
            state['plans'].remove(plan)
            rebuild_tasks(state, current_time())
        return change(user_id, update)

    def validate_slot_time(state, candidate, exclude_id=None):
        for plan in state['plans']:
            if plan['id'] != exclude_id and plan['enabled'] and plan['slotKey'] == candidate['slotKey'] and set(plan['days']) & set(candidate['days']) and plan['time'] != candidate['time']:
                raise HTTPException(409, '同一药格的计划需使用相同提醒时间；现有时间为 ' + plan['time'])

    @app.post('/api/demo/tasks/{task_id}/open')
    def simulate_open(task_id: str, user_id=Depends(family)):
        def update(state):
            try:
                complete(state, find_task(state, task_id), current_time(), 'demo', 'demo-' + uuid.uuid4().hex)
            except ValueError as error:
                raise HTTPException(409, str(error))
        return change(user_id, update)

    @app.post('/api/demo/tasks/{task_id}/overdue')
    def simulate_overdue(task_id: str, user_id=Depends(family)):
        def update(state):
            task = find_task(state, task_id)
            if task['status'] in ['NO_MEDICATION', 'COMPLETED', 'CONFIRMED']:
                raise HTTPException(409, '请选择尚未完成且有用药计划的药格')
            task.update(status='OVERDUE', demoOverride=True)
            add_alert(state, task, current_time(), 'demo')
        return change(user_id, update)

    @app.post('/api/tasks/{task_id}/confirm')
    def confirm_task(task_id: str, user_id=Depends(family)):
        def update(state):
            task = find_task(state, task_id)
            now = current_time()
            if task['date'] != now.date().isoformat() or task['slotKey'] not in state['device'].get('monitoredSlots', ['morning']):
                raise HTTPException(409, '只能确认今天已接入门磁的药格')
            if task['status'] in ['NO_MEDICATION', 'COMPLETED'] or task.get('demoOverride'):
                raise HTTPException(409, '这次计划无需确认')
            if now < datetime.fromisoformat(task['startAt']):
                raise HTTPException(409, '到提醒时间后才能确认')
            confirm_reminder(state, task, now)
        return change(user_id, update)

    @app.post('/api/alerts/read-all')
    def read_all(user_id=Depends(family)):
        return change(user_id, lambda state: [a.update(read=True) for a in state['alerts']])

    @app.post('/api/alerts/{alert_id}/read')
    def read_one(alert_id: str, user_id=Depends(family)):
        def update(state):
            alert = next((a for a in state['alerts'] if a['id'] == alert_id), None)
            if not alert:
                raise HTTPException(404, '提醒不存在')
            alert['read'] = True
        return change(user_id, update)

    @app.post('/api/demo/reset')
    def reset(user_id=Depends(family)):
        with database.transaction() as db:
            if db.execute('SELECT 1 FROM device_events WHERE user_id=?', (user_id,)).fetchone():
                raise HTTPException(409, '已有设备事件，为保护真实记录不能重置；请改用演示账号')
            user = db.execute('SELECT name,is_demo FROM users WHERE id=?', (user_id,)).fetchone()
            original = database.load(db, user_id)
            clear_support(db, user_id, current_time().isoformat())
            state = seed_state(user['name'], bool(user['is_demo']))
            state['device']['code'] = original['device']['code']
            database.save(db, user_id, state)
            return public_state(state, current_time())

    @app.post('/api/demo/reset-today')
    def reset_today(user_id=Depends(family)):
        with database.transaction() as db:
            now = current_time()
            today = now.date().isoformat()
            state = database.load(db, user_id)
            tick(state, now)
            state['history'] = [item for item in state['history'] if item.get('date') != today]
            state['alerts'] = [item for item in state['alerts']
                               if not item.get('taskKey', '').startswith(today + ':')]
            for row in db.execute('SELECT event_id,content FROM device_events WHERE user_id=?', (user_id,)).fetchall():
                if json.loads(row['content']).get('occurredAt', '').startswith(today + 'T'):
                    db.execute('DELETE FROM device_events WHERE user_id=? AND event_id=?', (user_id, row['event_id']))
            state['tasks'] = [task for task in state['tasks'] if task['date'] != today]
            rebuild_tasks(state, now)
            for task in state['tasks']:
                if task['date'] == today and task['medicines'] and now >= datetime.fromisoformat(task['startAt']):
                    task['resetSuppressed'] = True
            state['meta']['demoResetVersion'] = state['meta'].get('demoResetVersion', 0) + 1
            state['meta']['demoResetAt'] = now.isoformat()
            database.save(db, user_id, state)
            return public_state(state, now)

    @app.get('/api/device/integration')
    def integration(user_id=Depends(family)):
        with database.transaction() as db:
            state = database.load(db, user_id)
            configured = bool(db.execute('SELECT 1 FROM device_keys WHERE user_id=?', (user_id,)).fetchone())
        return {'deviceCode': state['device']['code'], 'keyConfigured': configured,
                'eventPath': '/api/device/events', 'schedulePath': '/api/device/schedule',
                'hardwareReady': state['device']['hasConnected'],
                'monitoredSlots': state['device'].get('monitoredSlots', ['morning'])}

    @app.post('/api/device/credentials')
    def credentials(user_id=Depends(family)):
        raw = secrets.token_urlsafe(32)
        with database.transaction() as db:
            state = database.load(db, user_id)
            db.execute('DELETE FROM device_keys WHERE user_id=?', (user_id,))
            db.execute('INSERT INTO device_keys VALUES (?,?,?)', (digest(raw), user_id, state['device']['code']))
        return {'deviceCode': state['device']['code'], 'deviceToken': raw,
                'message': '密钥仅显示这一次；重新生成后旧密钥立即失效'}

    @app.get('/api/device/schedule')
    def schedule(owner=Depends(device)):
        state = change(owner['user_id'], lambda state: None)
        return {'deviceCode': owner['device_code'], 'serverTime': current_time().isoformat(),
                'demoResetVersion': state['meta'].get('demoResetVersion', 0),
                'tasks': [t for t in state['tasks'] if t['date'] == current_time().date().isoformat()],
                'reminderPolicy': {'intervalSeconds': REMINDER_INTERVAL_SECONDS,
                                   'maxCount': REMINDER_MAX_COUNT, 'graceSeconds': GRACE_SECONDS}}

    @app.post('/api/device/events')
    def events(body: DeviceEvent, owner=Depends(device)):
        if body.deviceCode != owner['device_code']:
            raise HTTPException(403, '设备编号与密钥不匹配')
        now = current_time()
        if body.occurredAt > now + timedelta(minutes=2) or body.occurredAt < now - timedelta(days=7):
            raise HTTPException(422, '设备时间偏差过大，请校准时间后上传')
        with database.transaction() as db:
            state = database.load(db, owner['user_id'])
            tick(state, now)
            reset_at = state['meta'].get('demoResetAt')
            if reset_at and body.occurredAt <= datetime.fromisoformat(reset_at):
                raise HTTPException(409, '演示重置之前的开盒事件已作废')
            existing = db.execute('SELECT content FROM device_events WHERE user_id=? AND event_id=?',
                                  (owner['user_id'], body.eventId)).fetchone()
            if existing:
                if json.loads(existing['content']) != body.model_dump(mode='json'):
                    raise HTTPException(409, '同一事件编号不能用于不同事件')
                return {'ok': True, 'duplicate': True, 'matched': True}
            task = find_task(state, str(body.occurredAt.weekday()) + '-' + body.slotKey)
            if task['date'] != body.occurredAt.date().isoformat():
                raise HTTPException(422, '该事件不属于当前展示周，请核对设备时间')
            if task['status'] == 'NO_MEDICATION':
                raise HTTPException(409, '这个药格没有计划，事件未作为用药完成记录')
            if body.occurredAt < datetime.fromisoformat(task['startAt']):
                raise HTTPException(409, '计划开始前开盒，不计为本次用药开盒')
            complete(state, task, body.occurredAt, 'hardware', body.eventId)
            state['device'].update(lastHardwareSeen=now.isoformat(), hasConnected=True)
            if body.battery is not None:
                state['device']['battery'] = body.battery
            db.execute('INSERT INTO device_events VALUES (?,?,?)', (owner['user_id'], body.eventId, body.model_dump_json()))
            database.save(db, owner['user_id'], state)
        return {'ok': True, 'duplicate': False, 'matched': True, 'taskId': task['id']}

    install_support(app, database, family, current_time)

    asset_dir = ROOT / '微信小程序' / 'assets'
    if asset_dir.exists():
        app.mount('/assets', StaticFiles(directory=asset_dir), name='assets')

    @app.get('/', include_in_schema=False)
    @app.get('/preview', include_in_schema=False)
    @app.get('/preview.html', include_in_schema=False)
    def preview():
        return FileResponse(ROOT / '微信小程序' / 'preview.html', headers={'Cache-Control': 'no-store'})

    return app

app = create_app()
