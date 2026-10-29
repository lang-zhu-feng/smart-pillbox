const store = require('../../utils/store')
Page({
  data: { register: false, busy: false, error: '', remaining: 3, countdown: 0, baseURL: store.baseURL(), settingsOpen: false, realDevice: false, connectionStatus: '', connectionError: '', diagnosticReason: '', diagnosticBusy: false },
  onLoad() { this._lockUntil = 0; this.setData({ baseURL: store.baseURL(), realDevice: store.isRealDevice() }) },
  onUnload() { clearInterval(this._timer) },
  switchMode() { this.setData({ register: !this.data.register, error: '' }) },
  settings() { this.setData({ settingsOpen: !this.data.settingsOpen }) },
  saveServer(event) { try { store.setBaseURL(event.detail.value.baseURL); this.setData({ baseURL: store.baseURL(), error: '', connectionStatus: '', connectionError: '', diagnosticReason: '' }); this.checkConnection() } catch (e) { this.setData({ error: e.message }); store.error(e) } },
  async checkConnection() {
    if (this.data.diagnosticBusy || this.data.busy) return
    this.setData({ diagnosticBusy: true, connectionStatus: '已收到点击，正在检查电脑后端…', connectionError: '', diagnosticReason: '' })
    try {
      this.setData({ baseURL: store.baseURL() })
      const health = await store.request('/health')
      if (!health || health.service !== '安心药伴' || health.status !== 'healthy') {
        const failure = new Error('地址可访问，但返回内容未通过后端识别，请检查端口')
        failure.reason = 'health response: ' + JSON.stringify({ type: typeof health, status: health && health.status, service: health && health.service })
        throw failure
      }
      this.setData({ connectionStatus: '电脑后端已连接，可以登录。', connectionError: '', diagnosticReason: '', error: '' })
    } catch (e) {
      const message = e.message || e.errMsg || String(e)
      this.setData({ connectionStatus: '连接未成功', connectionError: message, diagnosticReason: e.reason || (e.status ? 'HTTP ' + e.status : ''), error: message })
      try { wx.showModal({ title: '连接检查未通过', content: message + (e.reason ? '\n\n诊断信息：' + e.reason : ''), showCancel: false }) } catch (_) {}
    }
    finally { this.setData({ diagnosticBusy: false }) }
  },
  async submit(event) {
    if (this.data.busy || this.data.countdown) return
    const form = event.detail.value
    if (!/^1\d{10}$/.test(form.phone)) { this.setData({ error: '请填写 11 位手机号' }); return }
    if (!form.password || (this.data.register && (!form.name.trim() || form.password.length < 8 || !/[A-Za-z]/.test(form.password) || !/\d/.test(form.password)))) { this.setData({ error: '请填写称呼；密码至少 8 位且含字母和数字' }); return }
    if (!this.data.register) delete form.name
    await this.login('/api/auth/' + (this.data.register ? 'register' : 'login'), form)
  },
  demoLogin() { if (!this.data.busy) return this.login('/api/auth/demo') },
  async login(path, body) {
    if (this.data.busy) return
    this.setData({ busy: true, error: '', connectionStatus: '已收到点击，正在登录…', connectionError: '', diagnosticReason: '' })
    let storedSession = false
    try {
      const session = await store.request(path, 'POST', body)
      if (!session || !session.token) throw new Error('登录响应不完整，请检查后端地址')
      store.setSession(session); storedSession = true
      // Verify the saved session before leaving the page. A failed verification
      // stays here with its error instead of silently bouncing home -> login.
      await store.request('/api/state', 'GET', undefined, { redirectOn401: false })
      await new Promise((resolve, reject) => {
        const timer = setTimeout(() => reject(new Error('登录成功，但微信未完成首页跳转，请退出本次真机调试后重新进入')), 8000)
        try {
          wx.switchTab({ url: '/pages/home/home', success: () => { clearTimeout(timer); resolve() }, fail: failure => {
            clearTimeout(timer)
            const error = new Error('登录成功，但首页打开失败')
            error.reason = failure && failure.errMsg || 'switchTab:fail'
            reject(error)
          } })
        } catch (failure) { clearTimeout(timer); reject(failure) }
      })
    }
    catch (e) {
      if (storedSession) store.clearToken()
      const detail = e.detail || {}
      const message = e.message || e.errMsg || String(e)
      this.setData({ error: message + (detail.remainingAttempts !== undefined ? `，还可重试 ${detail.remainingAttempts} 次` : ''), remaining: detail.remainingAttempts === undefined ? 3 : detail.remainingAttempts, connectionStatus: '登录未完成', connectionError: message, diagnosticReason: e.reason || '' })
      try { wx.showModal({ title: '登录未完成', content: message + (e.reason ? '\n\n诊断信息：' + e.reason : ''), showCancel: false }) } catch (_) {}
      if (e.network) this.setData({ settingsOpen: true, baseURL: store.baseURL(), connectionStatus: '连接未成功', connectionError: e.message, diagnosticReason: e.reason || '' })
      if (detail.retryAfter) {
        this._lockUntil = Date.now() + detail.retryAfter * 1000
        clearInterval(this._timer)
        this.setData({ countdown: detail.retryAfter })
        this._timer = setInterval(() => { const countdown = Math.max(0, Math.ceil((this._lockUntil - Date.now()) / 1000)); this.setData({ countdown }); if (!countdown) { clearInterval(this._timer); this.setData({ error: '现在可以重新尝试登录。' }) } }, 500)
      }
    } finally { this.setData({ busy: false }) }
  }
})
