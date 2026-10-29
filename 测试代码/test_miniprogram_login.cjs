// Run with Node. Check real page/store modules while simulating wx boundaries.
const fs = require('fs'), path = require('path'), vm = require('vm'), assert = require('assert/strict');
const root = path.join(__dirname, '..', '微信小程序');
function harness({platform = 'ios', storedURL = 'http://127.0.0.1:8766', mode = 'ok', navigateFails = false, navigationSilent = false, storageReadFails = false, storageWriteFails = false, modalFails = false, transport} = {}) {
  const memory = new Map([['medguard.baseURL', storedURL]]), requests = [], cache = new Map(), timers = new Map(), modals = [], toasts = [];
  let definition, route = '', redirects = 0, timerID = 0, storageReads = 0;
  const schedule = (callback, delay) => {const id = ++timerID;timers.set(id,{callback,delay});return id};
  const wx = {
    getDeviceInfo: () => ({platform}), getStorageSync: key => {storageReads++;if (storageReadFails) throw {errMsg:'getStorageSync:fail debug sync'};return memory.get(key)},
    setStorage(options) {if (storageWriteFails) return options.fail({errMsg:'setStorage:fail'});memory.set(options.key,options.data)},
    removeStorage(options) {memory.delete(options.key)},
    showToast(options) {toasts.push(options)}, showModal(options) {if (modalFails) throw {errMsg:'showModal:fail'};modals.push(options)},
    reLaunch(options) { redirects++; route = options.url; options.complete && options.complete() },
    switchTab(options) { if (navigationSilent) return; if (navigateFails) options.fail({errMsg:'switchTab:fail test failure'}); else { route = options.url; options.success() } },
    request(options) {
      requests.push(options.url);
      if (transport) return transport(options);
      if (mode === 'silent') return;
      if (mode === 'throw') throw {errMsg:'request:fail debug bridge exception'};
      if (mode === 'network') return options.fail({errMsg:'request:fail timeout'});
      if (mode === 'domain') return options.fail({errMsg:'request:fail url not in domain list'});
      if (options.url.endsWith('/api/state') && mode === 'expired') return options.success({statusCode:401,data:{detail:'登录已过期，请重新登录'}});
      const data = options.url.endsWith('/health') ? {status:'healthy',service:'安心药伴'} : options.url.endsWith('/api/state') ? {tasks:[]} : {token:'new-session',name:'示例家属'};
      options.success({statusCode:200,data});
    }
  };
  function load(file) {
    file = path.resolve(file); if (cache.has(file)) return cache.get(file);
    const module = {exports:{}};
    vm.runInNewContext(fs.readFileSync(file, 'utf8'), {module, require:name=>load(path.resolve(path.dirname(file), name+'.js')), wx, Page:value=>{definition=value}, setTimeout:transport ? setTimeout : schedule, clearTimeout:transport ? clearTimeout : id=>timers.delete(id), setInterval, clearInterval, Date, console}, {filename:file});
    cache.set(file,module.exports);return module.exports;
  }
  const store = load(path.join(root, 'utils/store.js'));
  load(path.join(root, 'pages/auth/auth.js'));
  const auth = {...definition, data:JSON.parse(JSON.stringify(definition.data)), setData(values) {Object.assign(this.data,values)}};
  auth.onLoad();
  return {store,auth,memory,requests,modals,toasts,timers,route:()=>route,redirects:()=>redirects,storageReads:()=>storageReads,
    timeout() {const [id,timer] = [...timers].sort((a,b)=>a[1].delay-b[1].delay)[0] || [];assert(timer,'Expected a pending timeout');timers.delete(id);timer.callback()}};
}
(async()=>{
  const selector = require(path.join(root, 'utils/connection.js'));
  const cfg = {baseURL:'http://127.0.0.1:8766',deviceBaseURL:'http://172.20.10.7:8766'};
  assert.equal(selector.selectURL(cfg,'http://127.0.0.1:8766','devtools'),cfg.baseURL);
  for (const platform of ['ios','android']) for (const saved of ['',cfg.baseURL,'http://localhost:8766','http://[::1]:8766']) assert.equal(selector.selectURL(cfg,saved,platform),cfg.deviceBaseURL);
  assert.equal(selector.selectURL(cfg,'http://192.168.1.10:8766','ios'),'http://192.168.1.10:8766');
  const success = harness(); await success.auth.login('/api/auth/demo');
  assert.equal(success.route(),'/pages/home/home');assert(success.requests.every(url=>url.startsWith(cfg.deviceBaseURL)));assert.equal(success.requests.length,2);assert.equal(success.auth.data.busy,false);
  assert.throws(()=>success.store.setBaseURL('http://localhost:8766'),/电脑局域网 IP/);
  assert.equal(success.memory.get('medguard.baseURL'),cfg.baseURL);
  assert.equal(success.timers.size,0);assert.equal(success.storageReads(),2,'Only read native storage during initialization');
  for (const mode of ['network','domain','expired','throw']) {
    const failed = harness({mode});await failed.auth.login('/api/auth/demo');
    assert.equal(failed.route(),'');assert.equal(failed.auth.data.busy,false);assert(failed.auth.data.error);assert.equal(failed.memory.get('medguard.session.v2'),undefined);
    assert.equal(failed.modals.length,1);assert.equal(failed.timers.size,0);
    if (mode === 'expired') assert.equal(failed.redirects(),0,'Auth verification must not silently re-launch the login page');
    else {
      assert.equal(failed.auth.data.settingsOpen,true);
      assert(failed.auth.data.connectionError);
      assert(failed.auth.data.diagnosticReason.includes('request:fail'));
      const reason = failed.auth.data.diagnosticReason;
      failed.auth.switchMode();
      assert.equal(failed.auth.data.diagnosticReason, reason, 'Switching login/register must preserve network diagnostics');
    }
  }
  const navigation = harness({navigateFails:true});await navigation.auth.login('/api/auth/demo');assert(navigation.auth.data.error.includes('首页打开失败'));assert.equal(navigation.memory.get('medguard.session.v2'),undefined);
  const diagnostic = harness();await diagnostic.auth.checkConnection();assert.equal(diagnostic.auth.data.connectionStatus,'电脑后端已连接，可以登录。');
  const diagnosticFailure = harness({mode:'domain'});await diagnosticFailure.auth.checkConnection();assert.equal(diagnosticFailure.auth.data.connectionStatus,'连接未成功');assert(diagnosticFailure.auth.data.diagnosticReason.includes('url not in domain list'));
  const brokenCache = harness({storageReadFails:true});await brokenCache.auth.checkConnection();await brokenCache.auth.demoLogin();assert.equal(brokenCache.route(),'/pages/home/home');assert.equal(brokenCache.storageReads(),2);
  const failedSave = harness({storageWriteFails:true});await failedSave.auth.demoLogin();assert.equal(failedSave.route(),'/pages/home/home');assert(failedSave.store.getToken());assert(failedSave.toasts.some(item=>item.title.includes('未能保存')));
  for (const action of ['demoLogin','checkConnection']) {
    const silent = harness({mode:'silent'});const pending = silent.auth[action]();
    assert(silent.auth.data.connectionStatus.includes('已收到点击'));silent.timeout();await pending;
    assert.equal(silent.auth.data.busy,false);assert.equal(silent.auth.data.diagnosticBusy,false);assert(silent.auth.data.diagnosticReason.includes('no callback'));assert.equal(silent.modals.length,1);
  }
  const navSilent = harness({navigationSilent:true});const pendingNavigation = navSilent.auth.demoLogin();
  for(let i=0;i<6;i++) await Promise.resolve();navSilent.timeout();await pendingNavigation;
  assert.equal(navSilent.auth.data.busy,false);assert(navSilent.auth.data.error.includes('未完成首页跳转'));assert.equal(navSilent.store.getToken(),'');
  const modalFailure = harness({mode:'throw',modalFails:true});await modalFailure.auth.demoLogin();assert.equal(modalFailure.auth.data.busy,false);assert(modalFailure.auth.data.error);
  console.log('PASS: address selection, native storage exceptions, session validation, network/domain failures, lost request/navigation callbacks, persistent error messages');
  if (process.argv.includes('--live')) {
    const http = require('http');
    const live = harness({transport(options) {
      const request = http.request(options.url,{method:options.method,headers:options.header},response=>{
        let body='';response.setEncoding('utf8');response.on('data',chunk=>body+=chunk);
        response.on('end',()=>{try {options.success({statusCode:response.statusCode,data:JSON.parse(body)})} catch(error) {options.fail({errMsg:error.message})}});
      });
      request.setTimeout(options.timeout,()=>request.destroy(new Error('timeout')));
      request.on('error',error=>options.fail({errMsg:error.message}));
      if(options.data !== undefined) request.write(JSON.stringify(options.data));request.end();
    }});
    await live.auth.checkConnection();assert.equal(live.auth.data.connectionError,'');
    await live.auth.demoLogin();assert.equal(live.route(),'/pages/home/home');
    await live.store.request('/api/auth/logout','POST');live.store.clearToken();
    console.log('PASS: actual LAN health -> demo login -> session state -> home navigation host adapter -> logout (no phone rendering verified)');
  }
})().catch(error=>{console.error(error);process.exit(1)});
