"""Pinned public HTTPS crawler and fixed-host JSON API client."""
import http.client
import json
import socket
import ssl
import time
from contextvars import ContextVar
from contextlib import contextmanager
from functools import wraps
from urllib.parse import urlsplit, urljoin
from .security import Problem, origin, public_ips

_deadline = ContextVar('voca_request_deadline', default=None)

class RequestDeadline(Problem):
    def __init__(self):
        super().__init__('The answer took too long. Please retry in a moment.',504)

@contextmanager
def request_budget(seconds=50):
    previous = _deadline.get()
    token = _deadline.set(min(previous, time.monotonic()+seconds) if previous else time.monotonic()+seconds)
    try:
        yield
    finally:
        _deadline.reset(token)

def bounded_answer(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        with request_budget():
            return fn(*args, **kwargs)
    return wrapped

def remaining():
    end = _deadline.get()
    left = end-time.monotonic() if end else 45
    if left <= 0:
        raise RequestDeadline()
    return left

class ProviderError(Problem):
    def __init__(self, upstream_status):
        self.upstream_status = upstream_status
        self.retryable = upstream_status in (404,429,500,502,503,504)
        message = ('AI provider limit reached. Check API credits and usage limits, or configure Gemini fallback.'
                   if upstream_status == 429 else
                   'The selected model is unavailable. Check its model name or select another model.' if upstream_status == 404 else
                   'The AI provider is temporarily unavailable. Please retry shortly.' if upstream_status >= 500 else
                   'Connected service returned HTTP %s. Check access and permissions.' % upstream_status)
        super().__init__(message, 503 if upstream_status == 429 else 502)

MAX_BYTES = 2_000_000

class PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host, ip):
        super().__init__(host, timeout=20, context=ssl.create_default_context())
        self.ip = ip

    def connect(self):
        sock = socket.create_connection((self.ip, 443), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


def fetch_public(url, allowed_origin, redirects=0):
    if origin(url) != allowed_origin or redirects > 4:
        raise Problem('Scan redirect left the connected website.')
    p = urlsplit(url)
    conn = PinnedHTTPS(p.hostname, public_ips(p.hostname)[0])
    try:
        conn.request('GET', p.path or '/', headers={'Host': p.hostname, 'User-Agent': 'VocaBot/1.0', 'Accept-Encoding': 'identity'})
        response = conn.getresponse()
        if response.status in (301, 302, 303, 307, 308):
            return fetch_public(urljoin(url, response.getheader('Location', '')), allowed_origin, redirects + 1)
        if response.status >= 400:
            raise Problem('A published page could not be fetched (HTTP %s).' % response.status, 502)
        body = response.read(MAX_BYTES + 1)
        if len(body) > MAX_BYTES:
            raise Problem('Page is too large to scan.')
        return body, response.getheader('Content-Type', ''), url
    finally:
        conn.close()


def api(url, body=None, headers=None, method=None):
    p = urlsplit(url)
    if p.scheme != 'https' or p.username or p.password:
        raise Problem('API endpoint must use HTTPS.')
    request_headers = {'Content-Type': 'application/json', 'Accept': 'application/json', **(headers or {})}
    payload = None if body is None else json.dumps(body).encode()
    method = method or ('POST' if body is not None else 'GET')
    attempts = 2 if _deadline.get() else 3
    for attempt in range(attempts):
        conn = http.client.HTTPSConnection(p.hostname, timeout=min(10 if _deadline.get() else 45, remaining()), context=ssl.create_default_context())
        try:
            conn.request(method, p.path + ('?' + p.query if p.query else ''), payload, request_headers)
            if conn.sock:
                conn.sock.settimeout(min(10 if _deadline.get() else 45, remaining()))
            response = conn.getresponse()
            pieces = []
            size = 0
            while size <= 8_000_000:
                if conn.sock:
                    conn.sock.settimeout(min(10 if _deadline.get() else 45, remaining()))
                else:
                    remaining()
                part = response.read1(min(65536,8_000_001-size))
                if not part:
                    break
                pieces.append(part)
                size += len(part)
            raw = b''.join(pieces)
            if response.status == 429 or response.status >= 500:
                if attempt < attempts-1:
                    delay = min(2 ** attempt, 4)
                    if remaining() <= delay:
                        raise RequestDeadline()
                    time.sleep(delay)
                    continue
            if response.status >= 300:
                raise ProviderError(response.status)
            if len(raw) > 8_000_000:
                raise Problem('Connected service response exceeded the import limit.', 502)
            return json.loads(raw) if raw else {}
        except (OSError, ValueError, http.client.HTTPException):
            if attempt == attempts-1:
                remaining()
                raise ProviderError(503)
        finally:
            conn.close()
