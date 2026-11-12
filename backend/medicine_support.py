"""Label-based medicine notes and explicitly opted-in, account-scoped companions."""
from typing import Literal
import unicodedata
import uuid

from fastapi import Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator


STORAGE_TIPS = [
    '先核对实际药品包装和说明书的贮藏要求；不确定能否分装时，先向药师确认并保留原包装。',
    '按说明书要求防潮、避光并及时盖好；远离水源、热源和阳光直射，放在儿童不能接触的地方。',
    '需要冷藏或特殊包装的药品，不因使用普通药盒而改变原有贮藏条件。',
    '分装不延长有效期；保留药名、批号、有效期和说明书，使用前检查包装及外观。',
]
RETRIEVAL_TIPS = [
    '结构改进方案：可取出的单格内胆、圆角浅底和宽口取药；便于将模拟物倒入独立接药小托盘。',
    '结构改进方案：加宽开盖拨片、清晰标识与防滑底座，先用模拟物验证老人是否方便操作。',
    '密封圈、不透光外壳和独立分格仅为待验证设计；需检查清洁、闭合及反复开合后的状态。',
]
SOURCES = [
    {'title': '西藏自治区药品监督管理局：怎样管理家庭药箱',
     'url': 'https://mpa.xizang.gov.cn/yp/ypkp/202101/t20210113_186986.html'},
    {'title': 'MedlinePlus：Storing your medicines',
     'url': 'https://www.medlineplus.gov/ency/patientinstructions/000534.htm'},
]
PROTOTYPE_NOTICE = '当前药盒仍是原型，不能实际存药。密封、防潮、避光和便捷取药尚未完成实物验证；不提供温湿度监测、主动控温或除湿。'


def medicine_key(name):
    # Only normalize spelling/spacing. Never infer an ingredient, disease or substitution.
    return ' '.join(unicodedata.normalize('NFKC', name).casefold().split())


def initialize_support(db):
    for sql in [
        '''CREATE TABLE IF NOT EXISTS medicine_notes (
            user_id TEXT REFERENCES users(id), medicine_key TEXT, specification TEXT NOT NULL,
            manufacturer TEXT NOT NULL, introduction TEXT NOT NULL, precautions TEXT NOT NULL,
            storage TEXT NOT NULL, source TEXT NOT NULL, updated_at TEXT NOT NULL,
            PRIMARY KEY(user_id, medicine_key))''',
        '''CREATE TABLE IF NOT EXISTS companion_profiles (
            user_id TEXT PRIMARY KEY REFERENCES users(id), enabled INTEGER NOT NULL DEFAULT 0,
            alias TEXT NOT NULL, about TEXT NOT NULL, plan_id TEXT NOT NULL,
            medicine_key TEXT NOT NULL, medicine TEXT NOT NULL, consent_at TEXT NOT NULL)''',
        '''CREATE TABLE IF NOT EXISTS companion_requests (
            id TEXT PRIMARY KEY, sender_id TEXT REFERENCES users(id), recipient_id TEXT REFERENCES users(id),
            medicine_key TEXT NOT NULL, medicine TEXT NOT NULL, status TEXT NOT NULL,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL)''',
        '''CREATE TABLE IF NOT EXISTS companion_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT, request_id TEXT REFERENCES companion_requests(id),
            sender_id TEXT REFERENCES users(id), content TEXT NOT NULL, created_at TEXT NOT NULL)''',
        'CREATE INDEX IF NOT EXISTS companion_lookup ON companion_profiles(enabled, medicine_key)',
        'CREATE INDEX IF NOT EXISTS companion_inbox ON companion_requests(recipient_id, status)',
        'CREATE INDEX IF NOT EXISTS companion_outbox ON companion_requests(sender_id, status)',
        'CREATE INDEX IF NOT EXISTS companion_chat ON companion_messages(request_id, id)',
    ]:
        db.execute(sql)


def close_connections(db, user_id, timestamp):
    db.execute("UPDATE companion_requests SET status='closed',updated_at=? WHERE (sender_id=? OR recipient_id=?) AND status IN ('pending','accepted')",
               (timestamp, user_id, user_id))


