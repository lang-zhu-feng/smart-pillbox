const store = require('../../utils/store')

Page({
  data: {
    alerts: [],
    unreadCount: 0
  },

  onShow() {
    this.refresh()
  },

  refresh() {
    const alerts = store.loadState().alerts.map((alert) => ({
      ...alert,
      levelLabel: alert.level === 'high' ? '需关注' : '设备消息'
    }))
    this.setData({
      alerts,
      unreadCount: alerts.filter((alert) => !alert.read).length
    })
  },

  openAlert(event) {
    const id = event.currentTarget.dataset.id
    const alert = this.data.alerts.find((item) => item.id === id)
    if (!alert) return
    store.markAlertRead(id)
    wx.showModal({
      title: alert.title,
      content: `${alert.detail}\n\n提示：请先通过电话或其他方式联系老人确认实际情况。`,
      showCancel: false,
      confirmText: '我知道了'
    })
    this.refresh()
  },

  markAllRead() {
    store.markAllAlertsRead()
    wx.showToast({ title: '已全部标记为已读', icon: 'none' })
    this.refresh()
  },

  simulateAlert() {
    const state = store.loadState()
    const candidate = state.tasks.find((task) => task.status === 'REMINDING' || task.status === 'PENDING')
    store.simulateOverdue(candidate ? candidate.id : '')
    wx.showToast({ title: '异常提醒已生成', icon: 'none' })
    this.refresh()
  }
})
