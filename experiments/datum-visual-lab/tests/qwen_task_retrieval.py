"""Local single-tool Qwen retrieval probe for one explicitly authorized task."""
import argparse,asyncio,json
from pathlib import Path
import httpx2 as httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--task-id',required=True,help='Only this local task may be retrieved; retrieval records a local audit event')
parser.add_argument('--output',required=True,type=Path,help='New transcript file; an existing file is not overwritten')
args=parser.parse_args()
TASK_ID=args.task_id
OUT=args.output
if OUT.exists(): parser.error('Output file already exists')
OUT.parent.mkdir(parents=True,exist_ok=True)
trace={'model':'qwen3.5:9b','task_id':TASK_ID,'status':'starting','messages':[],'calls':[]}
def save(): OUT.write_text(json.dumps(trace,ensure_ascii=False,indent=2),encoding='utf-8')
async def main():
  try:
    async with httpx.AsyncClient(timeout=180,trust_env=False) as http:
      model=next((m for m in (await http.get('http://127.0.0.1:11434/api/tags')).json()['models'] if m.get('name')=='qwen3.5:9b'),None)
      if not model or model.get('remote_host') or model.get('remote_model'): raise RuntimeError('Local Qwen model not available')
      trace['model_digest']=model.get('digest')
      async with streamable_http_client('http://127.0.0.1:8000/mcp') as transport:
       async with ClientSession(transport[0],transport[1]) as session:
        init=await session.initialize();trace['mcp_protocol_version']=init.protocol_version
        tool=next(t for t in (await session.list_tools()).tools if t.name=='datum_task_get')
        schemas=[{'type':'function','function':{'name':tool.name,'description':tool.description or '', 'parameters':tool.input_schema}}]
        messages=[{'role':'system','content':'Use the supplied MCP tool to retrieve the requested synthetic task. State only evidence contained in the tool result. Human labels are unverified, a synthetic review is not authorization, and stock readiness does not prove real-world repairability.'}, {'role':'user','content':f'Retrieve task {TASK_ID} and report its current parameters, evaluations, and latest human-labelled review.'}]
        trace['messages']=messages;trace['status']='running';save()
        for turn in range(3):
         response=await http.post('http://127.0.0.1:11434/api/chat',json={'model':'qwen3.5:9b','messages':messages,'tools':schemas,'stream':False,'think':False,'options':{'temperature':0,'num_predict':1024}})
         response.raise_for_status();message=response.json()['message'];messages.append(message);save()
         calls=message.get('tool_calls') or []
         if not calls: trace['status']='model_stopped';break
         if len(trace['calls'])+len(calls)>3: trace['status']='call_limit_reached';break
         for call in calls:
          f=call.get('function',{}); name=f.get('name'); arguments=f.get('arguments')
          if isinstance(arguments,str):
           try: arguments=json.loads(arguments)
           except json.JSONDecodeError: arguments=None
          if name!='datum_task_get' or arguments!={'task_id':TASK_ID}:
           payload={'isError':True,'error':'Rejected: only datum_task_get for the authorized task is allowed'}
          else:
           result=await session.call_tool(name,arguments);payload=result.model_dump(by_alias=True,mode='json',exclude_none=True)
          trace['calls'].append({'name':name,'arguments':arguments,'result':payload})
          messages.append({'role':'tool','tool_name':name or 'unknown','content':json.dumps(payload,ensure_ascii=False)})
          save()
        else: trace['status']='turn_limit_reached'
  except Exception as exc: trace['status']='error';trace['error']=f'{type(exc).__name__}: {exc}'
  save()
  print(json.dumps({'status':trace['status'],'calls':[(x['name'],x['result'].get('isError')) for x in trace['calls']], 'error':trace.get('error'),'transcript':str(OUT)},ensure_ascii=False))
asyncio.run(main())