def reconcile_support(db, user_id, state):
    profile = db.execute('SELECT * FROM companion_profiles WHERE user_id=? AND enabled=1', (user_id,)).fetchone()
    if profile and not any(p['id'] == profile['plan_id'] and p['enabled'] and medicine_key(p['medicine']) == profile['medicine_key'] for p in state['plans']):
        db.execute("UPDATE companion_profiles SET enabled=0,plan_id='',medicine_key='',medicine='' WHERE user_id=?", (user_id,))
        close_connections(db, user_id, state['meta']['updatedAt'])


def clear_support(db, user_id, timestamp):
    db.execute('DELETE FROM medicine_notes WHERE user_id=?', (user_id,))
    db.execute('DELETE FROM companion_profiles WHERE user_id=?', (user_id,))
    close_connections(db, user_id, timestamp)


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class MedicineNote(Input):
    specification: str = Field(default='', max_length=100)
    manufacturer: str = Field(default='', max_length=100)
    introduction: str = Field(default='', max_length=1000)
    precautions: str = Field(default='', max_length=1000)
    storage: str = Field(default='', max_length=500)
    source: str = Field(default='', max_length=200)

    @model_validator(mode='after')
    def require_source(self):
        if any([self.specification, self.manufacturer, self.introduction, self.precautions, self.storage]) and not self.source:
            raise ValueError('补充药品资料时，请填写说明书或包装等实际来源')
        return self


class CompanionProfile(Input):
    enabled: StrictBool
    alias: str = Field(default='', max_length=24)
    about: str = Field(default='', max_length=120)
    planId: str = Field(default='', max_length=64)
    participantConsent: StrictBool = False

    @model_validator(mode='after')
    def require_consent(self):
        if self.enabled and (not self.alias or not self.planId or not self.participantConsent):
            raise ValueError('开启药友功能需要昵称、已启用计划及参与者本人同意')
        return self


class FriendRequest(Input):
    targetId: str = Field(min_length=1, max_length=64)


class FriendDecision(Input):
    action: Literal['accept', 'decline', 'cancel', 'disconnect']


class ChatMessage(Input):
    content: str = Field(min_length=1, max_length=500)


