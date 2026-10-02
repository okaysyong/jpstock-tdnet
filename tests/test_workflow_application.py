"""Check JST weekday boundaries and the real deployment credential probe."""
from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
import re
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import verify_vps_ingest


def field_matches(field,value):
    for part in field.split(','):
        interval=1
        if '/' in part:part,interval=part.split('/');interval=int(interval)
        if part=='*':return True
        if '-' in part:
            start,stop=map(int,part.split('-'))
            if start<=value<=stop and (value-start)%interval==0:return True
        elif value==int(part):return True
    return False


def scheduled(name,stamp,fast_only=False):
    content=(ROOT/'.github/workflows'/name).read_text(encoding='utf-8')
    for cron in re.findall(r"cron: '([^']+)'",content):
        fields=cron.split()
        if fast_only and '/5' not in fields[0]:continue
        values=(stamp.minute,stamp.hour,stamp.day,stamp.month,(stamp.weekday()+1)%7)
        if all(field_matches(field,value) for field,value in zip(fields,values)):return True
    return False


class WorkflowApplicationTests(unittest.TestCase):
    def test_jst_monday_morning_and_friday_daytime_collectors_run(self):
        for name,minute in [('fetch_news.yml',1),('tdnet.yml',2),('fetch_kabutan.yml',3)]:
            for local in [datetime(2026,10,5,8,minute),datetime(2026,10,5,9,minute),datetime(2026,10,9,15,minute)]:
                utc=(local-timedelta(hours=9)).replace(tzinfo=timezone.utc)
                self.assertTrue(scheduled(name,utc,fast_only=True),(name,local))
            weekend=datetime(2026,10,9,23,minute,tzinfo=timezone.utc)
            self.assertFalse(scheduled(name,weekend,fast_only=True))
            self.assertTrue(scheduled(name,weekend),'weekend background still collects')

    def test_stock_news_jst_monday_0700_is_not_saturday(self):
        self.assertTrue(scheduled('stock_news.yml',datetime(2026,10,4,22,7,tzinfo=timezone.utc)))
        self.assertTrue(scheduled('stock_news.yml',datetime(2026,10,9,9,7,tzinfo=timezone.utc)))
        self.assertFalse(scheduled('stock_news.yml',datetime(2026,10,9,22,7,tzinfo=timezone.utc)))

    def test_credential_probe_cannot_insert_records(self):
        with patch.dict(verify_vps_ingest.os.environ,{'VPS_BASE_URL':'https://example.test'},clear=True),\
             patch.object(verify_vps_ingest,'push_json',return_value={'ok':True,'saved':0,'total':0}) as push:
            verify_vps_ingest.main()
        push.assert_called_once_with('https://example.test','/push/kessan',{'items':[]})
        with patch.object(verify_vps_ingest,'push_json',return_value={'ok':True,'saved':1,'total':1}):
            with self.assertRaises(RuntimeError):verify_vps_ingest.main()

    def test_application_check_only_uses_main_push_not_pr_secrets(self):
        content=(ROOT/'.github/workflows/tests.yml').read_text(encoding='utf-8')
        self.assertIn("if: github.event_name == 'push' && github.ref == 'refs/heads/main'",content)
        self.assertIn('needs: tests',content)
        self.assertIn('run: python verify_vps_ingest.py',content)
        self.assertIn('secrets.VPS_PUSH_SECRET || secrets.VPS_TOKEN',content)


if __name__=='__main__':unittest.main()
