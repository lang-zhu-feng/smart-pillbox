const store = require('../../utils/store')
Page(store.page({
  data: { plans: [], formOpen: false, editingId: '', formValues: { medicine: '', dosage: '', note: '' }, slots: ['早餐后', '午餐后', '晚餐后'], slotIndex: 0, time: '08:00', days: store.days.map((name, i) => ({ name, value: String(i), checked: true })) },
  applyState(state) { this.setData({ plans: state.plans.map(p => ({ ...p, schedule: p.days.map(i => store.days[i]).join('、') })) }) },
  togglePlan(event) { store.run(this, () => store.request('/api/plans/' + event.currentTarget.dataset.id, 'PATCH', { enabled: event.detail.value }), '计划已更新') },
  addPlan() {
    if (this.data.formOpen && !this.data.editingId) { this.setData({ formOpen: false }); return }
    this.setData({ formOpen: true, editingId: '', formValues: { medicine: '', dosage: '', note: '' }, slotIndex: 0, time: store.slots[0].time, days: store.days.map((name, i) => ({ name, value: String(i), checked: true })) })
  },
  editPlan(event) {
    const plan = this.data.plans.find(p => p.id === event.currentTarget.dataset.id)
    if (!plan) return
    this.setData({ formOpen: true, editingId: plan.id, formValues: { medicine: plan.medicine, dosage: plan.dosage, note: plan.note || '' }, slotIndex: store.slots.findIndex(s => s.key === plan.slotKey), time: plan.time, days: store.days.map((name, i) => ({ name, value: String(i), checked: plan.days.includes(i) })) })
  },
  async deletePlan(event) {
    const id = event.currentTarget.dataset.id
    const plan = this.data.plans.find(p => p.id === id)
    if (!plan) return
    const choice = await new Promise(resolve => wx.showModal({
      title: '删除服药计划',
      content: '确定删除“' + plan.medicine + '”吗？删除后药盒联网更新计划，将停止这项计划的后续提醒；已产生的历史记录会保留。',
      confirmText: '删除', confirmColor: '#B65D56',
      success: resolve, fail: () => resolve({ confirm: false })
    }))
    if (!choice.confirm) return
    const result = await store.run(this, () => store.request('/api/plans/' + encodeURIComponent(id), 'DELETE'), '计划已删除')
    if (result && this.data.editingId === id) this.closeForm()
  },
  closeForm() { this.setData({ formOpen: false, editingId: '' }) },
  goMedicines() { wx.navigateTo({ url: '/pages/medicines/medicines' }) },
  changeSlot(event) { const i = Number(event.detail.value); this.setData({ slotIndex: i, time: store.slots[i].time }) },
  changeTime(event) { this.setData({ time: event.detail.value }) },
  async savePlan(event) {
    const form = event.detail.value
    if (!form.medicine.trim() || !form.dosage.trim() || !form.days.length) { store.error('请填写药品、剂量并至少选择一天'); return }
    const payload = { medicine: form.medicine.trim(), dosage: form.dosage.trim(), note: form.note.trim(), days: form.days.map(Number), slotKey: store.slots[this.data.slotIndex].key, time: this.data.time }
    const id = this.data.editingId
    const result = await store.run(this, () => store.request(id ? '/api/plans/' + id : '/api/plans', id ? 'PUT' : 'POST', payload), '计划已保存')
    if (result) this.closeForm()
  }
}))
