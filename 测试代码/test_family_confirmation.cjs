const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')

const calls = []
let definition
const task = {
  id: '1-morning', date: '2026-11-10', dayIndex: 1, slotKey: 'morning',
  status: 'REMINDING', reminderCount: 2, medicines: ['测试药']
}
const state = {
  tasks: [task], meta: { updatedAt: '2026-11-10T08:15:00+08:00' },
  device: { hasConnected: false }
}
const store = {
  days: ['周一', '周二', '周三', '周四', '周五', '周六', '周日'],
  slots: [{ key: 'morning', time: '08:00' }, { key: 'noon', time: '12:00' }, { key: 'evening', time: '19:00' }],
  statusMeta: { REMINDING: { label: '提醒中', className: 'status-reminding' }, CONFIRMED: { label: '家属已确认', className: 'status-confirmed' } },
  mondayIndex: () => 1, deviceLabel: () => '尚未接入硬件', page: value => value,
  request: async (url, method) => {
    calls.push({ url, method })
    return { ...state, tasks: [{ ...task, status: 'CONFIRMED' }] }
  },
  run: async (owner, operation) => { const result = await operation(); owner.applyState(result); return result }
}
const wx = { showModal: options => options.success({ confirm: true }), navigateTo: () => {} }
const filename = path.join(__dirname, '..', '微信小程序', 'pages', 'pillbox', 'pillbox.js')
vm.runInNewContext(fs.readFileSync(filename, 'utf8'), { require: () => store, Page: value => { definition = value }, wx })
const page = { ...definition, data: JSON.parse(JSON.stringify(definition.data)), setData(values) { Object.assign(this.data, values) } }

async function main() {
  page.applyState(state)
  assert.equal(page.data.canConfirm, true)
  page.confirmTask()
  await new Promise(resolve => setImmediate(resolve))
  assert.equal(calls.length, 1)
  assert.equal(calls[0].url, '/api/tasks/1-morning/confirm')
  assert.equal(calls[0].method, 'POST')
  assert.equal(page.data.todayEarly.status, 'CONFIRMED')
  assert.equal(page.data.canConfirm, false)
  page.confirmTask()
  assert.equal(calls.length, 1)
  console.log('PASS: caregiver confirms once and native page stops offering confirmation')
}
main().catch(error => { console.error(error); process.exitCode = 1 })
