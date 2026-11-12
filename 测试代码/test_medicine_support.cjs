// Native page behavior with mocked wx transport; no developer-tool or live data access.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.join(__dirname, '..', '微信小程序');

function loadPage(name, initial) {
  let definition, result = initial;
  const calls = [], errors = [], timers = new Map();
  const store = {
    requireLogin: () => true, error: error => errors.push(error.message || String(error)),
    request: async (url, method = 'GET', body) => { calls.push({url, method, body}); return result; },
    async run(owner, operation) { if (owner._acting) return; owner._acting = true; try { return await operation(); } finally { owner._acting = false; } }
  };
  const wx = {showModal: options => options.success({confirm:true}), switchTab: options => calls.push({navigate:options.url}), setClipboardData: options => calls.push({clipboard:options.data})};
  vm.runInNewContext(fs.readFileSync(path.join(root, 'pages', name, name + '.js'), 'utf8'), {
    require: () => store, Page: value => { definition = value; }, wx,
    setInterval: (callback, delay) => { timers.set(1, {callback, delay}); return 1; }, clearInterval: id => timers.delete(id)
  });
  const page = {...definition, data: JSON.parse(JSON.stringify(definition.data)), setData: values => Object.assign(page.data, values)};
  return {page, calls, errors, timers, respond: value => {result = value;}};
}

async function main() {
  const app = JSON.parse(fs.readFileSync(path.join(root, 'app.json'), 'utf8'));
  assert(app.pages.includes('pages/medicines/medicines'));
  assert(app.pages.includes('pages/companions/companions'));
  const notes = {items:[{planId:'a',medicine:'测试药品',enabled:true,storage:'',source:''}], storageTips:['测试提示'], retrievalTips:[], sources:[], prototypeNotice:'原型不能实际存药'};
  const medicines = loadPage('medicines', notes);
  await medicines.page.refresh();
  assert.equal(medicines.page.data.current.planId, 'a');
  medicines.page.edit(); assert.equal(medicines.page.data.editOpen, true);
  medicines.respond({...notes, items:[{...notes.items[0],storage:'测试原文',source:'测试来源'}]});
  await medicines.page.save({detail:{value:{storage:'测试原文',source:'测试来源'}}});
  assert.equal(medicines.calls.at(-1).url, '/api/medicines/a');
  assert.equal(medicines.page.data.current.storage, '测试原文');
  assert.equal(medicines.page.data.editOpen, false);
  const initial = {profile:{enabled:false,alias:'',about:'',planId:''},eligibleMedicines:[{planId:'a',medicine:'测试药品'}],candidates:[],requests:[],connections:[]};
  const companions = loadPage('companions', initial), page = companions.page;
  await page.refresh();
  const before = companions.calls.length;
  await page.saveProfile({detail:{value:{alias:'测试昵称',about:'',consent:[]}}});
  assert.equal(companions.calls.length, before, 'Do not enable without explicit participant consent');
  assert(companions.errors.some(error => error.includes('本人同意')));
  const enabled = {...initial,profile:{enabled:true,alias:'测试昵称',about:'',planId:'a'}};
  companions.respond(enabled);
  await page.saveProfile({detail:{value:{alias:'测试昵称',about:'',consent:['yes']}}});
  assert.equal(companions.calls.at(-1).body.participantConsent, true);
  assert.equal(companions.calls.at(-1).body.planId, 'a');
  const connected = {...enabled,connections:[{id:'relation',alias:'测试药友',medicine:'测试药品'}]};
  page.applySupport(connected);
  companions.respond({items:[{id:1,mine:true,content:'测试问候'}]});
  await page.openChat({currentTarget:{dataset:{id:'relation',alias:'测试药友'}}});
  assert.equal(page.data.messages.length, 1);
  page.typeMessage({detail:{value:'  测试问候  '}});
  await page.sendMessage();
  assert.equal(companions.calls.at(-1).body.content, '测试问候');
  assert.equal(page.data.draft, '');
  page.applySupport(initial);
  assert.equal(page.data.chatId, '', 'Withdrawal or a paused plan must close the visible chat');
  assert.equal(page.data.messages.length, 0);
  companions.respond(initial);
  page.onShow();
  assert.equal(companions.timers.get(1).delay, 8000);
  page.onHide(); assert.equal(companions.timers.size, 0);
  console.log('PASS: native medicine loading/save, consent gate, request bodies, chat and withdrawal, timer cleanup, page registration.');
}
main().catch(error => {console.error(error);process.exitCode=1;});
