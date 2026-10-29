const store = require('../../utils/store')
Page(store.page({
  data: { plans: [], formOpen: false, slots: ['早餐后', '午餐后', '晚餐后'], slotIndex: 0, time: '08:00', days: store.days.map((name, i) => ({ name, value: String(i) })) },
  applyState(state) { this.setData({ plans: state.plans.map(p => ({ ...p, schedule: p.days.map(i => store.days[i]).join('、') })) }) },
  togglePlan(event) { store.run(this, () => store.request('/api/plans/' + event.currentTarget.dataset.id, 'PATCH', { enabled: event.detail.value }), '计划已更新') },
  addPlan() { this.setData({ formOpen: !this.data.formOpen }) },
  changeSlot(event) { const i = Number(event.detail.value); this.setData({ slotIndex: i, time: store.slots[i].time }) },
  changeTime(event) { this.setData({ time: event.detail.value }) },
  async savePlan(event) {
    const form = event.detail.value
    if (!form.medicine.trim() || !form.dosage.trim() || !form.days.length) { store.error('请填写药品、剂量并至少选择一天'); return }
    const result = await store.run(this, () => store.request('/api/plans', 'POST', { medicine: form.medicine.trim(), dosage: form.dosage.trim(), note: form.note.trim(), days: form.days.map(Number), slotKey: store.slots[this.data.slotIndex].key, time: this.data.time }), '计划已保存')
    if (result) this.setData({ formOpen: false })
  }
}))
