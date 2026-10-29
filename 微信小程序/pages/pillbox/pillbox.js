const store = require('../../utils/store')
Page(store.page({
  data: { days: store.days, rows: [], device: {}, deviceLabel: '', todayIndex: 0 },
  applyState(state) {
    this._state = state
    const todayIndex = store.mondayIndex(new Date())
    const rows = store.slots.map(slot => ({ ...slot, startTime: slot.time, cells: state.tasks.filter(t => t.slotKey === slot.key).map(t => ({ ...t, statusClass: store.statusMeta[t.status].className, shortLabel: store.statusMeta[t.status].label, isToday: t.dayIndex === todayIndex })) }))
    this.setData({ rows, todayIndex, device: state.device, deviceLabel: store.deviceLabel(state.device) })
  },
  goDevice() { wx.navigateTo({ url: '/pages/device/device' }) },
  openTask(event) {
    const task = this._state.tasks.find(t => t.id === event.currentTarget.dataset.id)
    if (!task) return
    const can = !['NO_MEDICATION', 'COMPLETED'].includes(task.status)
    wx.showModal({ title: `${task.day} · ${task.slotFullName}`, content: `${task.date} ${task.time}\n${task.medicines.join('\n') || '该药格没有计划'}\n${store.statusMeta[task.status].label}${task.source ? ' · ' + store.sourceLabel(task.source) : ''}\n提醒 ${task.reminderCount}/3 次\n\n模拟操作不会让设备显示在线。`, showCancel: can, confirmText: can ? '模拟开盒' : '知道了', success: result => { if (can && result.confirm) store.run(this, () => store.request('/api/demo/tasks/' + task.id + '/open', 'POST'), '已记录模拟开盒') } })
  },
  simulateOverdue() {
    const task = this._state && this._state.tasks.find(t => !['NO_MEDICATION', 'COMPLETED'].includes(t.status))
    if (!task) { store.error('请先新增或启用用药计划'); return }
    store.run(this, () => store.request('/api/demo/tasks/' + task.id + '/overdue', 'POST'), '已生成应用内提醒')
  }
}))
