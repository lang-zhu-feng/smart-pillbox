const store = require('../../utils/store')

Page({
  data: {
    elder: {},
    device: {},
    todayLabel: '',
    todayTasks: [],
    completionText: '0/0',
    completionRate: 0,
    unreadCount: 0,
    latestAlert: null
  },

  onShow() {
    this.refresh()
  },

  refresh() {
    const state = store.loadState()
    const todayIndex = store.mondayIndex(new Date())
    const todayTasks = state.tasks
      .filter((task) => task.dayIndex === todayIndex)
      .map((task) => this.decorateTask(task))
    const activeTasks = todayTasks.filter((task) => task.status !== 'NO_MEDICATION')
    const completed = activeTasks.filter((task) => task.status === 'COMPLETED').length
    const unreadAlerts = state.alerts.filter((alert) => !alert.read)

    this.setData({
      elder: {
        ...state.elder,
        conditionText: state.elder.conditions.join(' · ')
      },
      device: state.device,
      todayLabel: store.days[todayIndex],
      todayTasks,
      completionText: `${completed}/${activeTasks.length}`,
      completionRate: activeTasks.length ? Math.round(completed / activeTasks.length * 100) : 100,
      unreadCount: unreadAlerts.length,
      latestAlert: unreadAlerts[0] || state.alerts[0] || null
    })
  },

  decorateTask(task) {
    const meta = store.statusMeta[task.status]
    return {
      ...task,
      statusLabel: meta.label,
      statusClass: meta.className,
      medicineText: task.medicines.length ? task.medicines.join(' · ') : '本时段无需服药'
      ,
      startTime: task.time.substring(0, 5)
    }
  },

  goPillbox() {
    wx.switchTab({ url: '/pages/pillbox/pillbox' })
  },

  goPlans() {
    wx.switchTab({ url: '/pages/plans/plans' })
  },

  goAlerts() {
    wx.switchTab({ url: '/pages/alerts/alerts' })
  },

  goHistory() {
    wx.navigateTo({ url: '/pages/history/history' })
  },

  simulateOpen() {
    const task = this.data.todayTasks.find((item) => item.status === 'REMINDING' || item.status === 'PENDING' || item.status === 'OVERDUE')
    if (!task) {
      wx.showToast({ title: '今日任务已完成', icon: 'success' })
      return
    }
    store.completeTask(task.id)
    wx.showToast({ title: '已记录开盒事件', icon: 'success' })
    this.refresh()
  }
})
