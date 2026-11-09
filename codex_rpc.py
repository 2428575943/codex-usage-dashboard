"""Bounded official app-server client; no inference, messages, or token handling."""
import hashlib
import json
import os
from pathlib import Path
import queue
import subprocess
import threading
import time
import urllib.request


def discover_binary():
    local = Path(os.environ.get('LOCALAPPDATA', '')) / 'OpenAI/Codex/bin'
    paths = list(local.glob('*/codex.exe'))
    # Resolve each cycle; do not pin a component version directory.
    paths.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    if paths:
        return paths[0]
    raise FileNotFoundError('codex_component_not_found')


class Rpc:
    def __init__(self, binary, home, overrides=()):
        args = [str(binary), 'app-server']
        for value in overrides:
            args += ['-c', value]
        env = {**os.environ, 'CODEX_HOME': str(home)}
        # Rust components do not consistently inherit Windows Internet Settings.
        # Reuse the user's existing proxy; never edit registry/network settings.
        proxies = urllib.request.getproxies()
        for kind in ('http', 'https'):
            if not env.get(kind.upper()+'_PROXY') and not env.get(kind+'_proxy') and proxies.get(kind):
                env[kind.upper()+'_PROXY'] = proxies[kind]
        self.proc = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, encoding='utf-8', errors='replace', bufsize=1,
            env=env,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        self.lines = queue.Queue(maxsize=1024)
        self.seq = 0
        def pump():
            try:
                for line in self.proc.stdout:
                    try:
                        self.lines.put_nowait(line)
                    except queue.Full:
                        break
            finally:
                try:
                    self.lines.put_nowait(None)
                except queue.Full:
                    pass
        self.reader = threading.Thread(target=pump, daemon=True)
        self.reader.start()
        try:
            self.call('initialize', {'clientInfo': {'name': 'codex_quota_guard',
                       'title': 'Codex Quota Guard', 'version': '0.1.0'}})
            self.send({'method': 'initialized', 'params': {}})
        except Exception:
            self.close()
            raise

    def send(self, value):
        self.proc.stdin.write(json.dumps(value) + '\n')
        self.proc.stdin.flush()

    def call(self, method, params=None, timeout=25):
        self.seq += 1
        self.send({'id': self.seq, 'method': method, 'params': params or {}})
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                line = self.lines.get(timeout=max(.01, deadline-time.monotonic()))
            except queue.Empty:
                break
            if line is None:
                raise RuntimeError('app_server_closed')
            try:
                response = json.loads(line)
            except ValueError:
                continue
            if response.get('id') == self.seq:
                if 'error' in response:
                    raise RuntimeError('app_server_rpc_error:' + method + ':' + str(response['error'].get('code', 'unknown')))
                return response.get('result') or {}
        raise TimeoutError('app_server_timeout:' + method)

    def close(self):
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=4)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=4)
        for stream in (self.proc.stdin, self.proc.stdout):
            if stream:
                stream.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def account_fingerprint(result):
    account = result.get('account')
    if not isinstance(account, dict) or account.get('type') != 'chatgpt':
        return None
    # Account IDs and emails stay in process memory; only a one-way digest is saved locally.
    stable = account.get('id') or account.get('email')
    return hashlib.sha256(str(stable).encode()).hexdigest() if stable else None


def probe(home):
    with Rpc(discover_binary(), home) as rpc:
        account = account_fingerprint(rpc.call('account/read', {'refreshToken': False}))
        quota = rpc.call('account/rateLimits/read') if account else {}
    return account, quota
