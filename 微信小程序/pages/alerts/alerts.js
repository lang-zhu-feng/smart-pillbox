const store = require('../../utils/store')
Page(store.page({
  data: { alerts: [], unreadCount: 0 },
  applyState(state) { this._state = state; this.setData({ alerts: state.alerts.map(a => ({ ...a, levelLabel: store.sourceLabel(a.source) })), unreadCount: state.alerts.filter(a => !a.read).length }) },
  async openAlert(event) {
    const alert = this.data.alerts.find(a => a.id === event.currentTarget.dataset.id)
    if (!alert) return
    await store.run(this, () => store.request('/api/alerts/' + alert.id + '/read', 'POST'), '')
    wx.showModal({ title: alert.title, content: alert.detail + '\n\n请先联系家人确认实际情况。', showCancel: false })
  },
  markAllRead() { store.run(this, () => store.request('/api/alerts/read-all', 'POST'), '已全部标记为已读') },
  simulateAlert() {
    const task = this._state && this._state.tasks.find(t => !['NO_MEDICATION', 'COMPLETED'].includes(t.status))
    if (!task) { store.error('请先新增或启用计划'); return }
    store.run(this, () => store.request('/api/demo/tasks/' + task.id + '/overdue', 'POST'), '已生成应用内提醒')
  }
}))