def install_support(app, database, family, current_time):
    def stamp():
        return current_time().isoformat(timespec='microseconds')

    def medicines(db, user_id):
        state = database.load(db, user_id)
        items = []
        for plan in state['plans']:
            row = db.execute('SELECT * FROM medicine_notes WHERE user_id=? AND medicine_key=?', (user_id, medicine_key(plan['medicine']))).fetchone()
            note = {key: row[key] if row else '' for key in MedicineNote.model_fields}
            items.append(dict(note, planId=plan['id'], medicine=plan['medicine'], enabled=plan['enabled'],
                              updatedAt=row['updated_at'] if row else '', provenance='家属录入，未作医疗核验'))
        return {'items': items, 'storageTips': STORAGE_TIPS, 'retrievalTips': RETRIEVAL_TIPS,
                'sources': SOURCES, 'prototypeNotice': PROTOTYPE_NOTICE}

    @app.get('/api/medicines')
    def get_medicines(user_id=Depends(family)):
        with database.transaction() as db:
            return medicines(db, user_id)

    @app.patch('/api/medicines/{plan_id}')
    def save_medicine(plan_id: str, body: MedicineNote, user_id=Depends(family)):
        with database.transaction() as db:
            state = database.load(db, user_id)
            plan = next((p for p in state['plans'] if p['id'] == plan_id), None)
            if not plan:
                raise HTTPException(404, '没有找到当前家庭的这项计划')
            values = body.model_dump()
            db.execute('INSERT OR REPLACE INTO medicine_notes VALUES (?,?,?,?,?,?,?,?,?)',
                       (user_id, medicine_key(plan['medicine']), *values.values(), stamp()))
            return medicines(db, user_id)

    def active(db, user_id):
        row = db.execute('SELECT p.*,u.is_demo FROM companion_profiles p JOIN users u ON u.id=p.user_id WHERE p.user_id=? AND p.enabled=1', (user_id,)).fetchone()
        if not row:
            return None
        plans = database.load(db, user_id)['plans']
        if not any(p['id'] == row['plan_id'] and p['enabled'] and medicine_key(p['medicine']) == row['medicine_key'] for p in plans):
            return None
        return row

    def same_group(db, first, second):
        a, b = active(db, first), active(db, second)
        if not a or not b or a['medicine_key'] != b['medicine_key'] or a['is_demo'] != b['is_demo']:
            raise HTTPException(409, '双方需自愿开启相同药名的交流，且仍保留已启用计划；演示账号与正式账号隔离')
        return a, b

    def companions(db, user_id):
        state = database.load(db, user_id)
        reconcile_support(db, user_id, state)
        row = db.execute('SELECT * FROM companion_profiles WHERE user_id=?', (user_id,)).fetchone()
        profile = {'enabled': bool(row['enabled']) if row else False, 'alias': row['alias'] if row else '',
                   'about': row['about'] if row else '', 'planId': row['plan_id'] if row else '',
                   'consentAt': row['consent_at'] if row else ''}
        result = {'profile': profile, 'eligibleMedicines': [{'planId': p['id'], 'medicine': p['medicine']} for p in state['plans'] if p['enabled']],
                  'candidates': [], 'requests': [], 'connections': []}
        owner = active(db, user_id)
        if not owner:
            return result
        involved = set()
        for req in db.execute("SELECT * FROM companion_requests WHERE (sender_id=? OR recipient_id=?) AND status IN ('pending','accepted') ORDER BY created_at DESC", (user_id, user_id)).fetchall():
            other_id = req['recipient_id'] if req['sender_id'] == user_id else req['sender_id']
            other = active(db, other_id)
            if not other or other['medicine_key'] != owner['medicine_key'] or other['is_demo'] != owner['is_demo']:
                continue
            involved.add(other_id)
            entry = {'id': req['id'], 'alias': other['alias'], 'about': other['about'], 'medicine': req['medicine'],
                     'direction': 'sent' if req['sender_id'] == user_id else 'received', 'status': req['status']}
            result['connections' if req['status'] == 'accepted' else 'requests'].append(entry)
        # Bound scans; no unconsented account details are returned.
        for candidate in db.execute('SELECT p.user_id FROM companion_profiles p JOIN users u ON u.id=p.user_id WHERE p.enabled=1 AND p.medicine_key=? AND u.is_demo=? AND p.user_id<>? ORDER BY p.user_id LIMIT 200', (owner['medicine_key'], owner['is_demo'], user_id)).fetchall():
            other = active(db, candidate['user_id'])
            if other and other['user_id'] not in involved:
                result['candidates'].append({'id': other['user_id'], 'alias': other['alias'], 'about': other['about'], 'medicine': owner['medicine']})
            if len(result['candidates']) >= 40:
                break
        return result

    @app.get('/api/companions')
    def get_companions(user_id=Depends(family)):
        with database.transaction() as db:
            return companions(db, user_id)

    @app.patch('/api/companions/profile')
    def save_companion_profile(body: CompanionProfile, user_id=Depends(family)):
        with database.transaction() as db:
            plan = None
            if body.enabled:
                plan = next((p for p in database.load(db, user_id)['plans'] if p['id'] == body.planId and p['enabled']), None)
                if not plan:
                    raise HTTPException(409, '请先选择当前家庭已启用的用药计划')
            key = medicine_key(plan['medicine']) if plan else ''
            old = db.execute('SELECT * FROM companion_profiles WHERE user_id=?', (user_id,)).fetchone()
            if not body.enabled or (old and old['medicine_key'] != key):
                close_connections(db, user_id, stamp())
            db.execute('INSERT OR REPLACE INTO companion_profiles VALUES (?,?,?,?,?,?,?,?)',
                       (user_id, int(body.enabled), body.alias, body.about, body.planId if plan else '', key,
                        plan['medicine'] if plan else '', stamp() if body.enabled else ''))
            return companions(db, user_id)

    @app.post('/api/companions/requests', status_code=201)
    def send_request(body: FriendRequest, user_id=Depends(family)):
        with database.transaction() as db:
            if body.targetId == user_id:
                raise HTTPException(409, '不能向自己发送邀请')
            owner, _ = same_group(db, user_id, body.targetId)
            existing = db.execute("SELECT id FROM companion_requests WHERE ((sender_id=? AND recipient_id=?) OR (sender_id=? AND recipient_id=?)) AND status IN ('pending','accepted')",
                                  (user_id, body.targetId, body.targetId, user_id)).fetchone()
            if existing:
                raise HTTPException(409, '已有待处理邀请或药友关系')
            recent = db.execute('SELECT COUNT(*) FROM companion_requests WHERE sender_id=? AND created_at>=?',
                                (user_id, (current_time().replace(hour=0, minute=0, second=0, microsecond=0)).isoformat())).fetchone()[0]
            if recent >= 20:
                raise HTTPException(429, '今天的邀请已达 20 次，请稍后再试')
            timestamp = stamp()
            db.execute('INSERT INTO companion_requests VALUES (?,?,?,?,?,?,?,?)',
                       (uuid.uuid4().hex, user_id, body.targetId, owner['medicine_key'], owner['medicine'], 'pending', timestamp, timestamp))
            return companions(db, user_id)

    def owned_request(db, request_id, user_id):
        req = db.execute('SELECT * FROM companion_requests WHERE id=? AND (sender_id=? OR recipient_id=?)', (request_id, user_id, user_id)).fetchone()
        if not req:
            raise HTTPException(404, '邀请或药友关系不存在')
        return req

    @app.patch('/api/companions/requests/{request_id}')
    def decide(request_id: str, body: FriendDecision, user_id=Depends(family)):
        with database.transaction() as db:
            req = owned_request(db, request_id, user_id)
            if body.action in ['accept', 'decline'] and req['recipient_id'] != user_id:
                raise HTTPException(403, '只有收到邀请的一方可以接受或拒绝')
            if body.action == 'cancel' and req['sender_id'] != user_id:
                raise HTTPException(403, '只有发起人可以撤回邀请')
            expected = 'accepted' if body.action == 'disconnect' else 'pending'
            if req['status'] != expected:
                raise HTTPException(409, '状态已变化，请刷新')
            if body.action == 'accept':
                same_group(db, req['sender_id'], req['recipient_id'])
            status = {'accept': 'accepted', 'decline': 'declined', 'cancel': 'cancelled', 'disconnect': 'closed'}[body.action]
            db.execute('UPDATE companion_requests SET status=?,updated_at=? WHERE id=?', (status, stamp(), request_id))
            return companions(db, user_id)

    def chat_request(db, request_id, user_id):
        req = owned_request(db, request_id, user_id)
        if req['status'] != 'accepted':
            raise HTTPException(409, '双方接受邀请后才能交流')
        same_group(db, req['sender_id'], req['recipient_id'])
        return req

    def messages(db, request_id, user_id):
        rows = db.execute('SELECT * FROM companion_messages WHERE request_id=? ORDER BY id DESC LIMIT 100', (request_id,)).fetchall()
        return {'items': [{'id': r['id'], 'mine': r['sender_id'] == user_id, 'content': r['content'], 'createdAt': r['created_at']} for r in reversed(rows)], 'limit': 100}

    @app.get('/api/companions/connections/{request_id}/messages')
    def get_messages(request_id: str, user_id=Depends(family)):
        with database.transaction() as db:
            chat_request(db, request_id, user_id)
            return messages(db, request_id, user_id)

    @app.post('/api/companions/connections/{request_id}/messages', status_code=201)
    def send_message(request_id: str, body: ChatMessage, user_id=Depends(family)):
        with database.transaction() as db:
            chat_request(db, request_id, user_id)
            recent = db.execute('SELECT COUNT(*) FROM companion_messages WHERE sender_id=? AND created_at>=?',
                                (user_id, current_time().replace(minute=0, second=0, microsecond=0).isoformat())).fetchone()[0]
            if recent >= 60:
                raise HTTPException(429, '本小时已发送 60 条消息，请稍后再试')
            db.execute('INSERT INTO companion_messages(request_id,sender_id,content,created_at) VALUES (?,?,?,?)', (request_id, user_id, body.content, stamp()))
            return messages(db, request_id, user_id)
