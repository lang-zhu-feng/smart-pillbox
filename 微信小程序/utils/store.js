const config = require('./config')
const connection = require('./connection')
const TOKEN = 'medguard.session.v2'
const days = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
const slots = [{ key: 'morning', name: '早', fullName: '早餐后', time: '08:00' }, { key: 'noon', name: '中', fullName: '午餐后', time: '12:00' }, { key: 'evening', name: '晚', fullName: '晚餐后', time: '19:00' }]
const statusMeta = { PENDING: { label: '待开盒', className: 'status-pending' }, REMINDING: { label: '提醒中', className: 'status-reminding' }, COMPLETED: { label: '已开盒', className: 'status-completed' }, OVERDUE: { label: '待确认', className: 'status-overdue' }, NO_MEDICATION: { label: '无计划', className: 'status-none' } }
let redirecting = false
function readStorage(key) { try { return wx.getStorageSync(key) || '' } catch (_) { return '' } }
let sessionToken = readStorage(TOKEN)
let savedURL = readStorage('medguard.baseURL')
let cachedPlatform = ''
try { cachedPlatform = (wx.getDeviceInfo ? wx.getDeviceInfo() : wx.getSystemInfoSync()).platform || '' } catch (_) {}
function getToken() { return sessionToken }
function clearToken() {
  sessionToken = ''
  try { if (wx.removeStorage) wx.removeStorage({ key: TOKEN }); else wx.removeStorageSync(TOKEN) } catch (_) {}
}
function persist(key, value) {
  const failed = () => { try { wx.showToast({ title: '本次设置未能保存，重新打开后需再次设置', icon: 'none', duration: 3000 }) } catch (_) {} }
  try { if (wx.setStorage) wx.setStorage({ key, data: value, fail: failed }); else wx.setStorageSync(key, value) }
  catch (_) { failed() }
}
function setSession(session) { sessionToken = session.token; persist(TOKEN, sessionToken) }
function platform() {
  return cachedPlatform
}
function isRealDevice() { const value = platform(); return !!value && value !== 'devtools' }
function baseURL() { return connection.selectURL(config, savedURL, platform()) }
function setBaseURL(value) {
  const url = value.trim().replace(/\/+$/, '')
  if (!/^https?:\/\/[A-Za-z0-9.[\]:-]+$/.test(url)) throw new Error('请填写 http://IP:端口 或 HTTPS 服务地址')
  if (isRealDevice() && connection.isLoopback(url)) throw new Error('手机不能用本机地址连接电脑，请填写电脑局域网 IP')
  if (url !== baseURL()) clearToken()
  savedURL = url
  persist('medguard.baseURL', url)
}
function requireLogin() {
  if (getToken()) return true
  if (!redirecting) { redirecting = true; wx.reLaunch({ url: '/pages/auth/auth', complete: () => { redirecting = false } }) }
  return false
}
function request(path, method = 'GET', data, options = {}) {
  const endpoint = baseURL()
  return new Promise((resolve, reject) => {
    let settled = false
    const finish = (callback, value) => { if (settled) return; settled = true; clearTimeout(watchdog); callback(value) }
    const fail = detail => {
      const raw = detail && (detail.errMsg || detail.message) || String(detail || 'request:fail')
      let message
      if (/domain|url not in domain|not in.*list/i.test(raw)) message = '请求地址被微信域名校验拦截，请在真机调试中勾选“不校验合法域名”'
      else if (/timeout|timed out/i.test(raw)) message = '连接超时，请检查真机调试通道及微信本地网络权限'
      else message = '连不上电脑后端，请检查电脑局域网服务及微信本地网络权限'
      const failure = new Error(message + '。当前地址：' + endpoint)
      failure.network = true; failure.reason = raw; failure.endpoint = endpoint
      finish(reject, failure)
    }
    const watchdog = setTimeout(() => fail({ errMsg: 'request:fail timeout (no callback from WeChat debug bridge)' }), 12000)
    try { wx.request({
    url: endpoint + path, method, data, timeout: 10000,
    header: { 'Content-Type': 'application/json', ...(getToken() ? { Authorization: 'Bearer ' + getToken() } : {}) },
    success(response) {
      if (settled) return
      if (response.statusCode >= 200 && response.statusCode < 300) { finish(resolve, response.data); return }
      const detail = response.data && response.data.detail
      const error = new Error(typeof detail === 'string' ? detail : Array.isArray(detail) ? '请检查填写格式、密码需含字母和数字' : (detail && detail.message) || '服务请求未完成')
      error.detail = detail; error.status = response.statusCode
      if (response.statusCode === 401 && !path.startsWith('/api/auth/')) { clearToken(); if (options.redirectOn401 !== false) requireLogin() }
      finish(reject, error)
    },
    fail
  }) } catch (error) { fail(error) }
  })
}
function error(message) { wx.showToast({ title: message.message || String(message), icon: 'none', duration: 3000 }) }
function page(definition) {
  return Object.assign({
    onShow() { this.refresh(); this._timer = setInterval(() => this.refresh(true), 5000) },
    onHide() { clearInterval(this._timer); if (this.data.deviceToken) this.setData({ deviceToken: '' }) },
    onUnload() { clearInterval(this._timer) },
    async refresh(silent = false) {
      if (!requireLogin() || this._refreshing || this._acting || (silent && (this.data.formOpen || this.data.editOpen))) return
      this._refreshing = true
      try { this.applyState(await request('/api/state')); this.setData({ connectionError: '' }) }
      catch (e) { this.setData({ connectionError: e.message }); if (!silent) error(e) }
      finally { this._refreshing = false }
    }
  }, definition)
}
async function run(owner, operation, title = '已保存') {
  if (owner._acting) return
  owner._acting = true
  try { const result = await operation(); if (result && result.tasks) owner.applyState(result); if (title) wx.showToast({ title, icon: 'none' }); return result }
  catch (e) { error(e) }
  finally { owner._acting = false }
}
function deviceLabel(device) { return device.online ? '设备在线' : device.hasConnected ? '设备离线' : '尚未接入硬件' }
function mondayIndex(date) { return (date.getDay() + 6) % 7 }
function sourceLabel(source) { return source === 'hardware' ? '真实设备' : source === 'demo' ? '软件模拟' : '时间规则' }
module.exports = { days, slots, statusMeta, request, page, run, error, getToken, clearToken, setSession, requireLogin, baseURL, setBaseURL, isRealDevice, deviceLabel, mondayIndex, sourceLabel }
