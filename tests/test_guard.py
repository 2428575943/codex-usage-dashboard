import base64
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import tomllib
import unittest
from unittest.mock import patch
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from guard_core import *
import updater


def source():
    return {'models': [{'slug': m, 'visibility': 'list', 'default_reasoning_level': 'xhigh',
         'base_instructions': 'retain vendor instructions', 'upgrade': 'gpt-6-astra',
         'supported_reasoning_levels': [{'effort': e, 'description': e} for e in ['low','medium','high','xhigh','max','ultra']]}
         for m in [LUNA,TERRA,SOL,FUTURE_SOL,'gpt-6-astra']]}


class PolicyTests(unittest.TestCase):
    def test_exact_boundaries_and_neighbors(self):
        for value, tier, count in [(100,'full',4),(30.00001,'full',4),(30,'balanced',2),
                  (15.00001,'balanced',2),(15,'balanced',2),(14.99999,'save',1),(0,'save',1),(None,'unknown',1)]:
            with self.subTest(value=value):
                c,t,visible=filtered_catalog(source(),value)
                self.assertEqual((t,len(visible)),(tier,count))
                for m in c['models']:
                    self.assertEqual({r['effort'] for r in m['supported_reasoning_levels']},set(EFFORTS))
                    self.assertIsNone(m['upgrade'])

    def test_invalid_percent(self):
        for v in [-1,101,float('nan'),float('inf'),True,'30']:
            with self.subTest(v=v),self.assertRaises(ValueError):policy(v)

    def test_unreleased_not_fabricated(self):
        s=source();s['models']=[m for m in s['models'] if m['slug']!=FUTURE_SOL]
        self.assertNotIn(FUTURE_SOL,filtered_catalog(s,80)[2])

    def test_source_is_unchanged(self):
        s=source();original=copy.deepcopy(s);filtered_catalog(s,5);self.assertEqual(s,original)

    def test_missing_luna_rejected(self):
        s=source();s['models']=s['models'][1:]
        with self.assertRaises(ValueError):filtered_catalog(s,None)

    def test_effort_schema_change_rejected(self):
        s=source();s['models'][0]['supported_reasoning_levels']=[]
        with self.assertRaises(ValueError):filtered_catalog(s,10)


class QuotaTests(unittest.TestCase):
    def q(self,**kw):
        d={'usedPercent':70,'windowDurationMins':300,'resetsAt':2000};d.update(kw)
        return {'rateLimitsByLimitId':{'codex':{'primary':d}}}
    def test_server_used_is_converted_to_remaining(self):
        self.assertEqual(quota_from_result(self.q(),'A',1000)['remaining'],30)
    def test_weekly_or_other_bucket_not_used_as_five_hours(self):
        self.assertIsNone(quota_from_result(self.q(windowDurationMins=10080),'A',1000))
        q=self.q();q['rateLimitsByLimitId']['codex_other']=q['rateLimitsByLimitId'].pop('codex')
        self.assertIsNone(quota_from_result(q,'A',1000))
    def test_expired_and_invalid_server_data(self):
        for kw in [{'usedPercent':float('nan')},{'usedPercent':101},{'usedPercent':True},{'resetsAt':999}]:
            self.assertIsNone(quota_from_result(self.q(**kw),'A',1000))
    def test_login_switch_and_staleness(self):
        q=quota_from_result(self.q(),'A',1000)
        self.assertEqual(valid_quota(q,'A',1050),30)
        self.assertIsNone(valid_quota(q,'B',1050))
        self.assertIsNone(valid_quota(q,'A',1601))
        self.assertIsNone(valid_quota(q,'A',999))


