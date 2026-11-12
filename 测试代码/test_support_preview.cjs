// End-to-end preview test; isolated temporary database, no existing family data.
// NODE_PATH must resolve playwright; uses the Python recorded by backend/.venv.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const net = require('node:net');
const { spawn } = require('node:child_process');
const { chromium } = require('playwright');
const root = path.resolve(__dirname, '..');

async function main() {
  const temporary = fs.mkdtempSync(path.join(os.tmpdir(), 'medguard-support-'));
  const home = fs.readFileSync(path.join(root, 'backend/.venv/pyvenv.cfg'), 'utf8').match(/^home\s*=\s*(.+)$/m)[1].trim();
  const interpreter = process.env.MEDGUARD_TEST_PYTHON || path.join(home, 'python.exe');
  const port = await new Promise((resolve, reject) => {
    const server = net.createServer(); server.on('error', reject);
    server.listen(0, '127.0.0.1', () => { const value = server.address().port; server.close(() => resolve(value)); });
  });
  const base = 'http://127.0.0.1:' + port;
  const server = spawn(interpreter, ['-m', 'uvicorn', 'backend.main:app', '--host', '127.0.0.1', '--port', String(port)], {
    cwd: root, windowsHide: true,
    env: { ...process.env, PYTHONPATH: path.join(root, 'backend/.venv/Lib/site-packages'), PYTHONDONTWRITEBYTECODE: '1', MEDGUARD_DB: path.join(temporary, 'test.sqlite3') },
    stdio: ['ignore', 'pipe', 'pipe']
  });
  let output = '', browser, spawnError;
  server.stdout.on('data', chunk => { output = (output + chunk).slice(-12000); });
  server.stderr.on('data', chunk => { output = (output + chunk).slice(-12000); });
  server.on('error', error => { spawnError = error; });
  try {
    let ready = false;
    for (let i = 0; i < 100; i++) {
      if (spawnError) throw spawnError;
      if (server.exitCode !== null) throw new Error('Test server exited: ' + output);
      try { ready = (await fetch(base + '/health')).ok; } catch (_) {}
      if (ready) break;
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    assert(ready, 'Temporary test server should start');
    async function api(token, route, method = 'GET', body) {
      const result = await fetch(base + route, { method, headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: 'Bearer ' + token } : {}) }, ...(body ? { body: JSON.stringify(body) } : {}) });
      const value = await result.json(); assert(result.ok, JSON.stringify(value)); return value;
    }
    async function account(phone, name) {
      const result = await api('', '/api/auth/register', 'POST', {phone, name, password: 'Hello12345'});
      await api(result.token, '/api/plans', 'POST', {medicine: '功能测试用药（模拟物）', dosage: '仅测试', days: [0,1,2,3,4,5,6], slotKey: 'morning', time: '08:00', note: ''});
      return result.token;
    }
    const firstToken = await account('13922220001', '测试家属甲');
    const secondToken = await account('13922220002', '测试家属乙');
    const executablePath = process.env.MEDGUARD_TEST_BROWSER || 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
    browser = await chromium.launch({headless: true, executablePath});
    const errors = [];
    async function open(token) {
      const context = await browser.newContext({viewport: {width: 1280, height: 1000}});
      await context.addInitScript(value => localStorage.setItem('medguard.session.v2', value), token);
      const page = await context.newPage(); page.on('pageerror', error => errors.push(error.message));
      await page.goto(base + '/preview'); await page.locator('#tabs [data-page="profile"]').waitFor(); return page;
    }
    async function companions(page) {
      await page.locator('#tabs [data-page="profile"]').click();
      await page.locator('[data-page="companions"]').click();
      await page.locator('[data-support-action="edit-profile"]').waitFor();
    }
    async function enable(page, alias) {
      await page.locator('[data-support-action="edit-profile"]').click();
      await page.locator('#support-alias').fill(alias);
      await page.locator('#support-about').fill('喜欢散步（自动化测试）');
      await page.locator('[data-support-form="profile"] [name="consent"]').check();
      await page.locator('[data-support-form="profile"] [type="submit"]').click();
      await page.locator('#support-root').getByText('已开启自愿交流', {exact: true}).waitFor();
    }
    const a = await open(firstToken), b = await open(secondToken);
    await a.locator('#tabs [data-page="plans"]').click();
    await a.locator('[data-page="medicines"]').click();
    await a.locator('[data-support-action="edit-medicine"]').click();
    const introduction = '<img src=x onerror=alert(1)> 仅为资料显示测试';
    const storage = '测试包装原文（不是真实药品贮藏要求）';
    await a.locator('#support-introduction').fill(introduction);
    await a.locator('#support-storage').fill(storage);
    await a.locator('#support-source').fill('自动化测试用虚构包装，不用于医疗');
    await a.locator('[data-support-form="medicine"] [type="submit"]').click();
    await a.locator('[data-support-action="edit-medicine"]').getByText('按说明书补充资料', {exact:true}).waitFor();
    assert((await a.locator('#support-root').innerText()).includes(introduction));
    assert.equal(await a.locator('#support-root img').count(), 0, 'Entered medicine notes must render as text');
    assert.equal((await api(firstToken, '/api/medicines')).items[0].storage, storage);
    assert.equal((await api(secondToken, '/api/medicines')).items[0].storage, '');
    const screenshotDirectory = process.env.MEDGUARD_SCREENSHOT_DIR;
    if (screenshotDirectory) {
      fs.mkdirSync(screenshotDirectory, {recursive:true});
      await a.locator('#screen').evaluate(element => {element.scrollTop = 0;});
      await a.locator('.phone').screenshot({path:path.join(screenshotDirectory, 'medicine-preview.png')});
    }
    await companions(a); await enable(a, '晚风');
    await companions(b); await enable(b, '山茶');
    await a.locator('[data-support-action="invite"]').waitFor({timeout:20000});
    await a.locator('[data-support-action="invite"]').click();
    await b.locator('[data-support-action="decide"][data-decision="accept"]').waitFor({timeout:20000});
    await b.locator('[data-support-action="decide"][data-decision="accept"]').click();
    await a.locator('[data-support-action="chat"]').waitFor({timeout:20000});
    await a.locator('[data-support-action="chat"]').click();
    const greeting = '你好，一起散步吗？<b>仅测试文字</b>';
    await a.locator('#support-message').fill(greeting);
    await a.locator('[data-support-form="chat"] [type="submit"]').click();
    await a.locator('.support-message').getByText(greeting, {exact:true}).waitFor();
    await b.locator('[data-support-action="chat"]').click();
    await b.locator('.support-message').getByText(greeting, {exact:true}).waitFor();
    assert.equal(await b.locator('.support-message b').count(), 0);
    if (screenshotDirectory) await b.locator('.phone').screenshot({path:path.join(screenshotDirectory, 'companion-preview.png')});
    const requestId = (await api(firstToken, '/api/companions')).connections[0].id;
    b.once('dialog', dialog => dialog.accept());
    await b.locator('[data-support-action="disable"]').click();
    await b.locator('#support-root').getByText('默认关闭 · 由你决定', {exact:true}).waitFor();
    await a.locator('[data-support-action="chat"]').waitFor({state:'detached', timeout:20000});
    const closed = await fetch(base + '/api/companions/connections/' + requestId + '/messages', {headers:{Authorization:'Bearer ' + firstToken}});
    assert.equal(closed.status, 409);
    assert.deepEqual(errors, []);
    console.log('PASS: browser medicine save/isolation/text escaping; two-account consent, invitation, acceptance, chat and withdrawal; no page errors.');
    if (screenshotDirectory) console.log('Screenshots: ' + screenshotDirectory);
  } finally {
    if (browser) await browser.close();
    if (server.exitCode === null && !spawnError) {
      server.kill();
      await Promise.race([new Promise(resolve => server.once('exit', resolve)), new Promise(resolve => setTimeout(resolve, 5000))]);
    }
    if (server.exitCode !== null || spawnError) fs.rmSync(temporary, {recursive:true, force:true});
  }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
