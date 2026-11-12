const store = require('../../utils/store')
Page(store.page({
  data: { days: store.days, rows: [], device: {}, deviceLabel: '', todayIndex: 0, todayEarly: null, canConfirm: false, showConfirmCard: false },
  applyState(state) {
    this._state = state
    const todayIndex = store.mondayIndex(new Date())
    const rows = store.slots.map(slot => ({ ...slot, startTime: slot.time, cells: state.tasks.filter(t => t.slotKey === slot.key).map(t => ({ ...t, statusClass: store.statusMeta[t.status].className, shortLabel: store.statusMeta[t.status].label, isToday: t.dayIndex === todayIndex })) }))
    const todayEarly = state.tasks.find(t => t.slotKey === 'morning' && t.date === state.meta.updatedAt.slice(0, 10)) || null
    this.setData({ rows, todayIndex, device: state.device, deviceLabel: store.deviceLabel(state.device),
      todayEarly, canConfirm: !!todayEarly && ['REMINDING', 'OVERDUE'].includes(todayEarly.status),
      showConfirmCard: !!todayEarly && ['REMINDING', 'OVERDUE', 'CONFIRMED'].includes(todayEarly.status) })
  },
  goDevice() { wx.navigateTo({ url: '/pages/device/device' }) },
  openTask(event) {
    const task = this._state.tasks.find(t => t.id === event.currentTarget.dataset.id)
    if (!task) return
    const can = !['NO_MEDICATION', 'COMPLETED', 'CONFIRMED'].includes(task.status)
    wx.showModal({ title: `${task.day} · ${task.slotFullName}`, content: `${task.date} ${task.time}\n${task.medicines.join('\n') || '该药格没有计划'}\n${store.statusMeta[task.status].label}${task.source ? ' · ' + store.sourceLabel(task.source) : ''}\n提醒 ${task.reminderCount}/5 次\n\n模拟操作不会产生真实硬件接入记录。`, showCancel: can, confirmText: can ? '模拟开盒' : '知道了', success: result => { if (can && result.confirm) store.run(this, () => store.request('/api/demo/tasks/' + task.id + '/open', 'POST'), '已记录模拟开盒') } })
  },
  confirmTask() {
    const task = this.data.todayEarly
    if (!this.data.canConfirm || !task) return
    wx.showModal({ title: '停止本次药盒提醒', content: '确认后，药盒联网读取新状态会停止本次响铃，并取消尚未发出的本次超时通知；已经发出的通知无法撤回。这不代表已经开盒或服药。', confirmText: '确认停止', success: result => {
      if (result.confirm) store.run(this, () => store.request('/api/tasks/' + task.id + '/confirm', 'POST'), '本次提醒已确认')
    } })
  },
  simulateOverdue() {
    const task = this._state && this._state.tasks.find(t => !['NO_MEDICATION', 'COMPLETED', 'CONFIRMED'].includes(t.status))
    if (!task) { store.error('请先新增或启用用药计划'); return }
    store.run(this, () => store.request('/api/demo/tasks/' + task.id + '/overdue', 'POST'), '已生成应用内提醒')
  }
}))
