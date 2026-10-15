const store = require('../../utils/store')

Page({
  data: {
    elder: {},
    device: {}
  },

  onShow() {
    const state = store.loadState()
    this.setData({ elder: state.elder, device: state.device })
  },

  goHistory() {
    wx.navigateTo({ url: '/pages/history/history' })
  },

  resetDemo() {
    wx.showModal({
      title: '重置演示数据',
      content: '所有模拟操作会恢复到初始状态，不会影响任何真实数据。',
      confirmText: '确认重置',
      success: (result) => {
        if (result.confirm) {
          store.resetState()
          wx.showToast({ title: '已恢复初始状态', icon: 'success' })
          const state = store.loadState()
          this.setData({ elder: state.elder, device: state.device })
        }
      }
    })
  }
})
