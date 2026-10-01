import base64
import hashlib
import hmac
import ipaddress
import json
import os
import re
import secrets
import socket
import time
from urllib.parse import urlsplit
from cryptography.fernet import Fernet

class Problem(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def token():
    return secrets.token_urlsafe(32)


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def equal(a, b):
    return bool(a and b) and hmac.compare_digest(str(a), str(b))


def origin(value):
    if not isinstance(value,str):
        raise Problem('Use a valid public HTTPS website address.')
    try:
        p = urlsplit(value)
        local_hosts = set(os.environ.get('VOCA_LOCAL_DEV_HOSTS','').split(','))
        local = p.scheme=='http' and p.hostname in local_hosts and p.hostname.endswith('.local')
        if (p.scheme != 'https' and not local) or not p.hostname or p.username or p.password or p.port not in (None, 80 if local else 443):
            raise ValueError()
        host = p.hostname.encode('idna').decode('ascii').lower()
        if not re.fullmatch(r'[a-z0-9.-]+', host) or host.endswith('.'):
            raise ValueError()
        return ('http://' if local else 'https://') + host
    except (ValueError, UnicodeError):
        raise Problem('Use a valid public HTTPS website address.')


def public_ips(host):
    try:
        addresses = sorted({a[4][0] for a in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)})
    except OSError:
        raise Problem('Website hostname could not be resolved.')
    if not addresses or any(not ipaddress.ip_address(a).is_global for a in addresses):
        raise Problem('Only public websites can be scanned.')
    return addresses


def valid_shop(shop):
    if not isinstance(shop, str) or not re.fullmatch(r'[a-z0-9][a-z0-9-]*\.myshopify\.com', shop):
        raise Problem('Enter the store’s myshopify.com hostname.')
    return shop


def signature(secret, raw, supplied):
    expected = base64.b64encode(hmac.new(secret.encode(), raw, hashlib.sha256).digest()).decode()
    return equal(expected, supplied)


class Vault:
    def __init__(self, key):
        try:
            self.fernet = Fernet(key.encode())
        except (ValueError, TypeError):
            raise Problem('VOCA_ENCRYPTION_KEY must be a Fernet key. Run the setup helper.', 503)

    def encrypt(self, value):
        return self.fernet.encrypt(json.dumps(value).encode()).decode()

    def decrypt(self, value):
        return json.loads(self.fernet.decrypt(value.encode())) if value else {}


class RateLimit:
    def __init__(self, limit=20, seconds=60):
        import threading
        self.lock = threading.Lock()
        self.items = {}
        self.limit, self.seconds = limit, seconds

    def check(self, key):
        with self.lock:
            now = time.time()
            if len(self.items) > 5000:
                self.items = {k: v for k, v in self.items.items() if now - v[0] < self.seconds}
            start, count = self.items.get(key, (now, 0))
            if now - start > self.seconds:
                start, count = now, 0
            if count >= self.limit:
                raise Problem('Too many requests. Please try again shortly.', 429)
            self.items[key] = (start, count + 1)
