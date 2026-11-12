"""Server-side WeChat subscriptions and an at-most-once persistent outbox.

Subscription credits are estimates reported by the subscribing client, not proof
of a WeChat grant. Only a successful WeChat send response means API acceptance;
an ambiguous send is never retried automatically.
"""
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import threading
import time

import httpx
from dotenv import load_dotenv


@dataclass(frozen=True)
class WechatConfig:
    app_id: str = ''
    app_secret: str = ''
    template_id: str = ''
    fields: dict | None = None
    miniprogram_state: str = 'formal'

    @classmethod
    def from_env(cls):
        load_dotenv(Path(__file__).with_name('.env'), override=False)
        try:
            fields = json.loads(os.environ.get('WECHAT_OVERDUE_FIELDS', '{}'))
        except (ValueError, TypeError):
            fields = None
        return cls(os.environ.get('WECHAT_APP_ID', '').strip(),
                   os.environ.get('WECHAT_APP_SECRET', '').strip(),
                   os.environ.get('WECHAT_OVERDUE_TEMPLATE_ID', '').strip(),
                   fields, os.environ.get('WECHAT_MINIPROGRAM_STATE', 'formal').strip())

    @property
    def problem(self):
        if not all((self.app_id, self.app_secret, self.template_id)):
            return '服务端尚未配置微信 AppID、AppSecret 和获批的提醒模板。'
        if not isinstance(self.fields, dict) or set(self.fields) != {'name', 'time', 'remark'}:
            return '服务端需显式配置 WECHAT_OVERDUE_FIELDS，将 name、time、remark 对应到获批模板字段。'
        # These supported types have well-defined formats and length limits.
        patterns = {'name': r'(thing|name)\d+', 'time': r'time\d+', 'remark': r'thing\d+'}
        if any(not isinstance(self.fields[key], str) or not re.fullmatch(patterns[key], self.fields[key])
               for key in patterns) or len(set(self.fields.values())) != 3:
            return '微信模板字段需使用获批模板的姓名或事项、时间、事项字段，且三个字段不能重复。'
        if self.miniprogram_state not in {'formal', 'trial', 'developer'}:
            return 'WECHAT_MINIPROGRAM_STATE 需为 formal、trial 或 developer。'
        return ''

    @property
    def configured(self):
        return not self.problem


