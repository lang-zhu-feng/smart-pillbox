const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')

const calls = []
let confirmDelete = false
const slots = [
  { key: 'morning', time: '08:00' },
  { key: 'noon', time: '12:00' },
  { key: 'evening', time: '19:00' }
]
const store = {
  days: ['周一', '周二', '周三', '周四', '周五', '周六', '周日'], slots,
  page: definition => definition,
  request: async (url, method, body) => { calls.push({ url, method, body }); return { tasks: [], plans: [] } },
  run: async (_page, operation) => operation(),
  error: message => { throw new Error(message) }
}
let definition
const filename = path.join(__dirname, '..', '微信小程序', 'pages', 'plans', 'plans.js')
vm.runInNewContext(fs.readFileSync(filename, 'utf8'), {
  require: () => store,
  Page: value => { definition = value },
  wx: { navigateTo: () => {}, showModal: options => options.success({ confirm: confirmDelete }) }
})
const page = {
  ...definition,
  data: JSON.parse(JSON.stringify(definition.data)),
  setData(values) { Object.assign(this.data, values) }
}
page.applyState({ plans: [{
  id: 'plan-1', medicine: '测试药', dosage: '1片', note: '饭后',
  slotKey: 'morning', time: '08:00', days: [0, 2], enabled: true
}] })
page.editPlan({ currentTarget: { dataset: { id: 'plan-1' } } })
assert.equal(page.data.editingId, 'plan-1')
assert.equal(page.data.formValues.medicine, '测试药')
assert.deepEqual(Array.from(page.data.days.filter(day => day.checked).map(day => Number(day.value))), [0, 2])
page.changeTime({ detail: { value: '08:20' } })
async function main() {
  await page.savePlan({ detail: { value: { medicine: '测试药', dosage: '1片', note: '饭后', days: ['0', '2'] } } })
    assert.equal(calls[0].url, '/api/plans/plan-1')
    assert.equal(calls[0].method, 'PUT')
    assert.equal(calls[0].body.time, '08:20')
    assert.deepEqual(Array.from(calls[0].body.days), [0, 2])
    assert.equal(page.data.formOpen, false)
  await page.deletePlan({ currentTarget: { dataset: { id: 'plan-1' } } })
  assert.equal(calls.length, 1, 'cancelling deletion must not call the backend')
  confirmDelete = true
  await page.deletePlan({ currentTarget: { dataset: { id: 'plan-1' } } })
  assert.equal(calls[1].url, '/api/plans/plan-1')
  assert.equal(calls[1].method, 'DELETE')
  console.log('PASS: plan editing, deletion confirmation and DELETE request')
}
main().catch(error => { console.error(error); process.exitCode = 1 })
