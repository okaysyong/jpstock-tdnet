"""Shared collector contracts; no network or environment changes on import."""
import hashlib
import json
import os
import time
import unicodedata
from urllib.parse import urlsplit
import requests

TOKEN_KEYS = ('VPS_PUSH_TOKEN','VPS_TOKEN','VPS_PUSH_SECRET','PUSH_TOKEN')


def canonical_disclosure_id(item):
    parsed=urlsplit(str(item.get('pdf_url') or '').strip())
    identity=parsed.hostname.lower()+parsed.path if parsed.hostname and parsed.path else '|'.join(str(item.get(k) or '').strip() for k in ('stock_code','disclosed_at','title'))
    return 'doc_'+hashlib.sha256(identity.encode('utf-8')).hexdigest()[:32]


def event_identity(date, clock, country, title):
    value=''.join(c for c in unicodedata.normalize('NFKC',title).casefold().strip() if c.isalnum())
    aliases={'nonfarmemploymentchange':'nonfarmpayrolls','非農業部門雇用者数':'nonfarmpayrolls','失業率':'unemploymentrate','新規失業保険申請件数':'unemploymentclaims'}
    countries={'USD':'US','JPY':'JP','EUR':'EU','GBP':'GB','AUD':'AU','CNY':'CN'}
    raw='|'.join((date,clock[:5],countries.get(country,country),aliases.get(value,value)))
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()[:32]


def push_json(base_url,path,payload,session=None,timeout=30,token=None):
    token=token or next((os.getenv(k,'').strip() for k in TOKEN_KEYS if os.getenv(k,'').strip()),'')
    if not token:
        raise RuntimeError('VPS_PUSH_TOKEN is required')
    base=base_url.rstrip('/')
    parsed=urlsplit(base)
    if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise RuntimeError('Invalid VPS endpoint')
    if parsed.scheme!='https' and not (parsed.scheme=='http' and parsed.hostname in ('localhost','127.0.0.1','::1')):
        raise RuntimeError('VPS endpoint must use HTTPS (HTTP is allowed only on loopback)')
    client=session or requests
    body={k:v for k,v in payload.items() if k not in ('token','secret')}
    batch_key=next((key for key in ('items','news','events') if isinstance(body.get(key),list)),None)
    if batch_key and len(body[batch_key])>1 and (len(body[batch_key])>500 or len(json.dumps(body,ensure_ascii=False).encode('utf-8'))>1024*1024):
        midpoint=len(body[batch_key])//2
        results=[push_json(base,path,dict(body,**{batch_key:part}),session=session,timeout=timeout,token=token)
                 for part in (body[batch_key][:midpoint],body[batch_key][midpoint:])]
        return dict(ok=True,**{key:sum(result.get(key,0) for result in results)
            for key in ('saved','upserted','inserted','duplicates','skipped','failed','total')})
    last_error=None
    for attempt in range(3):
        try:
            response=client.post(base+path,json=body,headers={'X-Push-Token':token},timeout=timeout,allow_redirects=False)
            if response.status_code not in (200,201):
                response.raise_for_status()
                raise RuntimeError('Unexpected ingestion HTTP status')
            response.raise_for_status()
            result=response.json()
            if not isinstance(result,dict) or result.get('ok') is not True or result.get('failed',0):
                raise RuntimeError('VPS rejected the batch')
            return result
        except (requests.RequestException,ValueError,RuntimeError) as exc:
            last_error=exc
            code=getattr(getattr(exc,'response',None),'status_code',None)
            if code is not None and 400<=code<500:
                break
            if attempt<2:
                time.sleep(attempt+1)
    # Do not print response bodies, credential-bearing URLs or request headers.
    raise RuntimeError('VPS ingestion failed after validation/retry') from None


def get_json(base_url,path,session=None,timeout=30):
    response=(session or requests).get(base_url.rstrip('/')+path,timeout=timeout)
    response.raise_for_status()
    result=response.json()
    if not isinstance(result,dict) or result.get('ok') is False:
        raise RuntimeError('VPS query failed')
    return result
