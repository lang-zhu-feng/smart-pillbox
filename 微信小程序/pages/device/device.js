const store = require('../../utils/store')
Page(store.page({
  data: { device: {}, deviceLabel: '', deviceToken: '', keyStatus: '检查中', baseURL: store.baseURL() },
  applyState(state) {
    this.setData({ device: state.device, deviceLabel: store.deviceLabel(state.device) })
    if (!this._integrationLoaded) this.loadIntegration()
  },
  async loadIntegration() {
    this._integrationLoaded = true
    try {
      const result = await store.request('/api/device/integration')
      this.setData({ keyStatus: result.keyConfigured ? '已生成' : '尚未生成' })
    } catch (_) { this._integrationLoaded = false; this.setData({ keyStatus: '暂无法确认' }) }
  },
  generateKey() { wx.showModal({ title: '生成设备接入密钥', content: '新密钥仅显示一次。更换后旧密钥立即失效，已经接入的硬件需要重新配置。', confirmText: '生成密钥', success: async r => { if (!r.confirm) return; const result = await store.run(this, () => store.request('/api/device/credentials', 'POST'), '新密钥已生成'); if (result) this.setData({ deviceToken: result.deviceToken, keyStatus: '已生成' }) } }) },
  copyBindCommand() {
    if (this.data.deviceToken && this.data.device.code)
      wx.setClipboardData({ data: 'bind ' + this.data.device.code + ' ' + this.data.deviceToken })
  }
}))
