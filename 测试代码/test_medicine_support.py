"""Exercise consent, isolation, lifecycle and persisted label notes in a temporary DB."""
from datetime import datetime, timedelta
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient
from backend.main import create_app
from backend.domain import TZ


class MedicineSupport(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'support.sqlite3'
        self.now = datetime.now(TZ).replace(hour=10, minute=0, second=0, microsecond=0)
        self.app = create_app(self.path, lambda: self.now, scheduler_interval=3600)
        self.client = TestClient(self.app).__enter__()
        self.a = self.register('13911110001', '家属甲')
        self.b = self.register('13911110002', '家属乙')
        self.c = self.register('13911110003', '家属丙')

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.temp.cleanup()

    def register(self, phone, name):
        response = self.client.post('/api/auth/register', json={'phone': phone, 'name': name, 'password': 'Hello12345'})
        self.assertEqual(response.status_code, 200, response.text)
        return {'Authorization': 'Bearer ' + response.json()['token']}

    def plan(self, user, name='测试话题药品 5mg'):
        response = self.client.post('/api/plans', headers=user, json={
            'medicine': name, 'dosage': '仅测试', 'days': [0, 1, 2, 3, 4, 5, 6], 'slotKey': 'morning', 'time': '08:00', 'note': ''})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()['plans'][-1]['id']

    def profile(self, user, plan_id, alias):
        response = self.client.patch('/api/companions/profile', headers=user, json={
            'enabled': True, 'alias': alias, 'about': '爱散步', 'planId': plan_id, 'participantConsent': True})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def view(self, user):
        response = self.client.get('/api/companions', headers=user)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def pair(self):
        first, second = self.plan(self.a), self.plan(self.b)
        self.profile(self.a, first, '散步的人')
        self.profile(self.b, second, '读书的人')
        target = self.view(self.a)['candidates'][0]['id']
        response = self.client.post('/api/companions/requests', headers=self.a, json={'targetId': target})
        self.assertEqual(response.status_code, 201, response.text)
        request_id = response.json()['requests'][0]['id']
        return first, second, target, request_id

    def accept(self):
        values = self.pair()
        response = self.client.patch('/api/companions/requests/' + values[-1], headers=self.b, json={'action': 'accept'})
        self.assertEqual(response.status_code, 200, response.text)
        return values

    def test_existing_state_and_defaults_are_non_destructive(self):
        self.assertFalse(self.view(self.a)['profile']['enabled'])
        self.assertFalse(self.view(self.a)['candidates'])
        self.assertEqual(self.client.get('/api/medicines', headers=self.a).json()['items'], [])
        self.assertEqual(self.client.get('/api/medicines').status_code, 401)
        self.assertEqual(self.client.get('/api/companions').status_code, 401)
        self.app.state.database.initialize()
        self.assertFalse(self.view(self.a)['profile']['enabled'])

    def test_medicine_notes_source_scope_and_persistence(self):
        plan_id = self.plan(self.a)
        other_id = self.plan(self.b)
        path = '/api/medicines/' + plan_id
        self.assertEqual(self.client.patch(path, headers=self.a, json={'introduction': '测试资料'}).status_code, 422)
        self.assertEqual(self.client.patch(path, headers=self.a, json={'storage': '测试', 'source': '   '}).status_code, 422)
        note = {'specification': '仅测试 5mg', 'manufacturer': '测试厂家', 'introduction': '<script>仅保存文字</script>',
                'precautions': '仅测试内容', 'storage': '测试用包装原文', 'source': '测试说明书，非实际药品'}
        response = self.client.patch(path, headers=self.a, json=note)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['items'][0]['storage'], note['storage'])
        self.assertEqual(self.client.patch('/api/medicines/' + other_id, headers=self.a, json=note).status_code, 404)
        self.assertEqual(self.client.get('/api/medicines', headers=self.b).json()['items'][0]['source'], '')
        self.assertEqual(self.client.get('/api/state', headers=self.a).json()['plans'][0]['dosage'], '仅测试')
        with TestClient(create_app(self.path, scheduler_interval=3600)) as second:
            saved = second.get('/api/medicines', headers=self.a).json()['items'][0]
            for key, value in note.items():
                self.assertEqual(saved[key], value)
        # Empty notes may be explicitly saved to clear private, user-entered fields.
        self.assertEqual(self.client.patch(path, headers=self.a, json={}).json()['items'][0]['source'], '')

    def test_requires_explicit_consent_and_owned_enabled_plan(self):
        plan_id = self.plan(self.a)
        body = {'enabled': True, 'alias': '昵称', 'planId': plan_id}
        for extra in [{}, {'participantConsent': False}, {'participantConsent': True, 'alias': '  '}]:
            self.assertEqual(self.client.patch('/api/companions/profile', headers=self.a, json=dict(body, **extra)).status_code, 422)
        self.assertEqual(self.client.patch('/api/companions/profile', headers=self.b, json=dict(body, participantConsent=True)).status_code, 409)
        self.client.patch('/api/plans/' + plan_id, headers=self.a, json={'enabled': False})
        self.assertEqual(self.client.patch('/api/companions/profile', headers=self.a, json=dict(body, participantConsent=True)).status_code, 409)

    def test_matching_is_opt_in_exact_text_and_not_diagnosis(self):
        first, second, different = self.plan(self.a), self.plan(self.b), self.plan(self.c, '测试话题药品 10mg')
        self.profile(self.a, first, '甲')
        self.assertEqual(self.view(self.a)['candidates'], [])
        self.profile(self.b, second, '乙')
        self.profile(self.c, different, '丙')
        candidates = self.view(self.a)['candidates']
        self.assertEqual([p['alias'] for p in candidates], ['乙'])
        self.assertEqual(set(candidates[0]), {'id', 'alias', 'about', 'medicine'})
        self.assertNotIn('家属乙', str(candidates))
        self.assertNotIn('13911110002', str(candidates))

    def test_demo_and_independent_accounts_do_not_mix(self):
        demo = {'Authorization': 'Bearer ' + self.client.post('/api/auth/demo').json()['token']}
        state = self.client.get('/api/state', headers=demo).json()
        demo_plan = state['plans'][0]
        plan = self.plan(self.a, demo_plan['medicine'])
        self.profile(self.a, plan, '甲')
        self.profile(demo, demo_plan['id'], '公共演示')
        self.assertEqual(self.view(self.a)['candidates'], [])
        self.assertEqual(self.view(demo)['candidates'], [])

    def test_request_decisions_and_chat_permissions(self):
        _, _, target, request_id = self.pair()
        path = '/api/companions/requests/' + request_id
        chat = '/api/companions/connections/' + request_id + '/messages'
        self.assertEqual(self.client.get(chat, headers=self.a).status_code, 409)
        self.assertEqual(self.client.post(chat, headers=self.a, json={'content': '你好'}).status_code, 409)
        self.assertEqual(self.client.patch(path, headers=self.a, json={'action': 'accept'}).status_code, 403)
        self.assertEqual(self.client.patch(path, headers=self.c, json={'action': 'accept'}).status_code, 404)
        self.assertEqual(self.client.patch(path, headers=self.b, json={'action': 'cancel'}).status_code, 403)
        self.assertEqual(self.client.post('/api/companions/requests', headers=self.a, json={'targetId': target}).status_code, 409)
        self.assertEqual(self.client.patch(path, headers=self.b, json={'action': 'accept'}).status_code, 200)
        self.assertEqual(len(self.view(self.a)['connections']), 1)
        self.assertEqual(self.view(self.a)['candidates'], [])
        self.assertEqual(self.client.get(chat, headers=self.c).status_code, 404)
        self.assertEqual(self.client.post(chat, headers=self.a, json={'content': '   '}).status_code, 422)
        self.assertEqual(self.client.post(chat, headers=self.a, json={'content': 'x' * 501}).status_code, 422)
        response = self.client.post(chat, headers=self.a, json={'content': '你好，今天去散步了吗？'})
        self.assertEqual(response.status_code, 201, response.text)
        self.assertTrue(response.json()['items'][0]['mine'])
        self.assertFalse(self.client.get(chat, headers=self.b).json()['items'][0]['mine'])
        self.assertEqual(self.client.patch(path, headers=self.b, json={'action': 'accept'}).status_code, 409)
        self.assertEqual(self.client.patch(path, headers=self.b, json={'action': 'disconnect'}).status_code, 200)
        self.assertEqual(self.client.get(chat, headers=self.a).status_code, 409)

    def test_decline_and_cancel_then_reinvite_use_new_conversation(self):
        _, _, target, first = self.pair()
        self.assertEqual(self.client.patch('/api/companions/requests/' + first, headers=self.b, json={'action': 'decline'}).status_code, 200)
        second = self.client.post('/api/companions/requests', headers=self.a, json={'targetId': target}).json()['requests'][0]['id']
        self.assertNotEqual(first, second)
        self.assertEqual(self.client.patch('/api/companions/requests/' + second, headers=self.a, json={'action': 'cancel'}).status_code, 200)
        self.assertFalse(self.view(self.b)['requests'])

    def test_withdrawal_closes_relationship_on_both_sides(self):
        _, _, _, request_id = self.accept()
        chat = '/api/companions/connections/' + request_id + '/messages'
        self.client.post(chat, headers=self.a, json={'content': '仅测试问候'})
        self.assertEqual(self.client.patch('/api/companions/profile', headers=self.b, json={'enabled': False}).status_code, 200)
        self.assertFalse(self.view(self.a)['connections'])
        self.assertFalse(self.view(self.a)['candidates'])
        self.assertEqual(self.client.get(chat, headers=self.a).status_code, 409)
        self.assertEqual(self.client.post(chat, headers=self.b, json={'content': '你好'}).status_code, 409)

    def test_pausing_selected_plan_revokes_consent_without_auto_restore(self):
        first, _, _, request_id = self.accept()
        self.client.patch('/api/plans/' + first, headers=self.a, json={'enabled': False})
        self.assertFalse(self.view(self.a)['profile']['enabled'])
        self.assertFalse(self.view(self.b)['connections'])
        self.client.patch('/api/plans/' + first, headers=self.a, json={'enabled': True})
        self.assertFalse(self.view(self.a)['profile']['enabled'])
        self.profile(self.a, first, '新昵称')
        self.assertFalse(self.view(self.a)['connections'])
        self.assertEqual(self.client.get('/api/companions/connections/' + request_id + '/messages', headers=self.a).status_code, 409)

    def test_changing_topic_and_reset_end_existing_relations(self):
        first, _, _, request_id = self.accept()
        alternate = self.plan(self.a, '另一测试药品')
        self.profile(self.a, alternate, '甲')
        self.assertFalse(self.view(self.b)['connections'])
        self.profile(self.a, first, '甲')
        self.assertFalse(self.view(self.a)['connections'])
        self.client.patch('/api/medicines/' + first, headers=self.a, json={'source': '测试说明书'})
        response = self.client.post('/api/demo/reset', headers=self.a)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(self.view(self.a)['profile']['enabled'])
        self.assertFalse(self.client.get('/api/medicines', headers=self.a).json()['items'])
        self.assertFalse(self.view(self.b)['requests'])

    def test_invitation_and_message_limits_reset_with_clock(self):
        _, _, target, request_id = self.accept()
        chat = '/api/companions/connections/' + request_id + '/messages'
        for index in range(60):
            self.assertEqual(self.client.post(chat, headers=self.a, json={'content': str(index)}).status_code, 201)
        self.assertEqual(self.client.post(chat, headers=self.a, json={'content': '超出限制'}).status_code, 429)
        self.now += timedelta(hours=1)
        self.assertEqual(self.client.post(chat, headers=self.a, json={'content': '下一小时'}).status_code, 201)
        self.client.patch('/api/companions/requests/' + request_id, headers=self.a, json={'action': 'disconnect'})
        for _ in range(19):
            response = self.client.post('/api/companions/requests', headers=self.a, json={'targetId': target})
            self.assertEqual(response.status_code, 201, response.text)
            current_id = response.json()['requests'][0]['id']
            self.client.patch('/api/companions/requests/' + current_id, headers=self.a, json={'action': 'cancel'})
        self.assertEqual(self.client.post('/api/companions/requests', headers=self.a, json={'targetId': target}).status_code, 429)


if __name__ == '__main__':
    unittest.main()
