// Optional handoff check for an already model-created task in a disposable local database.
// The UI interactions are automated by Playwright; no human identity is verified.
const {chromium}=require('playwright');
const {execFileSync}=require('node:child_process');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const root=path.resolve(__dirname,'..');
const taskId=process.env.DATUM_TASK_ID;
const python=process.env.DATUM_PYTHON||'python';
const output=path.join(root,'screenshots');
if(!taskId) throw Error('Set DATUM_TASK_ID to the model-created task in the disposable server DB');
const mcp=(tool,args)=>JSON.parse(execFileSync(python,[path.join(__dirname,'task_protocol_call.py'),tool,JSON.stringify(args)],{cwd:root,encoding:'utf8',timeout:20000}));
(async()=>{
 let browser; const errors=[],consoleErrors=[];
 try {
  const before=mcp('datum_task_get',{task_id:taskId});
  assert.equal(before.created_by,'agent');
  assert.equal(before.task_type,'repair_investigation');
  assert(before.evaluations.length>0,'Model-created task has no evaluation');
  assert.equal(before.parameters.machine_id,'BC-01');
  browser=await chromium.launch({headless:true,...(process.env.DATUM_BROWSER?{executablePath:process.env.DATUM_BROWSER}:{})});
  const page=await browser.newPage({viewport:{width:1440,height:1050}});
  page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(m.type()==='error')consoleErrors.push(m.text())});
  await page.goto(process.env.DATUM_HOST||'http://localhost:8080/');
  const tool=page.locator('select').nth(1);
  await tool.locator('option[value="datum_task_open"]').waitFor({state:'attached',timeout:30000});
  await tool.selectOption('datum_task_open');
  await page.locator('textarea').fill(JSON.stringify({task_id:taskId}));
  await page.getByRole('button',{name:'Call Tool'}).click();
  let frame;
  for(let i=0;i<150;i++){frame=page.frames().find(f=>f.url()==='about:blank'&&f.parentFrame());if(frame&&await frame.locator('[data-source="parameters"]').count())break;await new Promise(r=>setTimeout(r,100))}
  assert(frame,'Application frame missing');
  await frame.locator('#connection').getByText('Task loaded.',{exact:false}).waitFor({timeout:20000});
  assert.match(await frame.locator('[data-source="status"]').innerText(),/blocked/i);
  const form=frame.locator('[data-source="parameters"] form');
  await form.locator('[name="strategy"]').selectOption('delivery');
  await form.locator('[name="allow_substitutes"]').check();
  await form.getByRole('button',{name:'Evaluate'}).click();
  await frame.locator('#connection').getByText('Task loaded.',{exact:false}).waitFor({timeout:20000});
  const afterEvaluation=mcp('datum_task_get',{task_id:taskId});
  assert.equal(afterEvaluation.evaluations.length,before.evaluations.length+1);
  assert.equal(afterEvaluation.parameters.strategy,'delivery');
  assert.equal(afterEvaluation.parameters.allow_substitutes,true);
  assert.equal(afterEvaluation.evaluations.at(-1).initiator,'human');
  const review=frame.locator('[data-source="review"] form');
  await review.locator('[name="decision"]').selectOption('needs_more_information');
  await review.locator('[name="note"]').fill('Automated UI test: verify supporting evidence before an operational decision.');
  await review.getByRole('button',{name:'Record review'}).click();
  await frame.locator('#connection').getByText('Task loaded.',{exact:false}).waitFor({timeout:20000});
  const afterReview=mcp('datum_task_get',{task_id:taskId});
  assert.equal(afterReview.reviews.length,before.reviews.length+1);
  assert.equal(afterReview.reviews.at(-1).evaluation_id,afterEvaluation.evaluations.at(-1).evaluation_id);
  assert.equal(afterReview.reviews.at(-1).decision,'needs_more_information');
  fs.mkdirSync(output,{recursive:true});
  await frame.locator('[data-source="reviews"]').scrollIntoViewIfNeeded();
  await page.screenshot({path:path.join(output,'task-model-handoff.png'),fullPage:true});
  assert.deepEqual(errors,[]);
  console.log(JSON.stringify({status:'pass',taskId,priorEvaluations:before.evaluations.length,afterEvaluations:afterReview.evaluations.length,reviewId:afterReview.reviews.at(-1).review_id,initiatorsAreUnverified:true,automatedHumanInterface:true,errors,consoleErrors},null,2));
 }finally{if(browser)await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