class NotificationError(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message
        super().__init__(message)


class WechatNotifications:
    def __init__(self, database, clock, config=None, transport=None):
        self.database, self.clock = database, clock
        self.config = config if config is not None else WechatConfig.from_env()
        self.transport = transport
        self._dispatch_lock = threading.Lock()
        self._token_lock = threading.Lock()
        self._access_token = ''
        self._token_until = 0

    def initialize(self):
        with self.database.transaction() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS wechat_subscriptions (
                user_id TEXT PRIMARY KEY REFERENCES users(id), app_id TEXT NOT NULL,
                template_id TEXT NOT NULL, openid TEXT NOT NULL, credits INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL, UNIQUE(app_id, openid))''')
            db.execute('''CREATE TABLE IF NOT EXISTS wechat_authorization_codes (
                code_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
                status TEXT NOT NULL, created_at TEXT NOT NULL)''')
            db.execute('''CREATE TABLE IF NOT EXISTS wechat_outbox (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL REFERENCES users(id),
                task_key TEXT NOT NULL, alert_id TEXT NOT NULL, template_id TEXT NOT NULL,
                status TEXT NOT NULL, message TEXT NOT NULL, target_openid TEXT,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                UNIQUE(user_id, task_key))''')
            # A process may have died after WeChat received the message. Reclaiming
            # such rows would risk a duplicate, so leave them for manual review.
            db.execute("UPDATE wechat_outbox SET status='unknown', message=?, updated_at=? WHERE status='sending'",
                       ('上次发送被中断，微信是否受理未知；为避免重复不会自动重发。', self._stamp()))
            db.execute("UPDATE wechat_authorization_codes SET status='failed' WHERE status='processing'")

    def _stamp(self):
        return self.clock().isoformat(timespec='microseconds')

    def _user(self, db, user_id):
        row = db.execute('SELECT is_demo FROM users WHERE id=?', (user_id,)).fetchone()
        if not row:
            raise NotificationError(401, '请先登录')
        return row

    def _subscription(self, db, user_id):
        return db.execute('SELECT * FROM wechat_subscriptions WHERE user_id=? AND app_id=? AND template_id=?',
                          (user_id, self.config.app_id, self.config.template_id)).fetchone()

    def status(self, user_id):
        with self.database.transaction() as db:
            user = self._user(db, user_id)
            subscription = self._subscription(db, user_id)
            delivery = db.execute('SELECT status,message FROM wechat_outbox WHERE user_id=? ORDER BY updated_at DESC,id DESC LIMIT 1',
                                  (user_id,)).fetchone()
        reason = self.config.problem
        if user['is_demo']:
            reason = '演示账号不发送真实微信通知，请使用自己的家属账号。'
        return {'configured': self.config.configured,
                'available': self.config.configured and not bool(user['is_demo']),
                'unavailableReason': reason,
                'templateId': self.config.template_id if self.config.configured else '',
                'authorizedCredits': subscription['credits'] if subscription and self.config.configured and not user['is_demo'] else 0,
                'lastDeliveryStatus': delivery['status'] if delivery else 'not_sent',
                'lastDeliveryMessage': delivery['message'] if delivery else '尚无微信发送记录；可用订阅次数为本地估计。'}

    def _json_request(self, method, path, **kwargs):
        # Never put raw HTTP exceptions into API replies: their URLs can contain
        # the AppSecret, login code, or access token.
        with httpx.Client(base_url='https://api.weixin.qq.com', transport=self.transport,
                          timeout=8, trust_env=False) as client:
            response = client.request(method, path, **kwargs)
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError('Unexpected WeChat response')
            return data

    def authorize(self, user_id, code, template_id):
        with self.database.transaction() as db:
            if self._user(db, user_id)['is_demo']:
                raise NotificationError(403, '演示账号不能订阅真实微信通知')
        if not self.config.configured:
            raise NotificationError(503, self.config.problem)
        if template_id != self.config.template_id:
            raise NotificationError(422, '订阅模板与服务端配置不一致，请刷新后重试')
        code_hash = hashlib.sha256((self.config.app_id + ':' + code).encode()).hexdigest()
        repeated = False
        with self.database.transaction() as db:
            existing = db.execute('SELECT user_id,status FROM wechat_authorization_codes WHERE code_hash=?', (code_hash,)).fetchone()
            if existing:
                if existing['user_id'] != user_id:
                    raise NotificationError(409, '该登录凭证已被使用，请重新登录微信后订阅')
                if existing['status'] != 'authorized':
                    raise NotificationError(409, '该登录凭证已尝试使用，请获取新的微信登录凭证后重试')
                repeated = True
            else:
                db.execute('INSERT INTO wechat_authorization_codes VALUES (?,?,?,?)',
                           (code_hash, user_id, 'processing', self._stamp()))
        if repeated:
            return self.status(user_id)

        try:
            response = self._json_request('GET', '/sns/jscode2session', params={
                'appid': self.config.app_id, 'secret': self.config.app_secret,
                'js_code': code, 'grant_type': 'authorization_code'})
            openid = response.get('openid')
            if response.get('errcode', 0) != 0 or not isinstance(openid, str) or not openid:
                raise NotificationError(422, '微信登录凭证无效或已过期，请重新登录并订阅')
            with self.database.transaction() as db:
                owner = db.execute('SELECT user_id FROM wechat_subscriptions WHERE app_id=? AND openid=?',
                                   (self.config.app_id, openid)).fetchone()
                if owner and owner['user_id'] != user_id:
                    raise NotificationError(409, '这个微信已绑定其他家属账号，请先使用原家属账号')
                existing = self._subscription(db, user_id)
                credits = existing['credits'] + 1 if existing and existing['openid'] == openid else 1
                db.execute('''INSERT INTO wechat_subscriptions VALUES (?,?,?,?,?,?)
                    ON CONFLICT(user_id) DO UPDATE SET app_id=excluded.app_id,
                    template_id=excluded.template_id, openid=excluded.openid,
                    credits=excluded.credits, updated_at=excluded.updated_at''',
                           (user_id, self.config.app_id, self.config.template_id, openid, credits, self._stamp()))
                db.execute("UPDATE wechat_authorization_codes SET status='authorized' WHERE code_hash=?", (code_hash,))
                # An explicit permission rejection is known not to have sent.
                # A fresh grant may retry it; ambiguous/successful rows stay final.
                db.execute("UPDATE wechat_outbox SET status='pending',message=?,updated_at=? WHERE user_id=? AND template_id=? AND status='needs_authorization'",
                           ('已重新订阅，等待后台复核任务后发送。', self._stamp(), user_id, self.config.template_id))
        except (httpx.HTTPError, ValueError, NotificationError) as error:
            with self.database.transaction() as db:
                db.execute("UPDATE wechat_authorization_codes SET status='failed' WHERE code_hash=?", (code_hash,))
            if isinstance(error, NotificationError):
                raise
            raise NotificationError(502, '暂时无法向微信核验登录，请稍后重新登录并订阅') from None
        return self.status(user_id)

    def capture(self, db, user_id, state, now, is_demo=False):
        """Run in the same transaction as tick; never queue demo or old-day alerts."""
        if is_demo or not self.config.configured:
            return
        tasks = {task['date'] + ':' + task['id']: task for task in state['tasks']}
        for alert in state['alerts']:
            key = alert.get('taskKey')
            task = tasks.get(key)
            if (alert.get('source') != 'rule' or alert.get('read') or not task
                    or task.get('demoOverride') or task['status'] != 'OVERDUE'
                    or task['date'] != now.date().isoformat()):
                continue
            stamp = now.isoformat(timespec='microseconds')
            db.execute('''INSERT OR IGNORE INTO wechat_outbox
                (user_id,task_key,alert_id,template_id,status,message,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?)''',
                       (user_id, key, alert['id'], self.config.template_id, 'pending', '等待后台发送。', stamp, stamp))

    def _eligible(self, state, item, now):
        alert = next((a for a in state['alerts'] if a['id'] == item['alert_id'] and a.get('taskKey') == item['task_key']), None)
        task = next((t for t in state['tasks'] if t['date'] + ':' + t['id'] == item['task_key']), None)
        if (not alert or alert.get('source') != 'rule' or alert.get('read') or not task
                or task.get('demoOverride') or task['status'] != 'OVERDUE'
                or task['date'] != now.date().isoformat()
                or item['template_id'] != self.config.template_id):
            return None
        return task

    def _claim(self, item_id, now):
        with self.database.transaction() as db:
            item = db.execute("SELECT * FROM wechat_outbox WHERE id=? AND status IN ('pending','waiting_authorization')", (item_id,)).fetchone()
            if not item:
                return None
            user = self._user(db, item['user_id'])
            state = self.database.load(db, item['user_id'])
            if user['is_demo'] or not self._eligible(state, item, now):
                db.execute("UPDATE wechat_outbox SET status='cancelled',message=?,updated_at=? WHERE id=?",
                           ('任务已处理、取消或过期，未发送微信通知。', self._stamp(), item_id))
                return None
            subscription = self._subscription(db, item['user_id'])
            if not subscription or subscription['credits'] <= 0:
                # Do not touch updated_at on every 5-second pass.
                if item['status'] != 'waiting_authorization':
                    db.execute("UPDATE wechat_outbox SET status='waiting_authorization',message=?,updated_at=? WHERE id=?",
                               ('需在小程序重新订阅，才可尝试发送微信通知。', self._stamp(), item_id))
                return None
            db.execute('UPDATE wechat_subscriptions SET credits=credits-1,updated_at=? WHERE user_id=?',
                       (self._stamp(), item['user_id']))
            db.execute("UPDATE wechat_outbox SET status='sending',target_openid=?,message=?,updated_at=? WHERE id=?",
                       (subscription['openid'], '正在向微信提交；结果尚未确认。', self._stamp(), item_id))
            return dict(item, target_openid=subscription['openid'])

    def _finish(self, item, status, message, restore_credit=False, clear_credits=False):
        with self.database.transaction() as db:
            updated = db.execute("UPDATE wechat_outbox SET status=?,message=?,updated_at=? WHERE id=? AND status='sending'",
                                 (status, message, self._stamp(), item['id'])).rowcount
            if not updated:
                return
            subscription = self._subscription(db, item['user_id'])
            if subscription and subscription['openid'] == item['target_openid']:
                if clear_credits:
                    db.execute('UPDATE wechat_subscriptions SET credits=0,updated_at=? WHERE user_id=?', (self._stamp(), item['user_id']))
                elif restore_credit:
                    db.execute('UPDATE wechat_subscriptions SET credits=credits+1,updated_at=? WHERE user_id=?', (self._stamp(), item['user_id']))

    def _token(self):
        with self._token_lock:
            if self._access_token and time.monotonic() < self._token_until:
                return self._access_token
            response = self._json_request('GET', '/cgi-bin/token', params={
                'grant_type': 'client_credential', 'appid': self.config.app_id, 'secret': self.config.app_secret})
            token, expires = response.get('access_token'), response.get('expires_in')
            if response.get('errcode', 0) != 0 or not isinstance(token, str) or not token or type(expires) is not int or expires <= 0:
                raise ValueError('Invalid WeChat access token response')
            self._access_token = token
            self._token_until = time.monotonic() + max(1, expires - 120)
            return token

    def _send(self, item, now):
        try:
            token = self._token()
        except (httpx.HTTPError, ValueError):
            self._finish(item, 'failed', '未取得微信发送凭证，通知未提交；请检查服务端配置。', restore_credit=True)
            return

        # Token retrieval may take time. Recheck the current task and recipient
        # immediately before submission, not only when the outbox was created.
        with self.database.transaction() as db:
            state = self.database.load(db, item['user_id'])
            task = self._eligible(state, item, self.clock())
            subscription = self._subscription(db, item['user_id'])
            target_valid = subscription and subscription['openid'] == item['target_openid']
        if not task or not target_valid:
            self._finish(item, 'cancelled', '发送前任务已处理或订阅身份已变化，未发送微信通知。', restore_credit=True)
            return

        name_key = self.config.fields['name']
        max_name = 10 if name_key.startswith('name') else 20
        fields = {
            'name': str(state['elder'].get('name') or '家人')[:max_name],
            'time': datetime.fromisoformat(task['startAt']).strftime('%Y-%m-%d %H:%M'),
            'remark': '暂未收到开盒记录，请联系家人确认',
        }
        body = {'touser': item['target_openid'], 'template_id': item['template_id'],
                'page': 'pages/alerts/alerts', 'miniprogram_state': self.config.miniprogram_state,
                'lang': 'zh_CN',
                'data': {self.config.fields[key]: {'value': value} for key, value in fields.items()}}
        try:
            response = self._json_request('POST', '/cgi-bin/message/subscribe/send',
                                          params={'access_token': token}, json=body)
        except (httpx.HTTPError, ValueError):
            self._finish(item, 'unknown', '微信是否受理未知；为避免重复不自动重发，请查看微信并联系家人确认。')
            return
        code = response.get('errcode')
        if type(code) is not int:
            self._finish(item, 'unknown', '微信返回结果无法确认；为避免重复不自动重发。')
        elif code == 0:
            self._finish(item, 'sent', '微信 API 已受理通知，不代表家属已收到或已读。')
        elif code in {43101, 40003}:
            self._finish(item, 'needs_authorization', '微信拒绝发送（错误码 %s），请在小程序重新登录并订阅。' % code, clear_credits=True)
        else:
            if code in {40001, 40014, 42001}:
                self._access_token = ''
                self._token_until = 0
            self._finish(item, 'failed', '微信明确拒绝发送（错误码 %s）；请检查模板和服务端配置，未标记为成功。' % code, restore_credit=True)

    def dispatch(self, now=None):
        if not self.config.configured or not self._dispatch_lock.acquire(blocking=False):
            return
        try:
            with self.database.transaction() as db:
                rows = db.execute('''SELECT o.id FROM wechat_outbox o
                    LEFT JOIN wechat_subscriptions s ON s.user_id=o.user_id AND s.app_id=? AND s.template_id=?
                    WHERE o.status IN ('pending','waiting_authorization')
                    ORDER BY CASE WHEN s.credits>0 THEN 0 ELSE 1 END,o.id LIMIT 100''',
                                  (self.config.app_id, self.config.template_id)).fetchall()
            for row in rows:
                item = self._claim(row['id'], self.clock())
                if item:
                    self._send(item, self.clock())
        finally:
            self._dispatch_lock.release()
