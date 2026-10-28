// Browser-only renderer test: simulated host messages, no MCP or task database.
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const root=path.resolve(__dirname,'..');
const html=fs.readFileSync(path.join(root,'task_interface.html'),'utf8');
(async()=>{
 const browser=await chromium.launch({headless:true,...(process.env.DATUM_BROWSER?{executablePath:process.env.DATUM_BROWSER}:{})});
 try{
  const page=await browser.newPage();
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.setContent('<iframe id="app" style="width:1000px;height:700px"></iframe>');
  await page.evaluate(source=>{
    window.messages=[];window.addEventListener('message',e=>window.messages.push(e.data));
    document.querySelector('#app').srcdoc=source;
  },html);
  await page.waitForFunction(()=>window.messages.some(m=>m.method==='ui/initialize'));
  await page.evaluate(()=>document.querySelector('#app').contentWindow.postMessage({jsonrpc:'2.0',id:1300,result:{protocolVersion:'2026-01-26',hostCapabilities:{serverTools:{}}}},'*'));
  await page.waitForFunction(()=>window.messages.some(m=>m.method==='ui/notifications/initialized'));
  const descriptor={schema_version:'datum-task-ui-v1',task_id:'task-mock',task_type:'repair_investigation',title:'Browser-only mock',components:[
    {type:'evidence_graph',title:'Evidence',source:'graph'},
    {type:'parameter_form',title:'Unavailable source',source:'parameters'}],data:{
    graph:{nodes:[{id:'part-0',label:'PL-40',detail:'Required 1; stock.csv:2'}],edges:[]},
    parameters:{fields:[{name:'machine_id',label:'Machine',type:'text',value:'BC-01'}],action:{tool:'datum_task_ui_evaluate',label:'Evaluate',arguments:{task_id:'task-mock'},enabled:false,disabled_reason:'Current source is unavailable.'}}}};
  await page.evaluate(data=>document.querySelector('#app').contentWindow.postMessage({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:{structuredContent:data}},'*'),descriptor);
  const frame=page.frameLocator('#app');
  await frame.locator('[data-node="part-0"]').click();
  assert.match(await frame.locator('.graphdetail').innerText(),/PL-40.*stock\.csv:2/);
  assert(await frame.getByRole('button',{name:'Evaluate'}).isDisabled());
  assert.match(await frame.locator('[data-source="parameters"]').innerText(),/Current source is unavailable/);
  assert.deepEqual(errors,[]);
  console.log('PASS: browser-only mocked bridge; graph node inspection and unavailable-source disabled action');
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
