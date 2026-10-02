"""Bounded TDnet PDF downloads with validated redirects and pinned public IPs."""
import ipaddress
import socket
from urllib.parse import urljoin, urlsplit, urlunsplit

PDF_HOSTS=frozenset(('www.release.tdnet.info','release.tdnet.info'))


def _resolve(url,resolver):
    parsed=urlsplit(url)
    if (parsed.scheme!='https' or parsed.hostname not in PDF_HOSTS or
        parsed.username or parsed.password or parsed.port not in (None,443)):
        raise ValueError('PDF host is not allowed')
    addresses=resolver(parsed.hostname,443,type=socket.SOCK_STREAM)
    ips=list(dict.fromkeys(entry[4][0] for entry in addresses))
    if not ips or any(not ipaddress.ip_address(ip).is_global for ip in ips):
        raise ValueError('PDF address is not public')
    return urlunsplit(('https',parsed.netloc,parsed.path,parsed.query,'')),ips


def validate_pdf_url(url,resolver=socket.getaddrinfo):
    return _resolve(url,resolver)[0]


class _PinnedResponse:
    def __init__(self,url,ip):
        import certifi
        import urllib3
        parsed=urlsplit(url)
        self.url=url
        # Connect to the validated address directly. SNI/certificate verification
        # still use the original hostname, avoiding a second DNS resolution.
        self.pool=urllib3.HTTPSConnectionPool(ip,443,assert_hostname=parsed.hostname,
            server_hostname=parsed.hostname,cert_reqs='CERT_REQUIRED',ca_certs=certifi.where())
        try:
            self.response=self.pool.urlopen('GET',urlunsplit(('','',parsed.path or '/',parsed.query,'')),
                headers={'Host':parsed.hostname,'User-Agent':'JPStockLive/1.0'},
                redirect=False,retries=False,preload_content=False,
                timeout=urllib3.Timeout(connect=5,read=15))
        except BaseException:
            self.pool.close()
            raise
        self.status_code=self.response.status
        self.headers=self.response.headers

    def __enter__(self):
        return self

    def __exit__(self,*args):
        self.response.close()
        self.pool.close()

    def raise_for_status(self):
        if self.status_code!=200:
            raise ValueError('PDF upstream did not return HTTP 200')

    def iter_content(self,size):
        return self.response.stream(size,decode_content=True)


def fetch_pdf(url,session=None,resolver=socket.getaddrinfo,max_bytes=12*1024*1024):
    """Session injection is for offline tests; production uses a pinned TLS socket."""
    for _ in range(4):
        url,ips=_resolve(url,resolver)
        response=(session.get(url,timeout=(5,15),stream=True,allow_redirects=False,
                             headers={'User-Agent':'JPStockLive/1.0'})
                  if session is not None else _PinnedResponse(url,ips[0]))
        with response:
            final_url=getattr(response,'url',url) or url
            validate_pdf_url(final_url,resolver)
            if response.status_code in (301,302,303,307,308):
                location=response.headers.get('Location')
                if not location:
                    raise ValueError('PDF redirect has no location')
                url=urljoin(final_url,location)
                continue
            response.raise_for_status()
            if response.status_code!=200:
                raise ValueError('PDF upstream did not return HTTP 200')
            if int(response.headers.get('Content-Length') or 0)>max_bytes:
                raise ValueError('PDF too large')
            output=bytearray()
            for chunk in response.iter_content(65536):
                output.extend(chunk)
                if len(output)>max_bytes:
                    raise ValueError('PDF too large')
            if not output.startswith(b'%PDF-'):
                raise ValueError('Response is not a PDF')
            return bytes(output)
    raise ValueError('Too many PDF redirects')
