// Run with Node. Exercises the real helper using mocked WeChat and backend boundaries.
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('assert/strict');

const helperPath = path.join(__dirname, '..', '微信小程序', 'utils', 'wechat-notifications.js');

function harness(options = {}) {
  const calls = [];
  const requests = [];
  const subscriptionRequests = [];
  const loginRequests = [];
  const response = {
    configured: true,
    available: true,
    unavailableReason: '',
    templateId: 'approved-template',
    authorizedCredits: 1,
    lastDeliveryStatus: '',
    lastDeliveryMessage: ''
  };
  const store = {
    request(endpoint, method = 'GET', data) {
      calls.push('backend');
      requests.push({ endpoint, method, data });
      if (options.backendFailure) return Promise.reject(new Error('后端保存授权失败'));
      return Promise.resolve({ ...response });
    }
  };
  const wx = {
    canIUse: () => true
  };
  if (!options.noSubscriptionAPI) {
    wx.requestSubscribeMessage = request => {
      calls.push('subscribe');
      subscriptionRequests.push(request);
      if (options.subscribeThrows) throw new Error('subscription bridge failed');
      if (options.manualSubscription) return;
      if (options.subscribeFails) {
        request.fail({ errMsg: 'requestSubscribeMessage:fail test' });
        return;
      }
      const templateId = request.tmplIds[0];
      request.success({ [templateId]: options.subscriptionResult || 'accept', errMsg: 'requestSubscribeMessage:ok' });
    };
  }
  if (!options.noLoginAPI) {
    wx.login = request => {
      calls.push('login');
      loginRequests.push(request);
      if (options.loginThrows) throw new Error('login bridge failed');
      if (options.loginFails) {
        request.fail({ errMsg: 'login:fail test' });
        return;
      }
      request.success({
        code: options.emptyLoginCode ? '' : 'one-time-login-code',
        // The client must not forward or rely on any claimed openid.
        openid: 'untrusted-client-openid',
        errMsg: 'login:ok'
      });
    };
  }
  const module = { exports: {} };
  vm.runInNewContext(fs.readFileSync(helperPath, 'utf8'), {
    module,
    exports: module.exports,
    require(name) {
      assert.equal(name, './store', 'The helper should use the authenticated backend store');
      return store;
    },
    wx,
    setTimeout,
    clearTimeout,
    console
  }, { filename: helperPath });
  return { api: module.exports, calls, requests, subscriptionRequests, loginRequests, response };
}

async function mustReject(operation, label) {
  let rejected = false;
  try {
    await (typeof operation === 'function' ? operation() : operation);
  } catch (error) {
    rejected = true;
    assert(error && typeof error.message === 'string' && error.message.length, label + ': report a useful failure');
  }
  assert(rejected, label + ': must reject rather than report success');
}

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((ok, fail) => { resolve = ok; reject = fail; });
  return { promise, resolve, reject };
}

function pageHarness() {
  const authorizeResult = deferred();
  const statusResult = deferred();
  const calls = [];
  const toasts = [];
  let definition;
  const notifications = {
    getStatus() { calls.push('status'); return statusResult.promise; },
    authorize(templateId) { calls.push({ authorize: templateId }); return authorizeResult.promise; }
  };
  const store = {
    page: value => value,
    sourceLabel: source => source
  };
  const pagePath = path.join(__dirname, '..', '微信小程序', 'pages', 'alerts', 'alerts.js');
  vm.runInNewContext(fs.readFileSync(pagePath, 'utf8'), {
    require(name) {
      if (name === '../../utils/store') return store;
      assert.equal(name, '../../utils/wechat-notifications');
      return notifications;
    },
    Page(value) { definition = value; },
    wx: { showToast(options) { toasts.push(options); } }
  }, { filename: pagePath });
  const page = {
    ...definition,
    data: JSON.parse(JSON.stringify(definition.data)),
    setData(values) { Object.assign(this.data, values); }
  };
  return { page, calls, toasts, authorizeResult, statusResult };
}

const flushPromises = () => new Promise(resolve => setImmediate(resolve));

