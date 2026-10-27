// Integration test against the official ext-apps basic-host and a live Datum server.
// The test temporarily changes one synthetic fixture and restores its exact bytes.
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {execFileSync}=require('node:child_process');
const root=path.resolve(__dirname,'..');
const target=process.env.DATUM_HOST||'http://localhost:8080/';
const python=process.env.DATUM_PYTHON||'python';
const fixturePath=path.join(root,'fixtures','machines.csv');
const screenshotDir=path.join(root,'screenshots');
const original=fs.readFileSync(fixturePath);
const evaluate=scenario=>JSON.parse(execFileSync(python,['-B','-c',`import json; from datum_engine import evaluate; print(json.dumps(evaluate('${scenario}')))`],{cwd:root,encoding:'utf8'}));
(async()=>{
 let browser;
 const errors=[],consoleErrors=[],httpErrors=[];
 try {
  fs.mkdirSync(screenshotDir,{recursive:true});
  browser=await chromium.launch({headless:true,...(process.env.DATUM_BROWSER?{executablePath:process.env.DATUM_BROWSER}:{})});
  const page=await browser.newPage({viewport:{width:1600,height:1000}});
  page.on('pageerror',e=>errors.push(e.message));
  page.on('response',r=>{if(r.status()>=400)httpErrors.push({url:r.url(),status:r.status()})});
  page.on('console',m=>{if(m.type()==='error')consoleErrors.push(m.text())});
  await page.addInitScript(()=>{window.__datumMessages=[];window.addEventListener('message',e=>window.__datumMessages.push(e.data))});
  await page.goto(target);
  await page.locator('textarea').waitFor({timeout:30000});
  await page.getByRole('button',{name:'Call Tool'}).click();
  await page.waitForFunction(()=>Array.from(document.querySelectorAll('iframe')).length>0);
  let app;
  for(let i=0;i<100;i++){
   app=page.frames().find(f=>f.url()==='about:blank'&&f.parentFrame());
   if(app&&await app.locator('#connectionStatus').count())break;
   await new Promise(r=>setTimeout(r,100));
  }
  assert(app,'MCP application iframe not found');
  await page.getByText('Tool Result',{exact:false}).click();
  const initial=JSON.parse(await page.getByText('Tool Result',{exact:false}).locator('xpath=../..').locator('pre').innerText()).structuredContent;
  await app.evaluate(()=>{window.__datumMessages=[];window.addEventListener('message',e=>window.__datumMessages.push(e.data))});
  async function check(scenario,first=false){
   const expected=evaluate(scenario);
   await app.locator('#connectionStatus').getByText(expected.receipt.run_id,{exact:false}).waitFor({timeout:15000});
   const rows=await app.locator('#machineRows tr').allTextContents();
   assert.equal(rows.length,expected.machines.length);
   for(const m of expected.machines){
    const text=await app.locator(`[data-mid="${m.id}"]`).innerText();
    assert(text.includes(m.name)&&text.includes(m.site)&&text.includes(`P${m.priority}`)&&text.toLowerCase().includes(m.status),`Mismatch ${m.id}: ${text}`);
   }
   const metrics=await app.locator('#metrics .big').allTextContents();
   assert.deepEqual(metrics.map(Number),[expected.counts.ready,expected.counts.blocked,expected.counts.review,expected.machines.length]);
   const messages=await app.evaluate(()=>window.__datumMessages);
   const payloads=messages.flatMap(m=>[m?.params?.structuredContent,m?.result?.structuredContent]).filter(Boolean);
   if(first)assert.deepEqual(initial,expected);
   else assert(payloads.some(p=>JSON.stringify(p)===JSON.stringify(expected)),`No exact structured result observed for ${scenario}`);
   return expected;
  }
  async function change(scenario){await app.locator('#scenarioPicker').selectOption(scenario);await check(scenario)}
  await check('baseline',true);
  await page.screenshot({path:path.join(screenshotDir,'reference-host-baseline.png')});
  await app.locator('[data-view="graph"]').click();
  const graph=app.locator('#evidenceGraph');
  const viewBefore=await graph.getAttribute('viewBox');
  await app.locator('#zoomIn').click();
  assert.notEqual(await graph.getAttribute('viewBox'),viewBefore);
  await app.locator('#evidenceGraph [data-node="part:PL-40"]').click();
  assert.match(await app.locator('#nodeDetails').innerText(),/PL-40/);
  await page.screenshot({path:path.join(screenshotDir,'reference-host-graph.png')});
  await app.locator('[data-view="overview"]').click();
  await change('delivery');
  assert.match(await app.locator('[data-mid="CR-01"]').innerText(),/Ready/);
  assert.match(await app.locator('[data-mid="PK-01"]').innerText(),/Blocked/);
  await change('quarantine');
  await app.locator('[data-view="claims"]').click();
  assert.match(await app.locator('#quarantinePanel').innerText(),/1\?/);
  assert.equal(await app.locator('#claimCards .claim-card').count(),2);
  await page.screenshot({path:path.join(screenshotDir,'reference-host-quarantine.png')});
  // Change source bytes and ask the existing app to call the server; no HTML rebuild.
  const changed=original.toString('utf8').replace('Belt conveyor','LIVE TEST conveyor');
  assert.notEqual(changed,original.toString('utf8'));
  fs.writeFileSync(fixturePath,changed,'utf8');
  await app.locator('[data-view="overview"]').click();
  await change('baseline');
  assert.match(await app.locator('[data-mid="BC-01"]').innerText(),/LIVE TEST conveyor/);
  await page.screenshot({path:path.join(screenshotDir,'reference-host-changed-record.png')});
  assert.deepEqual(errors,[]);
  console.log(JSON.stringify({status:'pass',scenarios:['baseline','delivery','quarantine'],checks:['exact live structured payload against Python evaluation','all table rows and counts','graph zoom and node selection','claims and quarantine','changed CSV without rebuilding HTML'],pageErrors:errors,consoleErrors,httpErrors,screenshots:screenshotDir},null,2));
 } finally {
  fs.writeFileSync(fixturePath,original);
  if(browser)await browser.close();
 }
})().catch(e=>{console.error(e);process.exitCode=1});
