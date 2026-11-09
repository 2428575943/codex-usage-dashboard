"""Signed installer updates, one attempt per day, including across restarts."""
import base64
import hashlib
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from guard_core import atomic_bytes, atomic_json, read_json

MAX_INSTALLER = 100 * 1024 * 1024
INTERVAL = 24 * 3600
HOSTS = {'github.com', 'raw.githubusercontent.com', 'release-assets.githubusercontent.com',
         'objects.githubusercontent.com'}


def allowed(url):
    p = urllib.parse.urlsplit(url)
    return p.scheme == 'https' and p.hostname in HOSTS and p.port in (None, 443) and not p.username and not p.password


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not allowed(newurl):
            raise ValueError('unsafe_update_redirect')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url, cap, headers=None):
    if not allowed(url):
        raise ValueError('unsafe_update_url')
    # Respect the user's Windows/system proxy configuration. Never change proxy settings.
    opener = urllib.request.build_opener(SafeRedirect())
    request = urllib.request.Request(url, headers={'User-Agent': 'CodexQuotaGuard/0.1', **(headers or {})})
    try:
        with opener.open(request, timeout=25) as response:
            value = response.read(cap+1)
            if len(value) > cap:
                raise ValueError('update_too_large')
            return value, response.headers.get('ETag')
    except urllib.error.HTTPError as e:
        if e.code == 304:
            return None, None
        raise


def verify(envelope, public_key):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    payload = base64.b64decode(envelope['payload'], validate=True)
    signature = base64.b64decode(envelope['signature'], validate=True)
    Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key, validate=True)).verify(signature, payload)
    m = json.loads(payload)
    if m.get('product') != 'codex-quota-guard' or type(m.get('sequence')) is not int or m['sequence'] < 1:
        raise ValueError('invalid_update_product')
    if not re.fullmatch(r'\d+\.\d+\.\d+', m.get('version', '')):
        raise ValueError('invalid_update_version')
    if type(m.get('size')) is not int or not 0 < m['size'] <= MAX_INSTALLER:
        raise ValueError('invalid_update_size')
    if not re.fullmatch('[a-f0-9]{64}', m.get('sha256', '')) or not allowed(m.get('url', '')):
        raise ValueError('invalid_update_download')
    return m


def check(root: Path, state: Path, now=None, downloader=fetch):
    now = time.time() if now is None else now
    trust = read_json(root / 'update-trust.json', {})
    if not trust.get('manifest_url') or not trust.get('public_key'):
        return 'not_configured'
    path = state / 'update-state.json'
    record = read_json(path, {})
    if now < record.get('check_after', 0):
        if record.get('result') == 'ready' and trust.get('sequence', 0) >= record.get('sequence', 1):
            record['result'] = 'up_to_date'
            atomic_json(path, record)
        return record.get('result', 'cooldown')
    record['check_after'] = now + INTERVAL
    # Commit before any request. Offline, restarts and manual refresh cannot cause a request loop.
    atomic_json(path, record)
    try:
        headers = {'If-None-Match': record['etag']} if record.get('etag') else {}
        raw, etag = downloader(trust['manifest_url'], 32768, headers)
        if raw is None:
            result = 'up_to_date'
        else:
            manifest = verify(json.loads(raw), trust['public_key'])
            floor = max(trust.get('sequence', 0), record.get('sequence', 0))
            if manifest['sequence'] <= floor:
                result = 'up_to_date'
            else:
                package, _ = downloader(manifest['url'], manifest['size'], {})
                if package is None or len(package) != manifest['size'] or hashlib.sha256(package).hexdigest() != manifest['sha256']:
                    raise ValueError('update_hash_mismatch')
                if not package.startswith(b'MZ'):
                    raise ValueError('invalid_installer_format')
                destination = state / 'updates' / ('setup-' + str(manifest['sequence']) + '.exe')
                atomic_bytes(destination, package)
                atomic_json(state / 'pending-update.json', {'path': str(destination.resolve()),
                    'sha256': manifest['sha256'], 'sequence': manifest['sequence'], 'version': manifest['version']})
                record['sequence'] = manifest['sequence']
                result = 'ready'
            if etag:
                record['etag'] = etag
        record.update(result=result, checked_at=now)
        record.pop('error', None)
    except Exception as e:
        result = 'deferred'
        record.update(result=result, error=type(e).__name__, checked_at=now)
    atomic_json(path, record)
    return result
