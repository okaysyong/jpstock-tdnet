"""Check authentication with a deliberately invalid, non-writing probe."""
import os
from urllib.parse import urlsplit
import requests
from collector_common import TOKEN_KEYS


def main():
    base=(os.environ.get('VPS_BASE_URL') or os.environ.get('VPS_URL')
          or os.environ.get('VPS_NEWS_API_URL') or 'https://jpstocklive.com').strip()
    token=next((os.environ.get(key,'').strip() for key in TOKEN_KEYS if os.environ.get(key,'').strip()),'')
    parsed=urlsplit(base)
    if not token:
        raise RuntimeError('VPS_PUSH_TOKEN is required')
    if (parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment):
        raise RuntimeError('Invalid HTTPS VPS endpoint')
    # The endpoint authenticates before validating items. A known validation
    # rejection proves access without inserting/updating any news or schedule.
    response=requests.post(base.rstrip('/')+'/push/kessan',
        json={'items':'authentication-probe-invalid'},headers={'X-Push-Token':token},
        timeout=15,allow_redirects=False)
    if response.status_code!=422:
        raise RuntimeError(f'Protected endpoint verification failed (HTTP {response.status_code})')
    try:detail=response.json().get('detail')
    except (ValueError,AttributeError):detail=None
    if detail!='Invalid ingest payload':
        raise RuntimeError('Protected endpoint validation contract did not match')
    print('Authenticated VPS endpoint rejected the invalid probe as expected; no records saved.')


if __name__=='__main__':main()
