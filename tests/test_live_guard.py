import concurrent.futures
import json
from pathlib import Path
import tempfile
import time
import unittest
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from guard_core import LUNA,SOL,TERRA,FUTURE_SOL,atomic_json
from live_guard import decide,current_quota,check,auth_generation
import hook_manager


class AdmissionTests(unittest.TestCase):
    def event(self,model):return {'hook_event_name':'UserPromptSubmit','model':model,'prompt':'private prompt never logged'}
    def test_thresholds_are_enforced_on_actual_model(self):
        for remaining,allowed in [(40,[LUNA,SOL,TERRA,FUTURE_SOL]),(30,[LUNA,TERRA]),(15,[LUNA,TERRA]),(14.999,[LUNA]),(None,[LUNA])]:
            for model in [LUNA,SOL,TERRA,FUTURE_SOL,'gpt-6-astra','unknown']:
                with self.subTest(remaining=remaining,model=model):
                    d=decide(self.event(model),{'remaining':remaining})
                    self.assertEqual(d['allowed'],model in allowed)
                    self.assertEqual(d['output'].get('decision')=='block',model not in allowed)
    def test_missing_or_wrong_event_blocks(self):
        for e in [{},{'model':LUNA},{'hook_event_name':'UserPromptSubmit'}, {'hook_event_name':'PreModelRequest','model':LUNA}]:
            self.assertFalse(decide(e,{'remaining':80})['allowed'])
    def test_internal_safety_review_is_retained(self):
        e=self.event('codex-auto-review')
        self.assertFalse(decide(e,{'remaining':10})['allowed'])
        e['agent_type']='auto_review'
        self.assertTrue(decide(e,{'remaining':10})['allowed'])
    def test_failed_query_allows_only_luna_and_cools_down(self):
        with tempfile.TemporaryDirectory() as t:
            home=Path(t)/'home';home.mkdir();state=Path(t)/'state';calls=[]
            def fail(home):calls.append(home);raise OSError()
            a=check(self.event(SOL),home,state,fail)
            b=check(self.event(LUNA),home,state,fail)
            self.assertEqual(a['decision'],'block');self.assertEqual(b,{})
            self.assertEqual(len(calls),1)
            receipt=json.loads((state/'last-admission.json').read_text())
            self.assertNotIn('prompt',receipt);self.assertNotIn('private prompt',json.dumps(receipt))
    def test_disable_is_immediate_and_does_not_query(self):
        with tempfile.TemporaryDirectory() as t:
            state=Path(t);(state/'live-disabled.flag').write_text('disabled')
            def never(_):raise AssertionError('must not query while disabled')
            self.assertEqual(check(self.event(SOL),state,state,never),{})
    def test_cache_is_no_more_than_five_seconds(self):
        with tempfile.TemporaryDirectory() as t:
            home=Path(t)/'home';home.mkdir();state=Path(t)/'state';calls=[]
            def probe(home):calls.append(home);return {'remaining':40,'account':'fixture','observed_at':1000,'resets_at':2000}
            self.assertEqual(current_quota(home,state,probe,lambda:1000)[1],'official_pre_submit_query')
            self.assertEqual(current_quota(home,state,probe,lambda:1005)[1],'fresh_shared_cache')
            current_quota(home,state,probe,lambda:1005.001)
            self.assertEqual(len(calls),2)
    def test_login_change_and_reset_discard_old_quota(self):
        with tempfile.TemporaryDirectory() as t:
            home=Path(t)/'home';home.mkdir();state=Path(t)/'state'
            auth=home/'auth.json';auth.write_text('{}')
            atomic_json(state/'live-quota.json',{'auth_generation':auth_generation(home),'quota':{'remaining':90,'account':'A','observed_at':1000,'resets_at':2000}})
            auth.write_text('{"fixture":true}')
            self.assertIsNone(current_quota(home,state,lambda _:None,lambda:1001)[0])
            atomic_json(state/'live-quota.json',{'auth_generation':auth_generation(home),'quota':{'remaining':90,'account':'A','observed_at':1000,'resets_at':1001}})
            self.assertIsNone(current_quota(home,state,lambda _:None,lambda:1001)[0])
    def test_parallel_chats_share_one_query(self):
        with tempfile.TemporaryDirectory() as t:
            home=Path(t)/'home';home.mkdir();state=Path(t)/'state';calls=[]
            def probe(_):
                calls.append(1);time.sleep(.1)
                return {'remaining':40,'account':'fixture','observed_at':time.time(),'resets_at':time.time()+1000}
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
                values=list(pool.map(lambda _:current_quota(home,state,probe)[0]['remaining'],range(4)))
            self.assertEqual(values,[40]*4);self.assertEqual(len(calls),1)


class HookRegistrationTests(unittest.TestCase):
    def test_merge_idempotence_restore_and_no_silent_trust(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t)/'app';home=Path(t)/'home';home.mkdir();state=Path(t)/'state'
            other={'hooks':[{'type':'command','command':'existing-user-hook'}]}
            atomic_json(home/'hooks.json',{'description':'retain','hooks':{'UserPromptSubmit':[other]}})
            command=hook_manager.install(root,home,state)
            hook_manager.install(root,home,state)
            data=json.loads((home/'hooks.json').read_text())
            self.assertEqual(len(data['hooks']['UserPromptSubmit']),2)
            self.assertEqual(data['description'],'retain')
            self.assertNotIn('trusted_hash',json.dumps(data))
            self.assertNotIn('bypass',command)
            hook_manager.restore(home,state)
            self.assertEqual(json.loads((home/'hooks.json').read_text())['hooks']['UserPromptSubmit'],[other])
    def test_powershell_paths_are_literal(self):
        s=hook_manager.ps_quote("C:\\O'Brien\\$user`name")
        self.assertEqual(s,"'C:\\O''Brien\\$user`name'")


if __name__=='__main__':unittest.main()
