const store = require('./utils/store')

App({
  onLaunch() {
    store.ensureState()
  },
  globalData: {
    appName: '安心药伴'
  }
})
