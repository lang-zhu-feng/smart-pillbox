const store = require('../../utils/store')

Page({
  data: {
    plans: []
  },

  onShow() {
    this.refresh()
  },

  refresh() {
    this.setData({ plans: store.loadState().plans })
  },

  togglePlan(event) {
    const id = event.currentTarget.dataset.id
    const state = store.togglePlan(id)
    const plan = state.plans.find((item) => item.id === id)
    wx.showToast({
      title: plan.enabled ? '计划已启用' : '计划已暂停',
      icon: 'none'
    })
    this.refresh()
  },

  addPlan() {
    wx.showModal({
      title: '新增演示计划',
      content: '将新增“维生素D滴剂，每周日 09:00”作为原型演示数据。',
      confirmText: '确认新增',
      success: (result) => {
        if (result.confirm) {
          store.addDemoPlan()
          wx.showToast({ title: '计划已新增', icon: 'success' })
          this.refresh()
        }
      }
    })
  }
})
