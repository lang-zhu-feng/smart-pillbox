const store = require('../../utils/store')
Page(store.page({
  data: { elder: {}, familyName: '', todayLabel: '', deviceLabel: '尚未接入硬件', connectionError: '' },
  applyState(state) {
    const date = new Date()
    this.setData({ elder: state.elder, familyName: state.meta.familyName, todayLabel: `${date.getMonth() + 1}月${date.getDate()}日 · ${store.days[store.mondayIndex(date)]}`, deviceLabel: store.deviceLabel(state.device) })
  },
  goPillbox() { wx.switchTab({ url: '/pages/pillbox/pillbox' }) },
  goProfile() { wx.switchTab({ url: '/pages/profile/profile' }) }
}))
