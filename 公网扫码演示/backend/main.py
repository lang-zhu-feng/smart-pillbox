"""Runnable local API. Demo actions never claim that a physical device is online."""
import asyncio
from contextlib import asynccontextmanager, contextmanager, suppress
from datetime import datetime, timedelta
import hashlib
import hmac
import json
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
from backend.domain import TZ, SLOTS, now_local, seed_state, rebuild_tasks, tick, add_alert, complete, public_state

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

class Heartbeat(Payload):
    deviceCode: str = Field(min_length=1, max_length=60)
    battery: int | None = Field(default=None, ge=0, le=100)

class DeviceEvent(Heartbeat):
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
        db.execute('UPDATE states SET content=? WHERE user_id=?', (json.dumps(state, ensure_ascii=False), user_id))

    def session(self, db, user_id):
        raw = secrets.token_urlsafe(32)
        db.execute('DELETE FROM sessions WHERE expires_at<?', (now_local().isoformat(),))
        db.execute('INSERT INTO sessions VALUES (?,?,?)', (digest(raw), user_id, (now_local() + timedelta(days=1)).isoformat()))
        user = db.execute('SELECT name,is_demo FROM users WHERE id=?', (user_id,)).fetchone()
        return {'token': raw, 'name': user['name'], 'isDemo': bool(user['is_demo'])}

def create_app(db_path=None, clock=None):
    database = Database(db_path or os.environ.get('MEDGUARD_DB', ROOT / 'backend' / 'data' / 'medguard.sqlite3'))
    current_time = clock or now_local

    async def scheduler():
        while True:
            await asyncio.sleep(5)
            def advance():
                with database.transaction() as db:
                    for row in db.execute('SELECT user_id,content FROM states').fetchall():
                        state = json.loads(row['content'])
                        tick(state, current_time())
                        database.save(db, row['user_id'], state)
            await asyncio.to_thread(advance)

    @asynccontextmanager
    async def lifespan(app):
        database.initialize()
        timer = asyncio.create_task(scheduler())
        yield
        timer.cancel()
        with suppress(asyncio.CancelledError):
            await timer

    app = FastAPI(title='安心药伴 · 家庭用药陪伴', version='0.2.0', lifespan=lifespan)
    app.state.database = database
    app.add_middleware(CORSMiddleware, allow_origins=['null'],
        allow_origin_regex=r'https?://(127\.0\.0\.1|localhost)(:\d+)?',
        allow_methods=['GET', 'POST', 'PATCH'], allow_headers=['Authorization', 'Content-Type'])

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
            return database.session(db, database.create_user(db, 'guest-' + uuid.uuid4().hex, '体验家属', secrets.token_urlsafe(24), True))

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
            if task['status'] in ['NO_MEDICATION', 'COMPLETED']:
                raise HTTPException(409, '请选择尚未完成且有用药计划的药格')
            task.update(status='OVERDUE', demoOverride=True)
            add_alert(state, task, current_time(), 'demo')
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
            state = seed_state(user['name'], bool(user['is_demo']))
            state['device']['code'] = original['device']['code']
            database.save(db, user_id, state)
            return public_state(state, current_time())

    @app.get('/api/device/integration')
    def integration(user_id=Depends(family)):
        with database.transaction() as db:
            state = database.load(db, user_id)
            configured = bool(db.execute('SELECT 1 FROM device_keys WHERE user_id=?', (user_id,)).fetchone())
        return {'deviceCode': state['device']['code'], 'keyConfigured': configured,
                'heartbeatPath': '/api/device/heartbeat', 'eventPath': '/api/device/events',
                'schedulePath': '/api/device/schedule', 'heartbeatIntervalSeconds': 30,
                'offlineAfterSeconds': 90, 'hardwareReady': state['device']['hasConnected']}

    @app.post('/api/device/credentials')
    def credentials(user_id=Depends(family)):
        raw = secrets.token_urlsafe(32)
        with database.transaction() as db:
            state = database.load(db, user_id)
            db.execute('DELETE FROM device_keys WHERE user_id=?', (user_id,))
            db.execute('INSERT INTO device_keys VALUES (?,?,?)', (digest(raw), user_id, state['device']['code']))
        return {'deviceCode': state['device']['code'], 'deviceToken': raw,
                'message': '密钥仅显示这一次；重新生成后旧密钥立即失效'}

    @app.post('/api/device/heartbeat')
    def heartbeat(body: Heartbeat, owner=Depends(device)):
        if body.deviceCode != owner['device_code']:
            raise HTTPException(403, '设备编号与密钥不匹配')
        def update(state):
            state['device'].update(lastHardwareSeen=current_time().isoformat(), hasConnected=True)
            if body.battery is not None:
                state['device']['battery'] = body.battery
        return {'ok': True, 'device': change(owner['user_id'], update)['device']}

    @app.get('/api/device/schedule')
    def schedule(owner=Depends(device)):
        state = change(owner['user_id'], lambda state: None)
        return {'deviceCode': owner['device_code'], 'serverTime': current_time().isoformat(),
                'tasks': [t for t in state['tasks'] if t['date'] == current_time().date().isoformat()],
                'reminderPolicy': {'intervalSeconds': 600, 'maxCount': 3, 'graceSeconds': 900}}

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
            complete(state, task, body.occurredAt, 'hardware', body.eventId)
            state['device'].update(lastHardwareSeen=now.isoformat(), hasConnected=True)
            if body.battery is not None:
                state['device']['battery'] = body.battery
            db.execute('INSERT INTO device_events VALUES (?,?,?)', (owner['user_id'], body.eventId, body.model_dump_json()))
            database.save(db, owner['user_id'], state)
        return {'ok': True, 'duplicate': False, 'matched': True, 'taskId': task['id']}

    asset_dir = ROOT / '微信小程序' / 'assets'
    if asset_dir.exists():
        app.mount('/assets', StaticFiles(directory=asset_dir), name='assets')

    @app.get('/', include_in_schema=False)
    @app.get('/preview', include_in_schema=False)
    @app.get('/preview.html', include_in_schema=False)
    def preview():
        return FileResponse(ROOT / '微信小程序' / 'preview.html')

    return app

app = create_app()
