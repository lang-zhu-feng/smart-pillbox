const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('C:/Users/liuzhanfei/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');

(async () => {
  const info = JSON.parse(fs.readFileSync(path.join(__dirname,'public-link.json'),'utf8').replace(/^\uFEFF/,''));
  const errors = [];
  const browserPath = [
    'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
    'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
    'C:/Program Files/Google/Chrome/Application/chrome.exe',
    'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe',
  ].find(p=>fs.existsSync(p));
  const browser = await chromium.launch({headless:true,...(browserPath?{executablePath:browserPath}:{})});
  try {
    const context = await browser.newContext({viewport:{width:390,height:844},isMobile:true,hasTouch:true});
    const page = await context.newPage();
    page.on('pageerror', e => errors.push(e.message));
    await page.goto(info.url,{waitUntil:'networkidle',timeout:45000});
    await page.locator('#demo-login').click();
    await page.locator('#auth-screen').waitFor({state:'hidden',timeout:20000});
    await page.locator('button.main-cta[data-page="pillbox"]').click();
    await page.locator('.pill-grid').waitFor({state:'visible'});
    const cells = await page.locator('.pill-grid button.cell').count();
    if(cells!==21)throw Error('Expected 21 compartments, got '+cells);
    await page.waitForFunction(()=>{const el=document.querySelector('#screen .page');return !el||Number(getComputedStyle(el).opacity)>0.99;});
    await page.screenshot({path:path.join(__dirname,'logs/mobile-pillbox.png'),fullPage:true});
    const qrData='data:image/png;base64,'+fs.readFileSync(path.join(__dirname,'../output/智慧药盒_公网体验二维码.png')).toString('base64');
    const qrCheck=await page.evaluate(async data=>{
      if(!('BarcodeDetector' in window))return {performed:false};
      const formats=await BarcodeDetector.getSupportedFormats();
      if(!formats.includes('qr_code'))return {performed:false};
      const bitmap=await createImageBitmap(await (await fetch(data)).blob());
      const codes=await new BarcodeDetector({formats:['qr_code']}).detect(bitmap);
      return {performed:true,value:codes[0]?.rawValue||null};
    },qrData);
    if(qrCheck.performed&&qrCheck.value!==info.url)throw Error('QR image did not decode to the public preview URL');
    const first = await context.request.post(info.origin+'/api/auth/demo');
    const firstSession = await first.json();
    const second = await context.request.post(info.origin+'/api/auth/demo');
    const secondSession = await second.json();
    async function state(token){ const r=await context.request.get(info.origin+'/api/state',{headers:{Authorization:'Bearer '+token}}); if(!r.ok())throw Error('State failed '+r.status()); return r.json(); }
    const a=await state(firstSession.token), b=await state(secondSession.token);
    if(a.device.code===b.device.code)throw Error('Guest families are not isolated');
    const task=a.tasks.find(t=>!['NO_MEDICATION','COMPLETED'].includes(t.status));
    if(!task)throw Error('No scheduled demo task found');
    const opened=await context.request.post(info.origin+'/api/demo/tasks/'+encodeURIComponent(task.id)+'/open',{headers:{Authorization:'Bearer '+firstSession.token}});
    if(!opened.ok())throw Error('Demo open failed '+opened.status());
    const after=await opened.json();
    if(after.tasks.find(t=>t.id===task.id).status!=='COMPLETED')throw Error('Open did not update the task');
    const bAfter=await state(secondSession.token);
    if(bAfter.tasks.find(t=>t.id===task.id).status==='COMPLETED')throw Error('Guest action affected another family');
    if(after.device.online)throw Error('Software demo incorrectly marked hardware online');
    if(errors.length)throw Error('Browser errors: '+errors.join('; '));
    const result={mobileViewport:'390x844',compartments:cells,guestIsolation:true,openEvent:true,hardwareRemainsOffline:true,qrDecode:qrCheck,browserErrors:errors};
    fs.writeFileSync(path.join(__dirname,'logs/verification.json'),JSON.stringify(result,null,2));
    console.log(JSON.stringify(result));
  } finally { await browser.close(); }
})().catch(e=>{console.error(e.stack);process.exitCode=1;});
