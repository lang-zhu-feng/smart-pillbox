const store = require('./store')

function getStatus() {
  return store.request('/api/notifications/wechat')
}

function loginCode() {
  return new Promise((resolve, reject) => {
    let settled = false
    const finish = (callback, value) => {
      if (settled) return
      settled = true
      clearTimeout(timer)
      callback(value)
    }
    const timer = setTimeout(() => finish(reject, new Error('微信身份确认超时，请稍后重试')), 12000)
    try {
      wx.login({
        timeout: 10000,
        success(result) {
          if (!result || !result.code) {
            finish(reject, new Error('未能取得微信身份，请稍后重试'))
            return
          }
          finish(resolve, result.code)
        },
        fail() { finish(reject, new Error('微信身份确认未完成，请稍后重试')) }
      })
    } catch (_) {
      finish(reject, new Error('微信身份确认未完成，请稍后重试'))
    }
  })
}

// 必须直接从点击事件调用；先弹订阅选择，再进行身份确认和后端记录。
function authorize(templateId) {
  return new Promise((resolve, reject) => {
    if (typeof templateId !== 'string' || !templateId.trim()) {
      reject(new Error('微信提醒还没有配置好，请先完成服务端设置'))
      return
    }
    if (typeof wx.requestSubscribeMessage !== 'function' || typeof wx.login !== 'function') {
      reject(new Error('当前环境不支持微信订阅提醒，请在手机微信中重试'))
      return
    }

    try {
      wx.requestSubscribeMessage({
        tmplIds: [templateId],
        success(result) {
          const decision = result && result[templateId]
          if (decision !== 'accept') {
            reject(new Error(decision === 'ban'
              ? '微信提醒权限已关闭，可在小程序设置中检查后再开启'
              : '你尚未允许这项微信提醒，可以需要时再次点击开启'))
            return
          }
          loginCode().then(code => store.request('/api/notifications/wechat/authorize', 'POST', {
            code,
            templateId
          })).then(resolve, reject)
        },
        fail() { reject(new Error('微信订阅选择未完成，请稍后重试')) }
      })
    } catch (_) {
      reject(new Error('微信订阅选择未完成，请稍后重试'))
    }
  })
}

module.exports = { getStatus, authorize }
