"""One short worker cycle. The tray supervisor handles singleton/startup/recovery."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import time
import tomllib
from guard_core import (VERSION, ConfigManager, atomic_json, filtered_catalog, load_source,
                        quota_from_result, read_json, valid_quota)
from codex_rpc import Rpc, account_fingerprint, discover_binary
import updater

POLL_SECONDS = 180


def auth_generation(home):
    # Detect sign-in/out without opening or copying auth credentials.
    p = home / 'auth.json'
    try:
        st = p.stat()
        return str(st.st_mtime_ns) + ':' + str(st.st_size)
    except OSError:
        return 'missing'


def compatibility(binary, home, state, catalog, visible):
    """Check the real component parser and model/list with an isolated config override."""
    candidate = state / 'candidate-models.json'
    atomic_json(candidate, catalog)
    with Rpc(binary, home, ['model_catalog_json=' + json.dumps(str(candidate.resolve()))]) as rpc:
        result = rpc.call('model/list', {'limit': 100, 'includeHidden': False})
    items = result.get('data') or []
    actual = {m.get('model') or m.get('id'): {r.get('reasoningEffort') for r in m.get('supportedReasoningEfforts', [])}
              for m in items if not m.get('hidden')}
    if set(actual) != set(visible) or any(v != {'low', 'medium', 'high'} for v in actual.values()):
        raise ValueError('component_ignored_or_changed_model_catalog')
    return True


def cycle(home, state, root, apply=True, network=True):
    state.mkdir(parents=True, exist_ok=True)
    cache_path = state / 'quota-cache.json'
    cache = read_json(cache_path, {})
    now = time.time()
    generation = auth_generation(home)
    if cache.get('auth_generation') != generation:
        cache = {'auth_generation': generation}
    status = {'version': VERSION, 'at': now, 'enforcement': 'startup_catalog_and_defaults',
              'live_turn_enforcement': False, 'quota_poll_seconds': POLL_SECONDS,
              'update_interval_seconds': updater.INTERVAL, 'restart_required': False}
    binary = discover_binary()
    if network and now >= cache.get('next_poll', 0):
        cache['next_poll'] = now + POLL_SECONDS
        atomic_json(cache_path, cache)
        try:
            with Rpc(binary, home) as rpc:
                account = account_fingerprint(rpc.call('account/read', {'refreshToken': False}))
                # Never carry another login's cached quota forward.
                if account != cache.get('account'):
                    cache.pop('quota', None)
                cache['account'] = account
                limits = rpc.call('account/rateLimits/read') if account else {}
                quota = quota_from_result(limits, account)
                if quota:
                    cache['quota'] = quota
                else:
                    cache.pop('quota', None)
            # A successful official token refresh may change file mtime; bind to the post-read generation.
            cache['auth_generation'] = auth_generation(home)
            cache.pop('error', None)
        except Exception as e:
            cache['error'] = str(e) if isinstance(e, (RuntimeError, TimeoutError)) else type(e).__name__
        atomic_json(cache_path, cache)
    now = time.time()
    remaining = valid_quota(cache.get('quota'), cache.get('account'), now)
    source, source_path = load_source(home)
    catalog, tier, visible = filtered_catalog(source, remaining)
    digest = hashlib.sha256(json.dumps(catalog, sort_keys=True).encode()).hexdigest()
    component = str(binary) + ':' + str(binary.stat().st_mtime_ns)
    proof = read_json(state / 'compatibility.json', {})
    if proof.get('digest') != digest or proof.get('component') != component:
        compatibility(binary, home, state, catalog, visible)
        proof = {'digest': digest, 'component': component, 'verified_at': time.time()}
        atomic_json(state / 'compatibility.json', proof)
    status.update(remaining_percent=remaining, tier=tier, visible_models=visible,
                  efforts=['low', 'medium', 'high'], compatible=True,
                  quota_error=cache.get('error'), source_catalog=source_path.name,
                  quota_observed_at=(cache.get('quota') or {}).get('observed_at'))
    previous = read_json(state / 'status.json', {})
    if apply:
        changed = ConfigManager(home, state).apply(catalog, visible)
        # A component change or catalog change needs a full app restart. Never terminate user chats.
        status['restart_required'] = bool(changed or previous.get('restart_required'))
        status['config_applied'] = True
    else:
        status['config_applied'] = False
    status['update'] = updater.check(root, state) if network and apply else 'not_checked'
    atomic_json(state / 'status.json', status)
    return status


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--home', type=Path, default=Path(os.environ.get('CODEX_HOME', Path.home()/'.codex')))
    parser.add_argument('--state', type=Path, default=Path(os.environ.get('LOCALAPPDATA', '.'))/'CodexQuotaGuard')
    parser.add_argument('--restore', action='store_true')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--offline', action='store_true')
    parser.add_argument('--healthcheck', action='store_true')
    args = parser.parse_args()
    if args.healthcheck:
        from guard_core import policy
        assert policy(30)[0] == 'balanced' and policy(15)[0] == 'balanced'
        print('healthcheck_ok')
        return
    try:
        if args.restore:
            print(json.dumps(ConfigManager(args.home, args.state).restore()))
        else:
            print(json.dumps(cycle(args.home, args.state, Path(__file__).parent,
                                  apply=not args.dry_run, network=not args.offline)))
    except Exception as e:
        status = {'version': VERSION, 'at': time.time(), 'compatible': False,
                  'error': str(e) if isinstance(e, ValueError) else type(e).__name__,
                  'config_applied': False, 'live_turn_enforcement': False}
        atomic_json(args.state/'status.json', status)
        print(json.dumps(status))
        raise SystemExit(1)


if __name__ == '__main__':
    main()
