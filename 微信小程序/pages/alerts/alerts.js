const store = require('../../utils/store')
const wechatNotifications = require('../../utils/wechat-notifications')
Page(store.page({
  data: {
    alerts: [], unreadCount: 0, todayEarly: null, canConfirm: false,
    wechatBusy: false, wechatError: '',
    wechat: { available: false, configured: false, authorizedCredits: 0, templateId: '', unavailableReason: '正在检查微信提醒设置', lastDeliveryMessage: '' }
  },
  applyState(state) {
    this._state = state
    const todayEarly = state.tasks.find(t => t.slotKey === 'morning' && t.date === state.meta.updatedAt.slice(0, 10)) || null
    this.setData({ alerts: state.alerts.map(a => ({ ...a, levelLabel: store.sourceLabel(a.source) })), unreadCount: state.alerts.filter(a => !a.read).length,
      todayEarly, canConfirm: !!todayEarly && ['REMINDING', 'OVERDUE'].includes(todayEarly.status) })
    this.refreshWechatStatus()
  },
  async refreshWechatStatus() {
    if (this._wechatLoading || this.data.wechatBusy) return
    this._wechatLoading = true
    const requestId = this._wechatRequestId = (this._wechatRequestId || 0) + 1
    try {
      const status = await wechatNotifications.getStatus()
      if (requestId === this._wechatRequestId) this.setData({ wechat: status, wechatError: '' })
    } catch (error) {
      if (requestId === this._wechatRequestId) this.setData({ wechatError: error.message || '微信提醒设置暂时无法读取，请稍后重试' })
    } finally {
      this._wechatLoading = false
    }
  },
  enableWechatNotifications() {
    if (this.data.wechatBusy || !this.data.wechat.available) return
    this._wechatRequestId = (this._wechatRequestId || 0) + 1
    this.setData({ wechatBusy: true, wechatError: '' })
    // 这里不能先等待网络请求，否则可能失去微信要求的用户点击上下文。
    wechatNotifications.authorize(this.data.wechat.templateId).then(status => {
      this.setData({ wechat: status })
      wx.showToast({ title: '本次微信提醒授权已记录', icon: 'none' })
    }).catch(error => {
      this.setData({ wechatError: error.message || '微信提醒尚未开启，请稍后重试' })
    }).finally(() => {
      this.setData({ wechatBusy: false })
    })
  },
  async openAlert(event) {
    const alert = this.data.alerts.find(a => a.id === event.currentTarget.dataset.id)
    if (!alert) return
    await store.run(this, () => store.request('/api/alerts/' + alert.id + '/read', 'POST'), '')
    wx.showModal({ title: alert.title, content: alert.detail + '\n\n请先联系家人确认实际情况。如需停止本次药盒响铃，请使用下方“家属确认”按钮。', showCancel: false })
  },
  confirmTask() {
    const task = this.data.todayEarly
    if (!this.data.canConfirm || !task) return
    wx.showModal({ title: '停止本次药盒提醒', content: '请先联系家人核实。确认后药盒联网读取新状态会停止本次响铃，尚未发出的超时通知会取消；已发出的不能撤回。确认不代表已经服药。', confirmText: '确认停止', success: result => {
      if (result.confirm) store.run(this, () => store.request('/api/tasks/' + task.id + '/confirm', 'POST'), '本次提醒已确认')
    } })
  },
  markAllRead() { store.run(this, () => store.request('/api/alerts/read-all', 'POST'), '已全部标记为已读') },
  simulateAlert() {
    const task = this._state && this._state.tasks.find(t => !['NO_MEDICATION', 'COMPLETED', 'CONFIRMED'].includes(t.status))
    if (!task) { store.error('请先新增或启用计划'); return }
    store.run(this, () => store.request('/api/demo/tasks/' + task.id + '/overdue', 'POST'), '已生成应用内提醒')
  }
}))
