// Official basic-host test; server must use a disposable DATUM_TASK_DB.
// Uses MCP client helper for agent-facing calls, not an autonomous AI agent.
const {chromium}=require('playwright');
const {execFileSync}=require('node:child_process');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const root=path.resolve(__dirname,'..');
const python=process.env.DATUM_PYTHON||'python';
const output=path.join(root,'screenshots');
const mcp=(tool,args)=>JSON.parse(execFileSync(python,[path.join(__dirname,'task_protocol_call.py'),tool,JSON.stringify(args)],{cwd:root,encoding:'utf8',timeout:20000}));
const params={machine_id:'BC-01',strategy:'baseline',allow_substitutes:false};
async function openTask(page,taskId){
 await page.goto(process.env.DATUM_HOST||'http://localhost:8080/');
 const tool=page.locator('select').nth(1);
 await tool.locator('option[value="datum_task_open"]').waitFor({state:'attached',timeout:30000});
 await tool.selectOption('datum_task_open');
 await page.locator('textarea').fill(JSON.stringify({task_id:taskId}));
 await page.getByRole('button',{name:'Call Tool'}).click();
 let frame;
 for(let i=0;i<150;i++){frame=page.frames().find(f=>f.url()==='about:blank'&&f.parentFrame());if(frame&&await frame.locator('[data-component]').count())break;await new Promise(r=>setTimeout(r,100))}
 assert(frame,'App frame missing');
 await frame.locator('#connection').getByText('Task loaded.',{exact:false}).waitFor({timeout:20000});
 return frame;
}
async function waitForUpdate(frame){await frame.locator('#connection').getByText('Task loaded.',{exact:false}).waitFor({timeout:20000})}
(async()=>{
 let browser;const errors=[],consoleErrors=[];
 try{
  const created=mcp('datum_task_create',{task_type:'repair_investigation',...params,recommendation:'Inspect the source records before reaching a conclusion.',next_steps:['Compare a hypothetical delivery','Seek human review']});
  const tid=created.task_id;
  mcp('datum_task_evaluate',{task_id:tid,...params});
  fs.mkdirSync(output,{recursive:true});
  browser=await chromium.launch({headless:true,...(process.env.DATUM_BROWSER?{executablePath:process.env.DATUM_BROWSER}:{})});
  const page=await browser.newPage({viewport:{width:1440,height:1050}});
  page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(m.type()==='error')consoleErrors.push(m.text())});
  let frame=await openTask(page,tid);
  assert.match(await frame.locator('#title').innerText(),/Repair readiness/);
  assert.equal(await frame.locator('[data-component="evidence_graph"]').count(),1);
  assert.match(await frame.locator('[data-source="status"]').innerText(),/Inspect the source records/);
  assert.match(await frame.locator('[data-source="requirements"]').innerText(),/BC-01|PL-40/);
  await page.screenshot({path:path.join(output,'task-repair.png'),fullPage:true});
  await frame.locator('[data-source="evidence_graph"]').scrollIntoViewIfNeeded();
  await frame.locator('[data-source="evidence_graph"] [data-node="part-0"]').click();
  assert.match(await frame.locator('[data-source="evidence_graph"] .graphdetail').innerText(),/PL-40.*stock\.csv:2/);
  await page.screenshot({path:path.join(output,'task-repair-graph.png'),fullPage:true});
  const form=frame.locator('[data-source="parameters"] form');
  await form.getByRole('button',{name:'Evaluate'}).click();
  await waitForUpdate(frame);
  let task=mcp('datum_task_get',{task_id:tid});
  assert.equal(task.evaluations.length,2);
  assert.deepEqual(task.evaluations[0].result,task.evaluations[1].result,'Identical parameters and sources must yield identical result');
  assert.equal(task.evaluations[0].initiator,'agent');assert.equal(task.evaluations[1].initiator,'human');
  await form.locator('[name="strategy"]').selectOption('delivery');
  await form.locator('[name="allow_substitutes"]').check();
  await form.getByRole('button',{name:'Evaluate'}).click();
  await waitForUpdate(frame);
  task=mcp('datum_task_get',{task_id:tid});
  assert.equal(task.evaluations.length,3);assert.equal(task.parameters.strategy,'delivery');assert.equal(task.parameters.allow_substitutes,true);
  assert.deepEqual(task.evaluations[2].result.parameters,task.parameters);
  const review=frame.locator('[data-source="review"] form');
  await review.locator('[name="decision"]').selectOption('needs_more_information');
  await review.locator('[name="note"]').fill('Check source claims before any operational decision.');
  await review.getByRole('button',{name:'Record review'}).click();
  await waitForUpdate(frame);
  task=mcp('datum_task_get',{task_id:tid});
  assert.equal(task.reviews.length,1);assert.equal(task.reviews[0].evaluation_id,task.evaluations[2].evaluation_id);
  assert.match(task.reviews[0].note,/Check source claims/);
  assert(task.events.some(e=>e.event_type==='parameter_changed'));assert(task.events.some(e=>e.event_type==='human_review_recorded'));
  await frame.locator('[data-source="reviews"]').scrollIntoViewIfNeeded();
  await page.screenshot({path:path.join(output,'task-human-review.png'),fullPage:true});
  // An agent records a newer evaluation while the app still shows the previous
  // one. The stale review must fail rather than attach to the new evidence.
  mcp('datum_task_evaluate',{task_id:tid,machine_id:'BC-01',strategy:'delivery',allow_substitutes:true});
  await review.locator('[name="note"]').fill('This review is based on stale evidence.');
  await review.getByRole('button',{name:'Record review'}).click();
  await frame.locator('#connection').getByText('Request failed:',{exact:false}).waitFor({timeout:15000});
  assert.match(await frame.locator('#connection').innerText(),/Evaluation changed/);
  task=mcp('datum_task_get',{task_id:tid});
  assert.equal(task.evaluations.length,4);assert.equal(task.reviews.length,1);
  await page.getByTitle('Close',{exact:true}).first().click();
  await page.getByTitle('Close',{exact:true}).first().waitFor({state:'detached',timeout:10000});
  await page.locator('textarea').fill(JSON.stringify({task_id:tid}));
  await page.getByRole('button',{name:'Call Tool'}).click();
  for(let i=0;i<150;i++){frame=page.frames().find(f=>f.url()==='about:blank'&&f.parentFrame());if(frame&&await frame.locator('[data-source="reviews"]').count())break;await new Promise(r=>setTimeout(r,100))}
  assert.match(await frame.locator('[data-source="reviews"]').innerText(),/Check source claims/);
  assert.equal(await frame.locator('[data-source="history"] tbody tr').count(),4);
  assert.equal(await frame.locator('[name="strategy"]').inputValue(),'delivery');
  assert.equal(await frame.locator('[name="allow_substitutes"]').isChecked(),true);
  task=mcp('datum_task_get',{task_id:tid});assert(task.events.some(e=>e.event_type==='task_reopened'));
  const conflict=mcp('datum_task_create',{task_type:'supplier_conflict_review',part_id:'CP-09-ALT'});
  mcp('datum_task_evaluate',{task_id:conflict.task_id,part_id:'CP-09-ALT'});
  const page2=await browser.newPage({viewport:{width:1440,height:1050}});page2.on('pageerror',e=>errors.push(e.message));page2.on('console',m=>{if(m.type()==='error')consoleErrors.push(m.text())});
  const app2=await openTask(page2,conflict.task_id);
  assert.match(await app2.locator('#title').innerText(),/Supplier record conflict/);
  assert.equal(await app2.locator('[data-component="evidence_graph"]').count(),0);
  assert.equal(await app2.locator('[data-source="claims"] tbody tr').count(),2);
  assert.match(await app2.locator('[data-source="claims"]').innerText(),/Not compatible/);
  assert.equal(await app2.locator('title').innerText(),await frame.locator('title').innerText(),'Both tasks use same renderer');
  await app2.locator('[data-source="claims"]').scrollIntoViewIfNeeded();
  await page2.screenshot({path:path.join(output,'task-supplier-conflict.png'),fullPage:true});
  assert.deepEqual(errors,[]);
  console.log(JSON.stringify({status:'pass',checks:['agent MCP create and evaluate','graph node source inspection','same source and parameters equal in agent and GUI','GUI changes parameters and app-only rerun','local review linked to evaluation','stale review rejected','agent retrieves changed state','close and reopen retains history','two task types use same generic renderer'],taskId:tid,errors,consoleErrors},null,2));
 }finally{if(browser)await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
