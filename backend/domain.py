"""Family state, weekly tasks, and an explicit separation of demo and hardware."""
from datetime import datetime, timedelta, timezone
import copy
import uuid

TZ = timezone(timedelta(hours=8))
DAYS = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
SLOTS = [
    {'key': 'morning', 'name': '早', 'fullName': '早餐后', 'time': '08:00'},
    {'key': 'noon', 'name': '中', 'fullName': '午餐后', 'time': '12:00'},
    {'key': 'evening', 'name': '晚', 'fullName': '晚餐后', 'time': '19:00'},
]

def now_local():
    return datetime.now(TZ)

def seed_state(name, demo=False):
    plans = []
    if demo:
        for index, slot in enumerate(SLOTS):
            plans.append({'id': 'sample-' + slot['key'], 'medicine': '示例药品 ' + chr(65 + index),
                          'dosage': '按医嘱', 'slotKey': slot['key'], 'time': slot['time'],
                          'days': list(range(7)) if index != 1 else [0, 2, 4],
                          'enabled': True, 'note': '仅供演示，不是用药建议'})
    state = {
        'elder': {'name': '李爸爸' if demo else '家人', 'age': 72 if demo else 0,
                  'relation': '父亲' if demo else '家人', 'address': '温暖的小家' if demo else '',
                  'conditions': [], 'emergencyContact': '', 'homeTitle': '爸爸的家' if demo else '家人的家'},
        'device': {'name': '家里的安心药盒', 'code': 'MG-' + uuid.uuid4().hex[:8].upper(),
                   'online': False, 'hasConnected': False, 'lastSeen': '尚未接入',
                   'lastHardwareSeen': None, 'battery': None},
        'plans': plans, 'tasks': [], 'alerts': [], 'history': [],
        'meta': {'isDemo': demo, 'familyName': name, 'weekStart': '', 'updatedAt': '', 'timezone': 'Asia/Shanghai'}
    }
    rebuild_tasks(state, now_local())
    return state

def rebuild_tasks(state, now):
    monday = now.date() - timedelta(days=now.weekday())
    week = monday.isoformat()
    previous = {t['id']: t for t in state.get('tasks', [])} if state['meta'].get('weekStart') == week else {}
    tasks = []
    for slot in SLOTS:
        for day_index, day in enumerate(DAYS):
            task_id = f"{day_index}-{slot['key']}"
            plans = [p for p in state['plans'] if p['enabled'] and p['slotKey'] == slot['key'] and day_index in p['days']]
            date = monday + timedelta(days=day_index)
            start_time = min((p['time'] for p in plans), default=slot['time'])
            start = datetime.fromisoformat(date.isoformat() + 'T' + start_time).replace(tzinfo=TZ)
            end = start + timedelta(minutes=30)
            old = previous.get(task_id, {})
            task = {'id': task_id, 'date': date.isoformat(), 'dayIndex': day_index, 'day': day,
                    'slotKey': slot['key'], 'slotName': slot['name'], 'slotFullName': slot['fullName'],
                    'time': start.strftime('%H:%M') + '-' + end.strftime('%H:%M'),
                    'startAt': start.isoformat(), 'endAt': end.isoformat(),
                    'medicines': [p['medicine'] + ' · ' + p['dosage'] for p in plans],
                    'status': 'PENDING' if plans else 'NO_MEDICATION', 'completedAt': '', 'reminderCount': 0}
            if plans and old.get('status') == 'COMPLETED':
                for key in ['status', 'completedAt', 'source', 'eventId']:
                    if key in old:
                        task[key] = old[key]
            elif plans and old.get('demoOverride'):
                task.update(status=old['status'], demoOverride=True)
            tasks.append(task)
    state['tasks'] = tasks
    state['meta']['weekStart'] = week

def tick(state, now):
    if state['meta'].get('weekStart') != (now.date() - timedelta(days=now.weekday())).isoformat():
        rebuild_tasks(state, now)
    device = state['device']
    last = device.get('lastHardwareSeen')
    device['online'] = bool(last and 0 <= (now - datetime.fromisoformat(last)).total_seconds() <= 90)
    device['lastSeen'] = last[11:19] if last else '尚未接入'
    for task in state['tasks']:
        if task['status'] in ['NO_MEDICATION', 'COMPLETED'] or task.get('demoOverride'):
            continue
        start, end = datetime.fromisoformat(task['startAt']), datetime.fromisoformat(task['endAt'])
        if now < start:
            task['status'], task['reminderCount'] = 'PENDING', 0
        elif now <= end:
            task['status'], task['reminderCount'] = 'REMINDING', min(3, int((now - start).total_seconds() // 600) + 1)
        else:
            task['status'] = 'OVERDUE'
            if task['date'] == now.date().isoformat() and now >= end + timedelta(minutes=15):
                add_alert(state, task, now, 'rule')
    state['meta']['updatedAt'] = now.isoformat(timespec='seconds')

def add_alert(state, task, now, source):
    key = task['date'] + ':' + task['id']
    if any(a.get('taskKey') == key for a in state['alerts']):
        return
    state['alerts'].insert(0, {'id': uuid.uuid4().hex, 'level': 'high', 'title': task['day'] + task['slotFullName'] + '需要留意',
        'detail': '暂未收到这个药格的开盒记录，可以联系家人确认一下。',
        'time': now.strftime('%m-%d %H:%M'), 'read': False, 'taskId': task['id'], 'taskKey': key, 'source': source})
    state['history'].insert(0, {'id': uuid.uuid4().hex, 'date': task['date'], 'slot': task['slotFullName'],
        'medicine': '、'.join(task['medicines']), 'result': 'OVERDUE', 'event': '超时未开盒 · ' + now.strftime('%H:%M:%S'),
        'source': source, 'deviceCode': state['device']['code'], 'eventId': 'overdue-' + key, 'taskId': task['id']})
    state['history'] = state['history'][:1000]

def complete(state, task, now, source, event_id):
    if task['status'] == 'NO_MEDICATION':
        raise ValueError('这个药格没有用药计划，请先设置计划')
    if task['status'] == 'COMPLETED' and source == 'demo':
        return
    task.update(status='COMPLETED', completedAt=now.strftime('%H:%M'), source=source, eventId=event_id)
    task.pop('demoOverride', None)
    for alert in state['alerts']:
        if alert.get('taskKey') == task['date'] + ':' + task['id']:
            alert['read'] = True
    state['history'].insert(0, {'id': uuid.uuid4().hex, 'date': task['date'], 'slot': task['slotFullName'],
        'medicine': '、'.join(task['medicines']), 'result': 'COMPLETED',
        'event': ('模拟开盒' if source == 'demo' else '设备开盒') + ' · ' + now.strftime('%H:%M:%S'),
        'source': source, 'deviceCode': state['device']['code'], 'eventId': event_id, 'taskId': task['id']})
    state['history'] = state['history'][:1000]

def public_state(state, now):
    tick(state, now)
    return copy.deepcopy(state)