class ConfigTests(unittest.TestCase):
    def test_retains_unrelated_sections_and_comments(self):
        text='# heading\r\nmodel = "gpt-6-astra"\r\n[mcp_servers.test]\r\ncommand = "keep"\r\n[desktop]\r\nlocale = "zh-CN"\r\nenabled-reasoning-efforts = ["max"]\r\n[projects."D:/my project"]\r\ntrust_level = "trusted"\r\n'
        updated=edit_config(text,{'model':'gpt-6-luna','model_catalog_json':'C:\\A B\\m.json',
                        'desktop.enabled-reasoning-efforts':list(EFFORTS)})
        parsed=tomllib.loads(updated)
        self.assertEqual(parsed['mcp_servers']['test']['command'],'keep')
        self.assertEqual(parsed['projects']['D:/my project']['trust_level'],'trusted')
        self.assertIn('# heading\r\n',updated)
        self.assertEqual(parsed['model_catalog_json'],'C:\\A B\\m.json')
    def test_roundtrip_apply_restore_and_external_edits(self):
        with tempfile.TemporaryDirectory() as d:
            home=Path(d)/'home';home.mkdir();state=Path(d)/'state'
            original='model = "gpt-6-astra"\nmodel_reasoning_effort = "max"\n[desktop]\nlocale = "zh-CN"\n'
            p=home/'config.toml';p.write_text(original,encoding='utf-8')
            manager=ConfigManager(home,state);c,t,v=filtered_catalog(source(),10)
            self.assertTrue(manager.apply(c,v));self.assertFalse(manager.apply(c,v))
            p.write_text(p.read_text().replace('locale = "zh-CN"','locale = "en-US"'),encoding='utf-8')
            result=manager.restore();parsed=tomllib.loads(p.read_text())
            self.assertEqual(parsed['model'],'gpt-6-astra');self.assertEqual(parsed['desktop']['locale'],'en-US')
            self.assertNotIn('model_catalog_json',parsed);self.assertEqual(result['preserved_user_changes'],[])
    def test_restore_retains_user_changed_managed_value(self):
        with tempfile.TemporaryDirectory() as d:
            home=Path(d)/'home';home.mkdir();state=Path(d)/'state'
            p=home/'config.toml';p.write_text('model="gpt-6-astra"\n',encoding='utf-8')
            m=ConfigManager(home,state);c,t,v=filtered_catalog(source(),10);m.apply(c,v)
            p.write_text(p.read_text().replace('model = "gpt-6-luna"','model = "user-choice"'),encoding='utf-8')
            result=m.restore();self.assertIn('model',result['preserved_user_changes'])
            self.assertEqual(tomllib.loads(p.read_text())['model'],'user-choice')
    def test_existing_third_party_catalog_not_overwritten(self):
        with tempfile.TemporaryDirectory() as d:
            home=Path(d);p=home/'config.toml';p.write_text('model_catalog_json="other.json"\n',encoding='utf-8')
            c,t,v=filtered_catalog(source(),10)
            with self.assertRaises(ValueError):ConfigManager(home,home/'state').apply(c,v)
            self.assertEqual(p.read_text(),'model_catalog_json="other.json"\n')
    def test_multiline_assignment_rejected(self):
        with self.assertRaises(ValueError):edit_config('[desktop]\nenabled-reasoning-efforts = [\n"max"\n]\n',{'desktop.enabled-reasoning-efforts':['low']})


class UpdateTests(unittest.TestCase):
    def setup_trust(self,root):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives.serialization import Encoding,PublicFormat
        self.key=Ed25519PrivateKey.generate()
        self.public=base64.b64encode(self.key.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw)).decode()
        atomic_json(root/'update-trust.json',{'public_key':self.public,'sequence':1,'manifest_url':'https://raw.githubusercontent.com/example/release/main/latest.json'})
    def envelope(self,data):
        raw=json.dumps(data).encode();return {'payload':base64.b64encode(raw).decode(),'signature':base64.b64encode(self.key.sign(raw)).decode()}
    def test_failure_is_throttled_across_restart(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);state=root/'state';self.setup_trust(root);calls=[]
            def fail(*args):calls.append(args);raise OSError()
            self.assertEqual(updater.check(root,state,1000,fail),'deferred')
            updater.check(root,state,1001,fail);self.assertEqual(len(calls),1)
            updater.check(root,state,1000+86401,fail);self.assertEqual(len(calls),2)
    def test_signed_installer_staged_and_tampering_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);self.setup_trust(root);package=b'MZtest-installer'
            m={'product':'codex-quota-guard','sequence':2,'version':'0.1.1','size':len(package),
               'sha256':hashlib.sha256(package).hexdigest(),'url':'https://github.com/example/release/releases/download/v0.1.1/setup.exe'}
            env=self.envelope(m)
            def download(url,cap,headers):return (json.dumps(env).encode(),'etag') if url.endswith('.json') else (package,None)
            self.assertEqual(updater.check(root,root/'state',1000,download),'ready')
            pending=read_json(root/'state/pending-update.json');self.assertEqual(Path(pending['path']).read_bytes(),package)
            installed=read_json(root/'update-trust.json');installed['sequence']=2
            atomic_json(root/'update-trust.json',installed)
            self.assertEqual(updater.check(root,root/'state',1001,download),'up_to_date')
            env['signature']=base64.b64encode(b'X'*64).decode()
            with self.assertRaises(Exception):updater.verify(env,self.public)
    def test_update_size_hash_and_origin_rejected(self):
        for url in ['http://github.com/a','https://evil.test/a','https://github.com.evil.test/a','https://user@github.com/a','https://github.com:444/a']:
            self.assertFalse(updater.allowed(url))
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);self.setup_trust(root)
            m={'product':'codex-quota-guard','sequence':2,'version':'0.1.1','size':updater.MAX_INSTALLER+1,'sha256':'a'*64,'url':'https://github.com/a'}
            with self.assertRaises(ValueError):updater.verify(self.envelope(m),self.public)


if __name__=='__main__':unittest.main()
