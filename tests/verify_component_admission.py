"""Run the actual Codex executable against a loopback-only inference recorder.

The only trust state written here belongs to an isolated fixture CODEX_HOME.
No real account, user transcript, or remote inference endpoint is used.
"""
import argparse
import http.server
import json
import os
from pathlib import Path
import queue
import shutil
import sys
import threading
import time
import uuid
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from codex_rpc import Rpc
from guard_core import atomic_json,load_source,LUNA,SOL,TERRA
from live_guard import auth_generation
import hook_manager


class Recorder(http.server.BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_POST(self):
        data=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        self.server.requests.append({'path':self.path,'model':data.get('model')})
        self.send_response(200);self.send_header('Content-Type','text/event-stream');self.send_header('Connection','close');self.end_headers()
        item={'id':'msg_'+uuid.uuid4().hex,'type':'message','role':'assistant','status':'completed',
              'content':[{'type':'output_text','text':'OK','annotations':[]}]}
        response={'id':'resp_'+uuid.uuid4().hex,'object':'response','created_at':int(time.time()),
          'status':'completed','model':data.get('model'),'output':[item],
          'usage':{'input_tokens':1,'output_tokens':1,'total_tokens':2,'input_tokens_details':{'cached_tokens':0},'output_tokens_details':{'reasoning_tokens':0}}}
        events=[('response.created',{'response':{**response,'status':'in_progress','output':[]}}),
          ('response.output_item.added',{'output_index':0,'item':{**item,'status':'in_progress','content':[]}}),
          ('response.output_text.delta',{'item_id':item['id'],'output_index':0,'content_index':0,'delta':'OK'}),
          ('response.output_item.done',{'output_index':0,'item':item}),('response.completed',{'response':response})]
        for i,(kind,payload) in enumerate(events):
            payload.update(type=kind,sequence_number=i)
            self.wfile.write(('event: '+kind+'\ndata: '+json.dumps(payload)+'\n\n').encode())
        self.wfile.flush();self.close_connection=True


def finish(rpc):
    deadline=time.monotonic()+20;events=[]
    while time.monotonic()<deadline:
        try:line=rpc.lines.get(timeout=1)
        except queue.Empty:continue
        if not line:raise AssertionError('fixture backend closed')
        event=json.loads(line);events.append(event)
        if event.get('method')=='turn/completed':return events
    raise AssertionError('fixture turn did not finish')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--codex',type=Path,required=True)
    parser.add_argument('--python-root',type=Path,required=True)
    parser.add_argument('--official-home',type=Path,required=True)
    parser.add_argument('--work',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    work=args.work.resolve()/('admission-'+uuid.uuid4().hex[:10]);work.mkdir(parents=True)
    home=work/'home';home.mkdir();state=work/'state';state.mkdir();payload=work/'payload';payload.mkdir()
    project=Path(__file__).resolve().parents[1]
    for name in ['guard_core.py','codex_rpc.py','live_guard.py','live_hook.py']:
        shutil.copy2(project/name,payload/name)
    shutil.copytree(args.python_root,payload/'python',ignore=shutil.ignore_patterns('__pycache__','*.pyc','test','tests'))
    source,_=load_source(args.official_home)
    atomic_json(home/'models.json',source)
    server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Recorder);server.requests=[]
    threading.Thread(target=server.serve_forever,daemon=True).start()
    os.environ['NO_PROXY']='127.0.0.1,localhost'
    config='model_provider="fixture"\nmodel="gpt-6.1-sol"\nmodel_catalog_json='+json.dumps(str(home/'models.json'))+'\n[model_providers.fixture]\nname="Local admission recorder"\nbase_url="http://127.0.0.1:'+str(server.server_port)+'/v1"\nwire_api="responses"\nrequires_openai_auth=false\nsupports_websockets=false\n'
    (home/'config.toml').write_text(config,encoding='utf-8')
    results=[]
    def snapshot(remaining):
        now=time.time()
        atomic_json(state/'live-quota.json',{'auth_generation':auth_generation(home),'quota':
            {'remaining':remaining,'account':'isolated-fixture','observed_at':now,'resets_at':now+3600}})
    try:
        with Rpc(args.codex,home) as rpc:
            pid=rpc.proc.pid
            started=rpc.call('thread/start',{'cwd':str(home),'model':SOL,'baseInstructions':'Reply OK.',
                'config':{'mcp_servers':{},'features':{'plugins':False}}})
            tid=started['thread']['id']
            def turn(label,remaining,model,expected,override=True):
                snapshot(remaining);before=len(server.requests)
                params={'threadId':tid,'input':[{'type':'text','text':'Fixture message. Reply OK.'}]}
                if override:params['model']=model
                rpc.call('turn/start',params);events=finish(rpc)
                delta=server.requests[before:]
                actual=bool(delta)
                if actual!=expected:raise AssertionError((label,expected,delta,events))
                if actual and any(r['model']!=model for r in delta):raise AssertionError((label,delta))
                if not actual:
                    completed=[e for e in events if e.get('method')=='hook/completed']
                    if not completed:raise AssertionError('no real hook event for rejected request')
                results.append({'case':label,'fixture_remaining':remaining,'selected_model':model,
                    'allowed':actual,'provider_requests':len(delta),'same_live_backend':rpc.proc.pid==pid})
            # This chat exists and has already called the model before hook registration.
            turn('existing_chat_before_install',40,SOL,True)
            command=hook_manager.install(payload,home,state)
            inventory=rpc.call('hooks/list',{'cwds':[str(home)]})
            entries=[h for d in inventory['data'] for h in d['hooks']]
            own=next((h for h in entries if h.get('command')==command),None)
            if own is None:raise AssertionError({'expected_command':command,'inventory':inventory})
            turn('unreviewed_hook_does_not_claim_enforcement',20,SOL,True)
            # Simulate the desktop's exact review operation on this owned fixture only.
            rpc.call('config/batchWrite',{'edits':[{'keyPath':'hooks.state','value':{
                own['key']:{'trusted_hash':own['currentHash']}},'mergeStrategy':'replace'}],
                'reloadUserConfig':True})
            if not hook_manager.status(rpc,command)['trusted']:raise AssertionError('fixture review failed')
            turn('same_existing_chat_full_tier_sol',40,SOL,True)
            turn('same_existing_chat_falls_to_middle_sol_blocked',20,SOL,False,override=False)
            turn('per_turn_override_terra_allowed_in_middle',20,TERRA,True)
            turn('same_existing_chat_falls_to_low_terra_blocked',10,TERRA,False,override=False)
            turn('same_existing_chat_luna_allowed_in_low',10,LUNA,True)
            turn('quota_reset_sol_available_without_restart',80,SOL,True)
            turn('explicit_astra_override_rejected',80,'gpt-6-astra',False)
            turn('thirty_percent_boundary_sol_rejected',30,SOL,False)
            turn('fifteen_percent_boundary_terra_allowed',15,TERRA,True)
            turn('below_fifteen_terra_rejected',14.999,TERRA,False)
            hook_manager.restore(home,state)
            turn('disable_restores_existing_chat_without_restart',10,SOL,True)
            report={'component_test':'real_Codex_app_server_with_loopback_inference_recorder',
              'remote_inference_used':False,'real_credentials_used':False,'backend_restart_count':0,
              'chat_created_before_hook_install':True,'trust_review_simulated_only_in_isolated_home':True,
              'production_hook_code_used':True,'cases':results,'passed':True}
            atomic_json(args.output,report)
            print(json.dumps({'passed':True,'cases':len(results),'backend_restarts':0,
                              'blocked_provider_requests':sum(r['provider_requests'] for r in results if not r['allowed'])}))
    finally:server.shutdown()


if __name__=='__main__':main()
