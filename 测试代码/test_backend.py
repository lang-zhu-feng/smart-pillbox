"""Run from the project root: python -m unittest discover -s 测试代码 -v."""
from datetime import datetime, timedelta
from pathlib import Path
import sqlite3
import tempfile
import unittest
from fastapi.testclient import TestClient
from backend.main import create_app
from backend.domain import TZ, seed_state, rebuild_tasks, tick, confirm_reminder

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

    def test_edit_plan_updates_device_schedule_and_checks_conflicts(self):
        state = self.get_state()
        first = next(p for p in state['plans'] if p['slotKey'] == 'morning')
        edited = {key: first[key] for key in ('medicine', 'dosage', 'days', 'slotKey', 'time', 'note')}
        edited['time'] = '08:20'
        result = self.client.put('/api/plans/' + first['id'], headers=self.family, json=edited)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(next(p for p in result.json()['plans'] if p['id'] == first['id'])['time'], '08:20')
        code, hardware = self.key()
        schedule = self.client.get('/api/device/schedule', headers=hardware).json()
        today = next(t for t in schedule['tasks'] if t['slotKey'] == 'morning')
        self.assertEqual(today['startAt'][11:16], '08:20')
        self.now = self.now.replace(hour=9, minute=4)
        self.assertFalse(any(a.get('taskKey') == today['date'] + ':' + today['id'] for a in self.get_state()['alerts']))
        self.now = self.now.replace(minute=5)
        self.assertTrue(any(a.get('taskKey') == today['date'] + ':' + today['id'] for a in self.get_state()['alerts']))
        self.assertEqual(self.client.put('/api/plans/missing', headers=self.family, json=edited).status_code, 404)
        other = dict(edited, medicine='另一项', time='08:30')
        self.assertEqual(self.client.post('/api/plans', headers=self.family, json=other).status_code, 409)
        other['time'] = '08:20'
        second = self.client.post('/api/plans', headers=self.family, json=other).json()
        second_id = next(p['id'] for p in second['plans'] if p['medicine'] == '另一项')
        self.assertEqual(self.client.put('/api/plans/' + second_id, headers=self.family,
                                         json=dict(other, time='08:30')).status_code, 409)

    def test_delete_plan_updates_device_schedule_and_keeps_history(self):
        state = self.get_state()
        plan = next(p for p in state['plans'] if p['slotKey'] == 'morning')
        task_id = str(self.now.weekday()) + '-morning'
        self.client.post('/api/demo/tasks/' + task_id + '/open', headers=self.family)
        before = len(self.get_state()['history'])
        _, hardware = self.key()
        self.assertEqual(self.client.delete('/api/plans/' + plan['id'], headers=hardware).status_code, 401)
        result = self.client.delete('/api/plans/' + plan['id'], headers=self.family)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertFalse(any(p['id'] == plan['id'] for p in result.json()['plans']))
        self.assertEqual(len(result.json()['history']), before)
        today = next(t for t in self.client.get('/api/device/schedule', headers=hardware).json()['tasks']
                     if t['slotKey'] == 'morning')
        self.assertEqual(today['status'], 'NO_MEDICATION')
        self.assertFalse(today['medicines'])
        self.assertEqual(self.client.delete('/api/plans/' + plan['id'], headers=self.family).status_code, 404)
        self.assertEqual(self.client.options('/api/plans/' + plan['id'], headers={
            'Origin': 'http://localhost:8766', 'Access-Control-Request-Method': 'DELETE'
        }).status_code, 200)

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
        self.assertNotIn('online', state['device'])
        self.assertFalse(state['device']['hasConnected'])
        self.assertEqual(self.client.post('/api/demo/reset', headers=self.family).status_code, 200)

    def test_hardware_events_without_heartbeat(self):
        code, hardware = self.key()
        self.assertEqual(self.client.post('/api/device/heartbeat', headers=hardware, json={'deviceCode': code}).status_code, 404)
        integration = self.client.get('/api/device/integration', headers=self.family).json()
        for field in ['heartbeatPath', 'heartbeatIntervalSeconds', 'offlineAfterSeconds']:
            self.assertNotIn(field, integration)
        self.assertFalse(self.get_state()['device']['hasConnected'])
        schedule = self.client.get('/api/device/schedule', headers=hardware).json()
        self.assertEqual(len(schedule['tasks']), 3)
        body = {'deviceCode': code, 'eventId': 'event-1', 'slotKey': 'morning', 'occurredAt': self.now.isoformat(), 'battery': 78}
        self.assertEqual(self.client.post('/api/device/events', headers=self.family, json=body).status_code, 401)
        self.assertEqual(self.client.post('/api/device/events', headers=hardware, json=dict(body, deviceCode='wrong')).status_code, 403)
        result = self.client.post('/api/device/events', headers=hardware, json=body)
        self.assertEqual(result.status_code, 200, result.text)
        state = self.get_state()
        self.assertEqual(state['history'][0]['source'], 'hardware')
        before = len(state['history'])
        self.assertTrue(self.client.post('/api/device/events', headers=hardware, json=body).json()['duplicate'])
        self.assertEqual(len(self.get_state()['history']), before)
        self.assertEqual(self.client.post('/api/device/events', headers=hardware, json=dict(body, battery=20)).status_code, 409)
        self.assertEqual(self.client.post('/api/device/events', headers=hardware, json=dict(body, eventId='future', occurredAt=(self.now + timedelta(minutes=5)).isoformat())).status_code, 422)
        self.assertEqual(self.client.post('/api/device/events', headers=hardware, json=dict(body, eventId='early', occurredAt=(self.now - timedelta(minutes=1)).isoformat())).status_code, 409)
        self.assertEqual(self.client.post('/api/device/events', headers=hardware, json=dict(body, eventId='naive', occurredAt=self.now.replace(tzinfo=None).isoformat())).status_code, 422)
        self.assertEqual(self.client.post('/api/demo/reset', headers=self.family).status_code, 409)
        last_seen = state['device']['lastHardwareSeen']
        self.now += timedelta(hours=2)
        later = self.get_state()['device']
        self.assertTrue(later['hasConnected'])
        self.assertNotIn('online', later)
        self.assertEqual(later['lastHardwareSeen'], last_seen)
        self.key()
        self.assertEqual(self.client.get('/api/device/schedule', headers=hardware).status_code, 401)

    def test_reset_today_keeps_binding_and_plans_but_allows_new_test_time(self):
        code, hardware = self.key()
        before = self.get_state()
        body = {'deviceCode': code, 'eventId': 'first-test-open', 'slotKey': 'morning',
                'occurredAt': self.now.isoformat()}
        self.assertEqual(self.client.post('/api/device/events', headers=hardware, json=body).status_code, 200)
        self.assertEqual(self.get_state()['tasks'][self.now.weekday()]['status'], 'COMPLETED')
        reset = self.client.post('/api/demo/reset-today', headers=self.family)
        self.assertEqual(reset.status_code, 200, reset.text)
        state = reset.json()
        self.assertEqual(state['plans'], before['plans'])
        self.assertEqual(state['device']['code'], code)
        self.assertTrue(state['device']['hasConnected'])
        self.assertFalse(any(item['date'] == self.now.date().isoformat() for item in state['history']))
        schedule = self.client.get('/api/device/schedule', headers=hardware)
        self.assertEqual(schedule.status_code, 200)
        self.assertEqual(schedule.json()['demoResetVersion'], 1)
        morning = next(task for task in schedule.json()['tasks'] if task['slotKey'] == 'morning')
        self.assertTrue(morning['resetSuppressed'])
        db = sqlite3.connect(self.path)
        try:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM device_events').fetchone()[0], 0)
        finally:
            db.close()
        self.assertEqual(self.client.post('/api/device/events', headers=hardware, json=body).status_code, 409)
        self.now += timedelta(hours=1)
        still_reset = self.get_state()
        self.assertFalse(any(item.get('taskKey', '').startswith(self.now.date().isoformat() + ':')
                             for item in still_reset['alerts']))
        plan = next(plan for plan in state['plans'] if plan['slotKey'] == 'morning')
        details = {key: plan[key] for key in ('medicine', 'dosage', 'slotKey', 'time', 'days', 'note')}
        details['time'] = '09:02'
        changed = self.client.put('/api/plans/' + plan['id'], headers=self.family, json=details)
        self.assertEqual(changed.status_code, 200, changed.text)
        self.now += timedelta(minutes=2)
        schedule = self.client.get('/api/device/schedule', headers=hardware).json()
        morning = next(task for task in schedule['tasks'] if task['slotKey'] == 'morning')
        self.assertFalse(morning.get('resetSuppressed', False))
        body.update(eventId='second-test-open', occurredAt=self.now.isoformat())
        self.assertEqual(self.client.post('/api/device/events', headers=hardware, json=body).status_code, 200)

    def test_hardware_record_after_demo_is_retained(self):
        task_id = str(self.now.weekday()) + '-morning'
        self.client.post('/api/demo/tasks/' + task_id + '/open', headers=self.family)
        code, hardware = self.key()
        body = {'deviceCode': code, 'eventId': 'real-after-demo', 'slotKey': 'morning', 'occurredAt': self.now.isoformat()}
        self.assertEqual(self.client.post('/api/device/events', headers=hardware, json=body).status_code, 200)
        self.assertEqual(self.get_state()['history'][0]['source'], 'hardware')

    def test_family_confirm_stops_this_round_without_faking_opening(self):
        code, hardware = self.key()
        task_id = str(self.now.weekday()) + '-morning'
        path = '/api/tasks/' + task_id + '/confirm'
        self.now = self.now.replace(hour=7, minute=59)
        self.assertEqual(self.client.post(path, headers=self.family).status_code, 409)
        self.now = self.now.replace(hour=8, minute=25)
        self.assertEqual(self.client.post(path, headers=hardware).status_code, 401)
        first = self.client.post(path, headers=self.family)
        self.assertEqual(first.status_code, 200, first.text)
        state = first.json()
        task = next(t for t in state['tasks'] if t['id'] == task_id)
        self.assertEqual(task['status'], 'CONFIRMED')
        self.assertEqual(state['history'][0]['result'], 'CONFIRMED')
        self.assertFalse(state['device']['hasConnected'])
        before = len(state['history'])
        self.assertEqual(len(self.client.post(path, headers=self.family).json()['history']), before)
        self.assertEqual(next(t for t in self.client.get('/api/device/schedule', headers=hardware).json()['tasks']
                              if t['id'] == task_id)['status'], 'CONFIRMED')
        self.now = self.now.replace(hour=8, minute=45)
        self.assertFalse(self.get_state()['alerts'])
        self.now += timedelta(minutes=1)
        body = {'deviceCode': code, 'eventId': 'opened-after-confirm', 'slotKey': 'morning',
                'occurredAt': self.now.isoformat()}
        self.assertEqual(self.client.post('/api/device/events', headers=hardware, json=body).status_code, 200)
        self.assertEqual(self.get_state()['history'][0]['source'], 'hardware')

