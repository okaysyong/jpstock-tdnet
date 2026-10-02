"""Check the protected earnings endpoint with an empty, non-destructive batch."""
import os
from collector_common import push_json


def main():
    base=(os.environ.get('VPS_BASE_URL') or os.environ.get('VPS_URL')
          or os.environ.get('VPS_NEWS_API_URL') or 'https://jpstocklive.com').strip()
    result=push_json(base,'/push/kessan',{'items':[]})
    if result.get('total')!=0 or result.get('saved')!=0:
        raise RuntimeError('Unexpected non-empty endpoint verification result')
    print('Authenticated VPS endpoint accepted an empty batch; no records saved.')


if __name__=='__main__':main()