async function main() {
  const status = harness();
  const reported = await status.api.getStatus();
  assert.equal(reported.templateId, status.response.templateId);
  assert.equal(status.requests.length, 1);
  assert.equal(status.requests[0].endpoint, '/api/notifications/wechat');
  assert.equal(status.requests[0].method, 'GET');
  assert.equal(status.subscriptionRequests.length, 0);

  const unconfigured = harness();
  await mustReject(() => unconfigured.api.authorize(''), 'Missing template');
  assert.equal(unconfigured.calls.length, 0);

  const unsupported = harness({ noSubscriptionAPI: true });
  await mustReject(() => unsupported.api.authorize('approved-template'), 'Unsupported WeChat version');
  assert.equal(unsupported.loginRequests.length, 0);
  assert.equal(unsupported.requests.length, 0);

  const gesture = harness({ manualSubscription: true });
  const pending = gesture.api.authorize('approved-template');
  assert.deepEqual(gesture.calls, ['subscribe'], 'Ask for subscription directly during the click, before login or backend work');
  assert.equal(gesture.subscriptionRequests.length, 1);
  assert.deepEqual(Array.from(gesture.subscriptionRequests[0].tmplIds), ['approved-template']);
  assert.equal(gesture.loginRequests.length, 0);
  assert.equal(gesture.requests.length, 0);
  gesture.subscriptionRequests[0].success({ 'approved-template': 'accept' });
  const authorized = await pending;
  assert.equal(authorized.authorizedCredits, 1);
  assert.deepEqual(gesture.calls, ['subscribe', 'login', 'backend']);
  assert.equal(gesture.requests.length, 1);
  assert.equal(gesture.requests[0].endpoint, '/api/notifications/wechat/authorize');
  assert.equal(gesture.requests[0].method, 'POST');
  assert.equal(gesture.requests[0].data.code, 'one-time-login-code');
  assert.equal(gesture.requests[0].data.templateId, 'approved-template');
  assert.deepEqual(Object.keys(gesture.requests[0].data).sort(), ['code', 'templateId']);

  for (const subscriptionResult of ['reject', 'ban', 'filter', 'unexpected']) {
    const refused = harness({ subscriptionResult });
    await mustReject(() => refused.api.authorize('approved-template'), 'Subscription result ' + subscriptionResult);
    assert.equal(refused.loginRequests.length, 0, 'A non-accept result must not obtain a login code');
    assert.equal(refused.requests.length, 0, 'A non-accept result must not add backend authorization credits');
  }

  for (const options of [{ subscribeFails: true }, { subscribeThrows: true }]) {
    const failed = harness(options);
    await mustReject(() => failed.api.authorize('approved-template'), 'Subscription API failure');
    assert.equal(failed.loginRequests.length, 0);
    assert.equal(failed.requests.length, 0);
  }

  for (const options of [{ emptyLoginCode: true }, { loginFails: true }, { loginThrows: true }, { noLoginAPI: true }]) {
    const failed = harness(options);
    await mustReject(() => failed.api.authorize('approved-template'), 'Login code failure');
    assert.equal(failed.requests.length, 0, 'An absent login code must never reach the backend');
  }

  const backendFailed = harness({ backendFailure: true });
  await mustReject(() => backendFailed.api.authorize('approved-template'), 'Backend authorization failure');
  assert.equal(backendFailed.requests.length, 1);
  const statusFailed = harness({ backendFailure: true });
  await mustReject(() => statusFailed.api.getStatus(), 'Status request failure');

  const unavailablePage = pageHarness();
  unavailablePage.page.enableWechatNotifications();
  assert.equal(unavailablePage.calls.length, 0, 'Do not request an unavailable notification channel');

  const busyPage = pageHarness();
  busyPage.page.data.wechat = { available: true, templateId: 'approved-template', authorizedCredits: 0 };
  busyPage.page.enableWechatNotifications();
  busyPage.page.enableWechatNotifications();
  assert.equal(busyPage.calls.length, 1, 'Repeated clicks while waiting must not request two authorizations');
  assert.equal(busyPage.calls[0].authorize, 'approved-template');
  assert.equal(busyPage.page.data.wechatBusy, true);
  busyPage.authorizeResult.reject(new Error('订阅尚未保存'));
  await flushPromises();
  assert.equal(busyPage.page.data.wechatBusy, false);
  assert.equal(busyPage.page.data.wechatError, '订阅尚未保存');
  assert.equal(busyPage.toasts.length, 0, 'A failed authorization must not display a success toast');

  const stalePage = pageHarness();
  stalePage.page.data.wechat = { available: true, templateId: 'approved-template', authorizedCredits: 0 };
  const earlierStatus = stalePage.page.refreshWechatStatus();
  stalePage.page.enableWechatNotifications();
  stalePage.authorizeResult.resolve({ available: true, templateId: 'approved-template', authorizedCredits: 1 });
  await flushPromises();
  stalePage.statusResult.resolve({ available: true, templateId: 'approved-template', authorizedCredits: 0 });
  await earlierStatus;
  assert.equal(stalePage.page.data.wechat.authorizedCredits, 1, 'Old polling results must not replace newly saved authorization');
  assert.equal(stalePage.page.data.wechatBusy, false);
  assert.equal(stalePage.toasts.length, 1);

  console.log('PASS: subscription gesture order, refusal/unsupported handling, code exchange, backend failures, no client openid trust, page busy/error state, and stale polling protection');
}

main().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
