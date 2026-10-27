// Official ext-apps basic-host integration check, not a browser-only emulation.
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const root=path.resolve(__dirname,'..');
const target=process.env.DATUM_HOST||'http://localhost:8080/';
const output=path.join(root,'screenshots');
(async()=>{
 let browser;
 const pageErrors=[],consoleErrors=[],hostMessages=[];
 try{
  fs.mkdirSync(output,{recursive:true});
  browser=await chromium.launch({headless:true,...(process.env.DATUM_BROWSER?{executablePath:process.env.DATUM_BROWSER}:{})});
  const page=await browser.newPage({viewport:{width:1440,height:1000}});
  page.on('pageerror',e=>pageErrors.push(e.message));
  page.on('console',m=>{if(m.type()==='error')consoleErrors.push(m.text()); if(m.text().includes('Display mode request'))hostMessages.push(m.text())});
  await page.goto(target,{waitUntil:'domcontentloaded'});
  const tool=page.locator('form select').nth(1);
  await page.waitForFunction(()=>Array.from(document.querySelectorAll('select option')).some(o=>o.value==='datum_rendering_probe'),null,{timeout:20000});
  await tool.selectOption('datum_rendering_probe');
  await page.getByRole('button',{name:'Call Tool'}).click();
  let app;
  for(let i=0;i<150;i++){app=page.frames().find(f=>f.url()==='about:blank'&&f.parentFrame());if(app&&await app.locator('#status').count())break;await new Promise(r=>setTimeout(r,100));}
  assert(app,'Reference host application frame missing');
  await app.getByText('Received structured MCP result').waitFor({timeout:20000});
  await app.waitForFunction(()=>document.querySelectorAll('#rows tr').length===2000);
  let measurements=await app.evaluate(()=>({probe:window.probeMetrics,mode:document.querySelector('#mode').textContent,grid:getComputedStyle(document.querySelector('.cards')).gridTemplateColumns, viewportWidth:innerWidth}));
  assert.equal(measurements.probe.rowCount,2000);assert.equal(measurements.probe.svgBars,8);
  assert.equal(await app.locator('#rows tr').count(),2000);
  assert.match(await app.locator('#rows tr').last().innerText(),/Synthetic row 2000/);
  assert(measurements.probe.canvasPixel[3]>0,'Canvas pixel not drawn');
  const before=await page.locator('iframe').first().boundingBox();
  await app.locator('#resize').click();
  await page.waitForFunction(()=>{let f=document.querySelector('iframe');return f&&f.getBoundingClientRect().height>=690},null,{timeout:10000});
  await page.waitForTimeout(400); // basic-host animates its iframe resize over 300 ms
  const after=await page.locator('iframe').first().boundingBox();
  await page.screenshot({path:path.join(output,'rendering-probe-desktop.png'),fullPage:true});
  assert(await app.locator('#fullscreen').isEnabled(),'Host did not advertise fullscreen');
  await app.locator('#fullscreen').click();
  await app.locator('#mode').getByText('Mode: fullscreen',{exact:false}).waitFor({timeout:10000});
  const fullscreen=await app.locator('#mode').innerText();
  await page.screenshot({path:path.join(output,'rendering-probe-fullscreen.png')});
  await app.locator('#inline').click();
  await app.locator('#mode').getByText('Mode: inline',{exact:false}).waitFor({timeout:10000});
  await page.setViewportSize({width:520,height:900});
  await app.waitForFunction(()=>innerWidth<650,null,{timeout:10000});
  const narrow=await app.evaluate(()=>({width:innerWidth,grid:getComputedStyle(document.querySelector('.cards')).gridTemplateColumns,tableScrollWidth:document.querySelector('.table-scroll').scrollWidth,tableClientWidth:document.querySelector('.table-scroll').clientWidth}));
  assert(!narrow.grid.includes(' '),'Responsive layout did not collapse to one column');
  await page.screenshot({path:path.join(output,'rendering-probe-narrow.png'),fullPage:true});
  assert.deepEqual(pageErrors,[]);
  const result={status:'pass',referenceHost:target,viewport:{width:1440,height:1000},measurements,resize:{before:before?.height,requested:700,after:after?.height},fullscreen,narrow,pageErrors,consoleErrors,hostMessages};
  fs.writeFileSync(path.join(output,'rendering-observations.json'),JSON.stringify(result,null,2)+'\n');
  console.log(JSON.stringify(result,null,2));
 }finally{if(browser)await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});



