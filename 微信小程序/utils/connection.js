function isLoopback(url) {
  return /^https?:\/\/(?:127(?:\.\d{1,3}){3}|localhost|\[::1\])(?=[:/]|$)/i.test(url || '')
}

function selectURL(config, saved, platform) {
  const realDevice = !!platform && platform !== 'devtools'
  // Shared developer-tool storage can contain its localhost setting. A phone
  // must use the computer address instead, without changing the tool's storage.
  if (realDevice && isLoopback(saved || config.baseURL)) {
    return config.deviceBaseURL || config.baseURL
  }
  return saved || (realDevice ? config.deviceBaseURL : config.baseURL) || config.baseURL
}

module.exports = { isLoopback, selectURL }
