const store = require('../../utils/store')
Page(store.page({
  data: { device: {}, deviceLabel: '', deviceToken: '', baseURL: store.baseURL() },
  applyState(state) { this.setData({ device: state.device, deviceLabel: store.deviceLabel(state.device) }) },
  generateKey() { wx.showModal({ title: '生成设备接入密钥', content: '新密钥仅显示一次。更换后旧密钥立即失效，已经接入的硬件需要重新配置。', confirmText: '生成密钥', success: async r => { if (!r.confirm) return; const result = await store.run(this, () => store.request('/api/device/credentials', 'POST'), '新密钥已生成'); if (result) this.setData({ deviceToken: result.deviceToken }) } }) },
  copyKey() { if (this.data.deviceToken) wx.setClipboardData({ data: this.data.deviceToken }) }
}))
