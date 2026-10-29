"""Run from the project root: python -m unittest discover -s 测试代码 -v."""
from datetime import datetime, timedelta
from pathlib import Path
import tempfile
import unittest
from fastapi.testclient import TestClient
from backend.main import create_app
from backend.domain import TZ, seed_state, rebuild_tasks, tick

class API(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'test.sqlite3'
        self.now = datetime.now(TZ).replace(hour=8, minute=0, second=0, microsecond=0)
        self.app = create_app(self.path, lambda: self.now)
        self.client = TestClient(self.app).__enter__()
        self.family = {'Authorization': 'Bearer ' + self.client.post('/api/auth/demo').json()['token']}

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.temp.cleanup()

    def get_state(self, headers=None):
        response = self.client.get('/api/state', headers=headers or self.family)
        self.assertEqual(response.status_code, 200)
        return response.json()

    def key(self):
        result = self.client.post('/api/device/credentials', headers=self.family).json()
        return result['deviceCode'], {'Authorization': 'Bearer ' + result['deviceToken']}

    def test_preview_and_auth(self):
        self.assertEqual(self.client.get('/health').json()['status'], 'healthy')
        self.assertIn('家庭档案', self.client.get('/preview').text)
        self.assertEqual(self.client.get('/assets/demo.js').status_code, 200)
        self.assertEqual(self.client.get('/api/state').status_code, 401)
        session = self.client.post('/api/auth/register', json={'phone': '13900000001', 'name': '小刘', 'password': 'Hello12345'}).json()
        headers = {'Authorization': 'Bearer ' + session['token']}
        state = self.get_state(headers)
        self.assertEqual(len(state['tasks']), 21)
        self.assertFalse(state['plans'])
        self.assertTrue(all(t['status'] == 'NO_MEDICATION' for t in state['tasks']))
        self.assertNotEqual(state['device']['code'], self.get_state()['device']['code'])
        task_id = state['tasks'][0]['id']
        self.assertEqual(self.client.post('/api/demo/tasks/' + task_id + '/open', headers=headers).status_code, 409)
        self.assertEqual(self.client.post('/api/auth/logout', headers=headers).status_code, 200)
        self.assertEqual(self.client.get('/api/state', headers=headers).status_code, 401)

    def test_retry_lock_survives_requests_and_database(self):
        for count in [2, 1, 0]:
            result = self.client.post('/api/auth/login', json={'phone': '13800000000', 'password': 'wrong'})
            self.assertEqual(result.json()['detail']['remainingAttempts'], count)
        self.assertEqual(self.client.post('/api/auth/login', json={'phone': '13800000000', 'password': 'Demo12345'}).status_code, 429)
        with TestClient(create_app(self.path)) as second:
            self.assertEqual(second.post('/api/auth/login', json={'phone': '13800000000', 'password': 'Demo12345'}).status_code, 429)

    def test_plan_profile_and_persistence(self):
        state = self.get_state()
        profile = dict(state['elder'], homeTitle='有阳光的家', name='奶奶')
        self.assertEqual(self.client.patch('/api/profile', headers=self.family, json=profile).status_code, 200)
        plan = state['plans'][0]
        result = self.client.patch('/api/plans/' + plan['id'], headers=self.family, json={'enabled': False}).json()
        self.assertTrue(all(t['status'] == 'NO_MEDICATION' for t in result['tasks'] if t['slotKey'] == 'morning'))
        body = {'medicine': '测试示例', 'dosage': '按医嘱', 'days': [0, 6], 'slotKey': 'morning', 'time': '09:00', 'note': ''}
        result = self.client.post('/api/plans', headers=self.family, json=body)
        self.assertEqual(result.status_code, 201)
        tasks = [t for t in result.json()['tasks'] if t['slotKey'] == 'morning' and t['medicines']]
        self.assertEqual(len(tasks), 2)
        self.assertTrue(all(t['time'].startswith('09:00') for t in tasks))
        self.assertEqual(self.client.patch('/api/plans/' + plan['id'], headers=self.family, json={'enabled': True}).status_code, 409)
        with TestClient(create_app(self.path)) as second:
            self.assertEqual(second.get('/api/state', headers=self.family).json()['elder']['homeTitle'], '有阳光的家')
        for bad in [[7], [0, 0], [True]]:
            self.assertEqual(self.client.post('/api/plans', headers=self.family, json=dict(body, days=bad)).status_code, 422)

    def test_demo_history_alerts_and_offline(self):
        task = self.get_state()['tasks'][0]
        state = self.client.post('/api/demo/tasks/' + task['id'] + '/overdue', headers=self.family).json()
        self.assertEqual(state['alerts'][0]['source'], 'demo')
        self.assertEqual(state['history'][0]['result'], 'OVERDUE')
        count = len(state['alerts'])
        self.assertEqual(len(self.client.post('/api/demo/tasks/' + task['id'] + '/overdue', headers=self.family).json()['alerts']), count)
        state = self.client.post('/api/alerts/read-all', headers=self.family).json()
        self.assertTrue(all(a['read'] for a in state['alerts']))
        state = self.client.post('/api/demo/tasks/' + task['id'] + '/open', headers=self.family).json()
        self.assertEqual(state['history'][0]['source'], 'demo')
        self.assertFalse(state['device']['online'])
        self.assertFalse(state['device']['hasConnected'])
        self.assertEqual(self.client.post('/api/demo/reset', headers=self.family).status_code, 200)

    def test_hardware_auth_events_idempotency_and_offline(self):
        code, hardware = self.key()
        heartbeat = {'deviceCode': code, 'battery': 80}
        self.assertEqual(self.client.post('/api/device/heartbeat', headers=self.family, json=heartbeat).status_code, 401)
        self.assertEqual(self.client.post('/api/device/heartbeat', headers=hardware, json=dict(heartbeat, deviceCode='wrong')).status_code, 403)
        self.assertEqual(self.client.post('/api/device/heartbeat', headers=hardware, json=heartbeat).status_code, 200)
        self.assertTrue(self.get_state()['device']['online'])
        schedule = self.client.get('/api/device/schedule', headers=hardware).json()
        self.assertEqual(len(schedule['tasks']), 3)
        body = {'deviceCode': code, 'eventId': 'event-1', 'slotKey': 'morning', 'occurredAt': self.now.isoformat(), 'battery': 78}
        result = self.client.post('/api/device/events', headers=hardware, json=body)
        self.assertEqual(result.status_code, 200, result.text)
        state = self.get_state()
        self.assertEqual(state['history'][0]['source'], 'hardware')
        before = len(state['history'])
        self.assertTrue(self.client.post('/api/device/events', headers=hardware, json=body).json()['duplicate'])
        self.assertEqual(len(self.get_state()['history']), before)
        self.assertEqual(self.client.post('/api/device/events', headers=hardware, json=dict(body, battery=20)).status_code, 409)
        self.assertEqual(self.client.post('/api/device/events', headers=hardware, json=dict(body, eventId='future', occurredAt=(self.now + timedelta(minutes=5)).isoformat())).status_code, 422)
        self.assertEqual(self.client.post('/api/device/events', headers=hardware, json=dict(body, eventId='naive', occurredAt=self.now.replace(tzinfo=None).isoformat())).status_code, 422)
        self.assertEqual(self.client.post('/api/demo/reset', headers=self.family).status_code, 409)
        self.now += timedelta(seconds=91)
        self.assertFalse(self.get_state()['device']['online'])
        self.key()
        self.assertEqual(self.client.post('/api/device/heartbeat', headers=hardware, json=heartbeat).status_code, 401)

    def test_hardware_record_after_demo_is_retained(self):
        task_id = str(self.now.weekday()) + '-morning'
        self.client.post('/api/demo/tasks/' + task_id + '/open', headers=self.family)
        code, hardware = self.key()
        body = {'deviceCode': code, 'eventId': 'real-after-demo', 'slotKey': 'morning', 'occurredAt': self.now.isoformat()}
        self.assertEqual(self.client.post('/api/device/events', headers=hardware, json=body).status_code, 200)
        self.assertEqual(self.get_state()['history'][0]['source'], 'hardware')

class Rules(unittest.TestCase):
    def test_reminders_grace_week_and_real_device_timeout(self):
        start = datetime(2026, 10, 15, 8, 0, tzinfo=TZ)
        state = seed_state('测试', True)
        rebuild_tasks(state, start)
        task = next(t for t in state['tasks'] if t['id'] == '3-morning')
        for minutes, expected in [(0, 1), (10, 2), (20, 3), (30, 3)]:
            tick(state, start + timedelta(minutes=minutes))
            self.assertEqual(task['reminderCount'], expected)
        tick(state, start + timedelta(minutes=31))
        self.assertEqual(task['status'], 'OVERDUE')
        self.assertFalse(state['alerts'])
        tick(state, start + timedelta(minutes=45))
        self.assertEqual(len(state['alerts']), 1)
        tick(state, start + timedelta(minutes=55))
        self.assertEqual(len(state['alerts']), 1)
        tick(state, start + timedelta(days=7))
        self.assertEqual(len(state['tasks']), 21)
        self.assertEqual(state['meta']['weekStart'], '2026-10-19')
        self.assertNotEqual(state['tasks'][3]['date'], task['date'])

if __name__ == '__main__': unittest.main()