class Rules(unittest.TestCase):
    def test_rescheduling_today_requires_new_family_confirmation(self):
        start = datetime(2026, 10, 15, 8, 0, tzinfo=TZ)
        state = seed_state('测试家庭', True)
        rebuild_tasks(state, start)
        task = next(t for t in state['tasks'] if t['id'] == '3-morning')
        tick(state, start + timedelta(minutes=20))
        confirm_reminder(state, task, start + timedelta(minutes=20))
        state['plans'][0]['time'] = '08:30'
        rebuild_tasks(state, start + timedelta(minutes=20))
        updated = next(t for t in state['tasks'] if t['id'] == '3-morning')
        self.assertEqual(updated['status'], 'PENDING')
        tick(state, start + timedelta(minutes=30))
        self.assertEqual(updated['status'], 'REMINDING')

    def test_only_sensor_equipped_slot_creates_real_family_alert(self):
        start = datetime(2026, 10, 15, 8, 0, tzinfo=TZ)
        state = seed_state('测试家庭', False)
        for slot, time in [('morning', '08:00'), ('noon', '12:00')]:
            state['plans'].append({'id': slot, 'medicine': '测试药', 'dosage': '按医嘱',
                                   'slotKey': slot, 'time': time, 'days': [3], 'enabled': True, 'note': ''})
        rebuild_tasks(state, start)
        tick(state, start + timedelta(hours=4, minutes=45))
        self.assertEqual(len(state['alerts']), 1)
        self.assertEqual(state['alerts'][0]['taskId'], '3-morning')
        noon = next(task for task in state['tasks'] if task['id'] == '3-noon')
        self.assertEqual(noon['status'], 'OVERDUE')

    def test_legacy_online_flag_is_removed(self):
        state = seed_state('测试', True)
        state['device']['online'] = True
        tick(state, datetime.now(TZ))
        self.assertNotIn('online', state['device'])

    def test_reminders_grace_week_and_real_device_timeout(self):
        start = datetime(2026, 10, 15, 8, 0, tzinfo=TZ)
        state = seed_state('测试', True)
        rebuild_tasks(state, start)
        task = next(t for t in state['tasks'] if t['id'] == '3-morning')
        for minutes, expected in [(0, 1), (10, 2), (20, 3), (30, 4), (40, 5)]:
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
