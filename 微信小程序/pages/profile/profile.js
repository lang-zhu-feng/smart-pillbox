const store = require('../../utils/store')
Page(store.page({
  data: { elder: {}, device: {}, deviceLabel: '', editOpen: false },
  applyState(state) { this._state = state; this.setData({ elder: state.elder, device: state.device, deviceLabel: store.deviceLabel(state.device), isDemo: state.meta.isDemo }) },
  goHistory() { wx.navigateTo({ url: '/pages/history/history' }) },
  goDevice() { wx.navigateTo({ url: '/pages/device/device' }) },
  editProfile() { this.setData({ editOpen: !this.data.editOpen }) },
  async saveProfile(event) {
    const body = { ...event.detail.value, age: Number(event.detail.value.age), conditions: this._state.elder.conditions }
    if (!body.name.trim() || !body.relation.trim() || !body.homeTitle.trim()) { store.error('称呼、关系和家的名字不能为空'); return }
    const result = await store.run(this, () => store.request('/api/profile', 'PATCH', body), '家庭档案已保存')
    if (result) this.setData({ editOpen: false })
  },
  resetDemo() { wx.showModal({ title: '重置演示数据', content: '将恢复当前家庭的档案、计划与模拟记录。有真实设备事件时，后端会保护数据并拒绝重置。', confirmText: '确认重置', success: r => { if (r.confirm) store.run(this, () => store.request('/api/demo/reset', 'POST'), '已恢复初始状态') } }) },
  async logout() { await store.run(this, async () => { await store.request('/api/auth/logout', 'POST'); store.clearToken(); store.requireLogin() }, '') }
}))
