const store = require('../../utils/store')
Page(store.page({
  data: { elder: {}, device: {}, deviceLabel: '', editOpen: false },
  applyState(state) { this._state = state; this.setData({ elder: state.elder, device: state.device, deviceLabel: store.deviceLabel(state.device), isDemo: state.meta.isDemo }) },
  goHistory() { wx.navigateTo({ url: '/pages/history/history' }) },
  goDevice() { wx.navigateTo({ url: '/pages/device/device' }) },
  goMedicines() { wx.navigateTo({ url: '/pages/medicines/medicines' }) },
  goCompanions() { wx.navigateTo({ url: '/pages/companions/companions' }) },
  editProfile() { this.setData({ editOpen: !this.data.editOpen }) },
  async saveProfile(event) {
    const body = { ...event.detail.value, age: Number(event.detail.value.age), conditions: this._state.elder.conditions }
    if (!body.name.trim() || !body.relation.trim() || !body.homeTitle.trim()) { store.error('称呼、关系和家的名字不能为空'); return }
    const result = await store.run(this, () => store.request('/api/profile', 'PATCH', body), '家庭档案已保存')
    if (result) this.setData({ editOpen: false })
  },
  resetDemo() { wx.showModal({ title: '重置今天的演示记录', content: '仅清除今天的提醒和开盒测试记录；账号、计划和设备绑定保留。已发出的微信消息不能撤回。若旧计划时间已过，请改设未来时间再演示。', confirmText: '确认重置', success: r => { if (r.confirm) store.run(this, () => store.request('/api/demo/reset-today', 'POST'), '今天的演示记录已重置') } }) },
  async logout() { await store.run(this, async () => { await store.request('/api/auth/logout', 'POST'); store.clearToken(); store.requireLogin() }, '') }
}))
