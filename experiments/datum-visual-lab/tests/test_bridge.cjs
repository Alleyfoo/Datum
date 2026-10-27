// Optional browser bridge check. Run with Node and Playwright available (see README).
// This deliberately simulates a host; it is not a reference-host compatibility test.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const html = fs.readFileSync(path.join(root, 'app.template.html'), 'utf8').replace('__DATA_JSON__', '{}');
const offline = fs.readFileSync(path.join(root, 'datum_visual_lab.html'), 'utf8');
const fixture = JSON.parse(offline.match(/<script id="datum-seed" type="application\/json">(.*?)<\/script>/s)[1]);
(async () => {
 const executablePath = process.env.DATUM_BROWSER || undefined;
 const browser = await chromium.launch({headless:true, ...(executablePath ? {executablePath} : {})});
 try {
  const page = await browser.newPage();
  const errors=[];page.on('pageerror', e=>errors.push(e.message));
  await page.setContent('<iframe id="app" style="width:1200px;height:900px"></iframe>');
  await page.evaluate((source)=>{
   window.messages=[];
   window.addEventListener('message',e=>window.messages.push(e.data));
   document.querySelector('iframe').srcdoc=source;
  }, html);
  await page.waitForFunction(()=>window.messages.some(m=>m.method==='ui/initialize'));
  const frame=page.frameLocator('#app');
  assert.equal(await frame.locator('.wrap').isVisible(),false);
  assert.match(await frame.locator('#connectionStatus').innerText(),/waiting for the host tool result/);
  await page.evaluate(()=>document.querySelector('iframe').contentWindow.postMessage({jsonrpc:'2.0',id:831,result:{protocolVersion:'2026-01-26'}},'*'));
  await page.waitForFunction(()=>window.messages.some(m=>m.method==='ui/notifications/initialized'));
  await page.evaluate(()=>document.querySelector('iframe').contentWindow.postMessage({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:{content:[{type:'text',text:'No structured data'}]}},'*'));
  await frame.locator('#connectionStatus').getByText('MCP Apps: tool result missing valid structured data. No result displayed.').waitFor();
  assert.equal(await frame.locator('.wrap').isVisible(),false);
  const first=structuredClone(fixture.baseline);first.machines.find(m=>m.id==='BC-01').name='Changed live record';
  await page.evaluate((d)=>document.querySelector('iframe').contentWindow.postMessage({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:{structuredContent:d}},'*'),first);
  await frame.locator('#machineRows').getByText('Changed live record').waitFor();
  assert.match(await frame.locator('#connectionStatus').innerText(),/MCP tool result/);
  await frame.locator('#scenarioPicker').selectOption('delivery');
  await page.waitForFunction(()=>window.messages.some(m=>m.method==='tools/call'));
  const request=await page.evaluate(()=>window.messages.find(m=>m.method==='tools/call'));
  assert.deepEqual(request.params,{name:'datum_visualize',arguments:{scenario:'delivery'}});
  const second=structuredClone(fixture.delivery);second.machines.find(m=>m.id==='BC-01').name='Fresh delivery record';
  await page.evaluate(({id,d})=>document.querySelector('iframe').contentWindow.postMessage({jsonrpc:'2.0',id,result:{structuredContent:d}},'*'),{id:request.id,d:second});
  await frame.locator('#machineRows').getByText('Fresh delivery record').waitFor();
  assert.equal(await frame.locator('#machineRows').getByText('Changed live record').count(),0);
  await page.goto('file:///'+path.join(root,'datum_visual_lab.html').replace(/\\/g,'/'));
  assert.match(await page.locator('#connectionStatus').innerText(),/Offline snapshot/);
  assert.equal(await page.locator('#machineRows tr').count(),9);
  assert.deepEqual(errors,[]);
  console.log('PASS: empty live startup, host result, scenario tool request, refreshed payload, offline snapshot');
 } finally { await browser.close(); }
})().catch(e=>{console.error(e);process.exitCode=1});
