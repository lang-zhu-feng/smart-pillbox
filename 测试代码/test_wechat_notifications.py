"""Offline only: python -m unittest discover -s 测试代码 -p test_wechat_notifications.py -v."""
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
import json
import tempfile
import threading
import unittest

import httpx
from fastapi.testclient import TestClient

from backend.domain import TZ, tick, complete
from backend.main import create_app
from backend.wechat_notifications import WechatConfig


CONFIG = WechatConfig('test-app', 'test-secret-not-real', 'approved-test-template',
                      {'name': 'thing1', 'time': 'time2', 'remark': 'thing3'})


class FakeWechat:
    def __init__(self):
        self.login_calls = []
        self.send_bodies = []
        self.token_calls = 0
        self.send_response = {'errcode': 0, 'errmsg': 'ok'}
        self.send_error = None
        self.on_token = None
        self.sent = threading.Event()
        self.transport = httpx.MockTransport(self.handle)

    def handle(self, request):
        if request.url.path == '/sns/jscode2session':
            code = request.url.params['js_code']
            self.login_calls.append(code)
            if code.startswith('bad'):
                return httpx.Response(200, json={'errcode': 40029, 'errmsg': 'invalid code'})
            return httpx.Response(200, json={'openid': 'openid-' + code.split('-')[0], 'session_key': 'not-persisted'})
        if request.url.path == '/cgi-bin/token':
            self.token_calls += 1
            if self.on_token:
                self.on_token()
            return httpx.Response(200, json={'access_token': 'fake-access-token', 'expires_in': 7200})
        if request.url.path == '/cgi-bin/message/subscribe/send':
            self.send_bodies.append(json.loads(request.content))
            self.sent.set()
            if self.send_error:
                raise self.send_error('fake failure', request=request)
            return httpx.Response(200, json=self.send_response)
        raise AssertionError('Unexpected fake WeChat route')


class WechatNotificationsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'notifications.sqlite3'
        self.now = datetime.now(TZ).replace(hour=8, minute=0, second=0, microsecond=0)
        self.fake = FakeWechat()
        self.app = create_app(self.path, lambda: self.now, notification_config=CONFIG,
                              notification_transport=self.fake.transport, scheduler_interval=300)
        self.client = TestClient(self.app).__enter__()
        self.alice = self.register('13900000101', '家属甲')
        self.bob = self.register('13900000102', '家属乙')

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.temp.cleanup()

    def register(self, phone, name, client=None):
        response = (client or self.client).post('/api/auth/register',
            json={'phone': phone, 'name': name, 'password': 'Hello12345'})
        self.assertEqual(response.status_code, 200, response.text)
        return {'Authorization': 'Bearer ' + response.json()['token']}

    def authorize(self, headers=None, code='alice-1', client=None):
        return (client or self.client).post('/api/notifications/wechat/authorize',
            headers=headers or self.alice, json={'code': code, 'templateId': CONFIG.template_id})

    def status(self, headers=None, client=None):
        response = (client or self.client).get('/api/notifications/wechat', headers=headers or self.alice)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def plan(self, headers=None, client=None):
        response = (client or self.client).post('/api/plans', headers=headers or self.alice,
            json={'medicine': '测试物品', 'dosage': '仅演示', 'slotKey': 'morning',
                  'time': '08:00', 'days': [self.now.weekday()]})
        self.assertEqual(response.status_code, 201, response.text)

    def uid(self, phone='13900000101'):
        with self.app.state.database.transaction() as db:
            return db.execute('SELECT id FROM users WHERE phone=?', (phone,)).fetchone()['id']

    def capture_without_dispatch(self):
        database = self.app.state.database
        uid = self.uid()
        with database.transaction() as db:
            state = database.load(db, uid)
            tick(state, self.now)
            self.app.state.notifications.capture(db, uid, state, self.now)
            database.save(db, uid, state)

    def test_missing_configuration_never_calls_wechat(self):
        path = Path(self.temp.name) / 'unconfigured.sqlite3'
        app = create_app(path, lambda: self.now, notification_config=WechatConfig(),
                         notification_transport=self.fake.transport, scheduler_interval=300)
        with TestClient(app) as client:
            headers = self.register('13900000103', '未配置账号', client)
            status = self.status(headers, client)
            self.assertFalse(status['configured'])
            self.assertFalse(status['available'])
            self.assertEqual(status['templateId'], '')
            self.assertEqual(self.authorize(headers, 'none-1', client).status_code, 503)
            self.plan(headers, client)
            self.now += timedelta(minutes=45)
            app.state.advance_rules()
            with app.state.database.transaction() as db:
                state = app.state.database.load(db, db.execute('SELECT id FROM users WHERE phone=?', ('13900000103',)).fetchone()['id'])
                self.assertEqual(len(state['alerts']), 1)
            self.assertEqual(self.fake.login_calls, [])
            self.assertEqual(self.fake.token_calls, 0)
            self.assertEqual(self.fake.send_bodies, [])

    def test_template_fields_must_be_explicit_and_valid(self):
        for fields in [None, {}, {'name': 'thing1', 'time': 'time2'},
                       {'name': 'thing1', 'time': 'time2', 'remark': 'thing1'},
                       {'name': 'thing1', 'time': 'thing2', 'remark': 'thing3'}]:
            self.assertFalse(replace(CONFIG, fields=fields).configured)
        self.assertTrue(CONFIG.configured)
        self.assertFalse(replace(CONFIG, miniprogram_state='invalid').configured)

    def test_authentication_isolation_and_no_secret_fields(self):
        self.assertEqual(self.client.get('/api/notifications/wechat').status_code, 401)
        self.assertEqual(self.authorize().status_code, 200)
        self.assertEqual(self.status()['authorizedCredits'], 1)
        self.assertEqual(self.status(self.bob)['authorizedCredits'], 0)
        self.assertEqual(self.authorize(self.bob, 'alice-1').status_code, 409)
        # Different login codes still cannot bind another family's WeChat identity.
        self.assertEqual(self.authorize(self.bob, 'alice-2').status_code, 409)
        self.assertEqual(self.status(self.bob)['authorizedCredits'], 0)
        result = self.status()
        self.assertEqual(set(result), {'configured', 'available', 'unavailableReason', 'templateId',
                                      'authorizedCredits', 'lastDeliveryStatus', 'lastDeliveryMessage'})
        serialized = json.dumps(result)
        for secret in ['openid', CONFIG.app_secret, 'session_key', 'fake-access-token']:
            self.assertNotIn(secret, serialized)

    def test_duplicate_login_code_does_not_grant_again(self):
        self.assertEqual(self.authorize().status_code, 200)
        self.assertEqual(self.authorize().status_code, 200)
        self.assertEqual(self.status()['authorizedCredits'], 1)
        self.assertEqual(self.fake.login_calls, ['alice-1'])
        self.assertEqual(self.authorize(code='alice-2').status_code, 200)
        self.assertEqual(self.status()['authorizedCredits'], 2)
        self.assertEqual(self.authorize(code='bad-code').status_code, 422)
        self.assertEqual(self.authorize(code='bad-code').status_code, 409)

    def test_demo_accounts_and_demo_alerts_never_send(self):
        demo = {'Authorization': 'Bearer ' + self.client.post('/api/auth/demo').json()['token']}
        self.assertFalse(self.status(demo)['available'])
        self.assertEqual(self.authorize(demo, 'demo-1').status_code, 403)
        self.plan()
        self.assertEqual(self.authorize().status_code, 200)
        task_id = str(self.now.weekday()) + '-morning'
        self.assertEqual(self.client.post('/api/demo/tasks/' + task_id + '/overdue', headers=self.alice).status_code, 200)
        self.now += timedelta(minutes=45)
        self.app.state.advance_rules()
        self.assertEqual(self.fake.send_bodies, [])

    def test_rule_outbox_deduplicates_and_sent_only_means_api_acceptance(self):
        self.plan()
        self.authorize()
        self.now += timedelta(minutes=44)
        self.app.state.advance_rules()
        self.assertEqual(len(self.fake.send_bodies), 0)
        self.now += timedelta(minutes=1)
        self.app.state.advance_rules()
        self.app.state.advance_rules()
        self.assertEqual(len(self.fake.send_bodies), 1)
        body = self.fake.send_bodies[0]
        self.assertEqual(body['touser'], 'openid-alice')
        self.assertEqual(body['page'], 'pages/alerts/alerts')
        self.assertEqual(body['miniprogram_state'], 'formal')
        self.assertEqual(set(body['data']), {'thing1', 'time2', 'thing3'})
        status = self.status()
        self.assertEqual(status['lastDeliveryStatus'], 'sent')
        self.assertIn('不代表', status['lastDeliveryMessage'])
        self.assertEqual(status['authorizedCredits'], 0)
        self.assertEqual(self.status(self.bob)['lastDeliveryStatus'], 'not_sent')
        with self.app.state.database.transaction() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM wechat_outbox').fetchone()[0], 1)

    def test_opened_task_is_cancelled_before_dispatch(self):
        self.plan()
        self.authorize()
        self.now += timedelta(minutes=45)
        self.capture_without_dispatch()
        keys = self.client.post('/api/device/credentials', headers=self.alice).json()
        response = self.client.post('/api/device/events',
            headers={'Authorization': 'Bearer ' + keys['deviceToken']},
            json={'deviceCode': keys['deviceCode'], 'eventId': 'open-after-queue',
                  'slotKey': 'morning', 'occurredAt': self.now.isoformat()})
        self.assertEqual(response.status_code, 200, response.text)
        self.app.state.notifications.dispatch()
        self.assertEqual(self.fake.send_bodies, [])
        self.assertEqual(self.fake.token_calls, 0)
        self.assertEqual(self.status()['lastDeliveryStatus'], 'cancelled')
        self.assertEqual(self.status()['authorizedCredits'], 1)

    def test_family_confirmation_cancels_unsent_overdue_message(self):
        self.plan()
        self.authorize()
        self.now += timedelta(minutes=45)
        self.capture_without_dispatch()
        task_id = str(self.now.weekday()) + '-morning'
        response = self.client.post('/api/tasks/' + task_id + '/confirm', headers=self.alice)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(next(t for t in response.json()['tasks'] if t['id'] == task_id)['status'], 'CONFIRMED')
        self.app.state.notifications.dispatch()
        self.assertEqual(self.fake.send_bodies, [])
        self.assertEqual(self.status()['lastDeliveryStatus'], 'cancelled')
        self.assertEqual(self.status()['authorizedCredits'], 1)

    def test_rechecks_after_token_fetch_and_restores_unused_credit(self):
        self.plan()
        self.authorize()
        self.now += timedelta(minutes=45)
        def close_task():
            database = self.app.state.database
            with database.transaction() as db:
                uid = db.execute('SELECT id FROM users WHERE phone=?', ('13900000101',)).fetchone()['id']
                state = database.load(db, uid)
                task = next(t for t in state['tasks'] if t['id'] == str(self.now.weekday()) + '-morning')
                complete(state, task, self.now, 'hardware', 'opening-during-token-fetch')
                database.save(db, uid, state)
        self.fake.on_token = close_task
        self.app.state.advance_rules()
        self.assertEqual(self.fake.send_bodies, [])
        self.assertEqual(self.status()['lastDeliveryStatus'], 'cancelled')
        self.assertEqual(self.status()['authorizedCredits'], 1)

    def test_permission_failure_requires_new_subscription_and_never_claims_success(self):
        self.plan()
        self.authorize()
        self.fake.send_response = {'errcode': 43101, 'errmsg': 'user refuse'}
        self.now += timedelta(minutes=45)
        self.app.state.advance_rules()
        status = self.status()
        self.assertEqual(status['lastDeliveryStatus'], 'needs_authorization')
        self.assertEqual(status['authorizedCredits'], 0)
        self.assertIn('重新', status['lastDeliveryMessage'])
        self.app.state.advance_rules()
        self.assertEqual(len(self.fake.send_bodies), 1)
        self.authorize(code='alice-2')
        self.fake.send_response = {'errcode': 0}
        self.app.state.advance_rules()
        self.assertEqual(len(self.fake.send_bodies), 2)
        self.assertEqual(self.status()['lastDeliveryStatus'], 'sent')

    def test_known_wechat_failure_is_not_success_and_is_not_blindly_retried(self):
        self.plan()
        self.authorize()
        self.fake.send_response = {'errcode': 47003, 'errmsg': 'invalid template data'}
        self.now += timedelta(minutes=45)
        self.app.state.advance_rules()
        self.app.state.advance_rules()
        self.assertEqual(self.status()['lastDeliveryStatus'], 'failed')
        self.assertEqual(self.status()['authorizedCredits'], 1)
        self.assertEqual(len(self.fake.send_bodies), 1)

    def test_ambiguous_send_is_persisted_and_never_retried(self):
        self.plan()
        self.authorize()
        self.fake.send_error = httpx.ReadTimeout
        self.now += timedelta(minutes=45)
        self.app.state.advance_rules()
        self.app.state.advance_rules()
        self.assertEqual(self.status()['lastDeliveryStatus'], 'unknown')
        self.assertEqual(self.status()['authorizedCredits'], 0)
        app = create_app(self.path, lambda: self.now, notification_config=CONFIG,
                         notification_transport=self.fake.transport, scheduler_interval=300)
        with TestClient(app) as client:
            app.state.advance_rules()
            self.assertEqual(self.status(client=client)['lastDeliveryStatus'], 'unknown')
        self.assertEqual(len(self.fake.send_bodies), 1)

    def test_background_scheduler_dispatches_without_state_requests(self):
        path = Path(self.temp.name) / 'background.sqlite3'
        app = create_app(path, lambda: self.now, notification_config=CONFIG,
                         notification_transport=self.fake.transport, scheduler_interval=0.02)
        with TestClient(app) as client:
            headers = self.register('13900000104', '后台测试家属', client)
            self.plan(headers, client)
            self.assertEqual(self.authorize(headers, 'background-1', client).status_code, 200)
            self.now += timedelta(minutes=45)
            # No GET /api/state (or any other page request) after moving the clock.
            self.assertTrue(self.fake.sent.wait(3), '后台任务没有独立派发通知')
        self.assertEqual(len(self.fake.send_bodies), 1)


if __name__ == '__main__':
    unittest.main()
