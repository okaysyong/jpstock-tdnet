"""Standalone GitHub checkout tests; HTTP is always fake."""
import ast
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import requests

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import collector_common as common


class Reply:
    def __init__(self,result,status=200):self.result,self.status_code=result,status
    def json(self):return self.result
    def raise_for_status(self):
        if self.status_code>=400:raise requests.HTTPError('fake HTTP failure',response=self)


class FakeHTTP:
    def __init__(self,*responses):self.responses=list(responses);self.calls=[]
    def post(self,url,**kwargs):self.calls.append((url,kwargs));return self.responses.pop(0)


class CollectorTests(unittest.TestCase):
    def test_push_uses_header_strips_legacy_fields_and_accepts_duplicates(self):
        http=FakeHTTP(Reply({'ok':True,'saved':0,'duplicates':2,'failed':0,'total':2}))
        result=common.push_json('https://example.test','/push/news',{'items':[],'token':'old','secret':'old'},session=http,token='test-only')
        self.assertEqual(result['duplicates'],2)
        sent=http.calls[0][1]
        self.assertEqual(sent['headers'],{'X-Push-Token':'test-only'})
        self.assertNotIn('token',sent['json']);self.assertNotIn('secret',sent['json'])
        self.assertFalse(sent['allow_redirects'])

    @patch.object(common.time,'sleep')
    def test_invalid_partial_http_and_redirect_results_fail(self,sleep):
        for response in (Reply({'ok':False}),Reply({'ok':True,'failed':1}),Reply([]),Reply({'ok':True},302),Reply({'ok':True},500)):
            with self.subTest(response=response),self.assertRaises(RuntimeError):
                common.push_json('https://example.test','/push/news',{},session=FakeHTTP(response,response,response),token='test-only')
        http=FakeHTTP(Reply({},401))
        with self.assertRaises(RuntimeError):common.push_json('https://example.test','/push/news',{},session=http,token='test-only')
        self.assertEqual(len(http.calls),1)

    def test_missing_credentials_and_insecure_urls_fail_without_http(self):
        with patch.dict(common.os.environ,{},clear=True):
            with self.assertRaises(RuntimeError):common.push_json('https://example.test','/push/news',{})
        for url in ('http://example.test','https://name:pass@example.test','https://example.test/?token=x'):
            with self.subTest(url=url),self.assertRaises(RuntimeError):common.push_json(url,'/push/news',{},session=FakeHTTP(),token='test-only')

    def test_large_batches_are_bounded_and_results_accumulate(self):
        http=FakeHTTP(Reply({'ok':True,'saved':300,'duplicates':0,'failed':0,'total':300}),Reply({'ok':True,'saved':299,'duplicates':1,'failed':0,'total':300}))
        result=common.push_json('https://example.test','/push/tdnet',{'items':[{'id':n} for n in range(600)]},session=http,token='test-only')
        self.assertEqual((result['saved'],result['duplicates'],result['total']),(599,1,600))
        self.assertEqual([len(call[1]['json']['items']) for call in http.calls],[300,300])

    def test_document_and_calendar_identity(self):
        a={'stock_code':'7203','title':'A','disclosed_at':'2026-10-01 09:00','pdf_url':'https://www.release.tdnet.info/inbs/a.pdf'}
        b=dict(a,title='B',pdf_url='https://www.release.tdnet.info/inbs/b.pdf')
        self.assertNotEqual(common.canonical_disclosure_id(a),common.canonical_disclosure_id(b))
        self.assertEqual(common.canonical_disclosure_id(a),common.canonical_disclosure_id(dict(a,pdf_url=a['pdf_url']+'?cache=1')))
        keys={common.event_identity('2026-10-01','21:30',country,title) for country,title in [('USD','Unemployment Rate'),('USD','Nonfarm Payrolls'),('JPY','Unemployment Rate')]}
        self.assertEqual(len(keys),3)
        self.assertEqual(common.event_identity('2026-10-01','21:30','USD','Unemployment Rate'),common.event_identity('2026-10-01','21:30','US','失業率'))

    def test_tdnet_parser_keeps_two_same_minute_documents(self):
        spec=importlib.util.spec_from_file_location('collector_tdnet_test',ROOT/'collect_tdnet.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        html='''<table id="main-list-table"><tr><td class="kjTime">15:00</td><td class="kjCode">72030</td><td class="kjName">Toyota</td><td class="kjTitle"><a href="a.pdf">業績予想の修正</a></td></tr>
          <tr><td class="kjTime">15:00</td><td class="kjCode">72030</td><td class="kjName">Toyota</td><td class="kjTitle"><a href="b.pdf">配当予想の修正</a></td></tr></table>'''
        class Page:
            status_code=200;text=html;encoding='utf-8'
            def raise_for_status(self):pass
        class End(Page):status_code=404
        with patch.object(module.requests,'get',side_effect=[Page(),End()]):
            items=module.fetch_tdnet()
        self.assertEqual(len(items),2)
        self.assertEqual(len({i['disclosure_id'] for i in items}),2)

    def test_workflows_and_deploy_files_are_self_contained(self):
        workflows=list((ROOT/'.github/workflows').glob('*.yml'))
        text='\n'.join(p.read_text(encoding='utf-8') for p in workflows if p.name!='tests.yml')
        self.assertEqual(text.count('run: python collect_tdnet.py'),1)
        for p in workflows:
            content=p.read_text(encoding='utf-8')
            self.assertIn('permissions:',content);self.assertIn('timeout-minutes:',content)
            for line in content.splitlines():
                if 'run: python ' in line and ' -m ' not in line:
                    name=line.split('run: python ',1)[1].split()[0]
                    self.assertTrue((ROOT/name).is_file(),name)
        for file in ('collector_common.py','safe_pdf.py','collect_calendar.py'):
            ast.parse((ROOT/file).read_text(encoding='utf-8'))
        for line in (ROOT/'requirements.txt').read_text(encoding='utf-8').splitlines():
            if line and not line.startswith('#'):self.assertIn('==',line)


if __name__=='__main__':unittest.main()
