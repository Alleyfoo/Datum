// Run against the official basic-host and this directory's server; no LLM is involved.
// Temporarily modifies the synthetic menu configuration and always restores its bytes.
const {chromium}=require('playwright');
const fs=require('node:fs');
const path=require('node:path');
const assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..');
const configPath=path.join(root,'interaction_menu.json');
const original=fs.readFileSync(configPath);
const screenshotDir=path.join(root,'screenshots');
(async()=>{
 let browser;
 const pageErrors=[], consoleErrors=[];
 try {
  browser=await chromium.launch({headless:true,...(process.env.DATUM_BROWSER?{executablePath:process.env.DATUM_BROWSER}:{})});
  const page=await browser.newPage({viewport:{width:1400,height:950}});
  page.on('pageerror',e=>pageErrors.push(e.message));
  page.on('console',m=>{if(m.type()==='error')consoleErrors.push(m.text())});
  await page.goto(process.env.DATUM_HOST||'http://localhost:8080/');
  const tool=page.locator('select').nth(1);
  await tool.locator('option[value="datum_open_interaction_lab"]').waitFor({state:'attached',timeout:30000});
  const options=await tool.locator('option').allTextContents();
  assert(!options.includes('datum_menu_action')&&!options.includes('datum_menu_refresh'),'app-only tools appeared in host tool selector');
  await tool.selectOption('datum_open_interaction_lab');
  await page.getByRole('button',{name:'Call Tool'}).click();
  let app;
  for(let i=0;i<150;i++){app=page.frames().find(f=>f.url()==='about:blank'&&f.parentFrame());if(app&&await app.locator('#menu [data-action]').count())break;await new Promise(r=>setTimeout(r,100))}
  assert(app,'No interaction app iframe');
  await app.getByText('Menu received from the server.',{exact:false}).waitFor({timeout:15000});
  assert.equal(await app.locator('#menu [data-action]').count(),3);
  assert(await app.locator('[data-action="locked"]').isDisabled());
  await app.locator('[data-action="sources"]').click();
  await app.getByText('Received server result for Inspect sources.').waitFor({timeout:15000});
  assert.match(await app.locator('#resultDetails').innerText(),/Source A: synthetic record/);
  fs.mkdirSync(screenshotDir,{recursive:true});
  await page.screenshot({path:path.join(screenshotDir,'interaction-menu.png')});
  const changed=JSON.parse(original.toString('utf8').replace(/^\uFEFF/,''));
  changed.actions.push({id:'new_example',label:'Added on server',enabled:true,result:{heading:'Fresh result',details:['Changed configuration served live']}});
  fs.writeFileSync(configPath,JSON.stringify(changed,null,2)+'\n','utf8');
  await app.locator('#refresh').click();
  await app.locator('[data-action="new_example"]').waitFor({timeout:15000});
  await app.locator('[data-action="new_example"]').click();
  await app.getByText('Received server result for Added on server.').waitFor({timeout:15000});
  assert.equal(await app.locator('#resultHeading').innerText(),'Fresh result');
  assert.match(await app.locator('#resultDetails').innerText(),/Changed configuration served live/);
  await page.screenshot({path:path.join(screenshotDir,'interaction-menu-changed.png')});
  assert.deepEqual(pageErrors,[]);
  console.log(JSON.stringify({status:'pass',checks:['model-facing tool opens app','app-only tools hidden by host selector','disabled action disabled','enabled action calls server and renders structured result','config change visible after app-only refresh without HTML rebuild'],pageErrors,consoleErrors},null,2));
 }finally {fs.writeFileSync(configPath,original);if(browser)await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});

