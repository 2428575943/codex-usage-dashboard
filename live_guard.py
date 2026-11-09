"""Per-submit admission policy. No prompts, transcripts, or credentials are saved."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import time
from guard_core import LUNA, atomic_json, policy, quota_from_result, read_json
from codex_rpc import Rpc, account_fingerprint, discover_binary

LIVE_CACHE_SECONDS = 5


def auth_generation(home):
    try:
        st = (Path(home)/'auth.json').stat()
        return str(st.st_mtime_ns)+':'+str(st.st_size)
    except OSError:
        return 'missing'


@contextmanager
def quota_lock(state):
    state = Path(state)
    state.mkdir(parents=True, exist_ok=True)
    with (state/'live-quota.lock').open('a+b') as handle:
        handle.seek(0, 2)
        if handle.tell() == 0:
            handle.write(b'0');handle.flush()
        deadline = time.monotonic()+.8
        while True:
            try:
                handle.seek(0)
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX|fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise TimeoutError('quota_check_busy')
                time.sleep(.025)
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == 'nt':
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def probe_quota(home):
    # Explicit budgets leave time to return a blocking decision before the hook timeout.
    with Rpc(discover_binary(), home, initialize_timeout=2, close_timeout=.5) as rpc:
        account = account_fingerprint(rpc.call('account/read', {'refreshToken': False}, timeout=1.5))
        raw = rpc.call('account/rateLimits/read', timeout=2) if account else {}
    return quota_from_result(raw, account) if account else None


def current_quota(home, state, probe=probe_quota, clock=time.time):
    home,state=Path(home),Path(state)
    generation=auth_generation(home)
    with quota_lock(state):
        cached=read_json(state/'live-quota.json',{})
        now=clock()
        quota=cached.get('quota')
        if cached.get('auth_generation')==generation and isinstance(quota,dict):
            try:
                if (quota.get('account') and 0<=now-quota['observed_at']<=LIVE_CACHE_SECONDS
                        and quota['resets_at']>now):
                    policy(quota['remaining'])
                    return quota,'fresh_shared_cache'
            except (KeyError,TypeError,ValueError):
                pass
        # Sharing the failure cooldown also prevents parallel chats causing retry storms.
        if (cached.get('auth_generation')==generation and cached.get('failed_at') is not None
                and 0<=now-cached['failed_at']<=LIVE_CACHE_SECONDS):
            return None,'recent_query_failure'
        try:
            quota=probe(home)
            if auth_generation(home)!=generation:
                # A refresh may have written credentials. Query on the next submission.
                quota=None
            if quota:
                policy(quota['remaining'])
                atomic_json(state/'live-quota.json',{'auth_generation':generation,'quota':quota})
                return quota,'official_pre_submit_query'
        except Exception:
            pass
        atomic_json(state/'live-quota.json',{'auth_generation':auth_generation(home),
                    'quota':None,'failed_at':clock()})
        return None,'quota_unknown'


def decide(event, quota):
    model=event.get('model')
    remaining=quota.get('remaining') if isinstance(quota,dict) else None
    tier,allowed=policy(remaining)
    valid_event=event.get('hook_event_name')=='UserPromptSubmit'
    internal_review=(model=='codex-auto-review' and bool(event.get('agent_id') or event.get('agent_type')))
    permit=valid_event and isinstance(model,str) and (model in allowed or internal_review)
    result={'allowed':permit,'model':model if isinstance(model,str) else None,
            'tier':tier,'allowed_models':allowed,'remaining_percent':remaining}
    if not permit:
        balance='暂时无法确认' if remaining is None else f'{remaining:g}%'
        result['output']={'decision':'block','reason':
            f'额度守护已阻止本次提交：5 小时剩余{balance}。当前可使用 '+
            '、'.join(allowed)+'。请在同一聊天切换到允许的模型后重新提交，无需重启 Codex。'}
    else:
        result['output']={}
    return result


def check(event, home, state, probe=probe_quota):
    if (Path(state)/'live-disabled.flag').exists():
        return {}
    try:
        quota,basis=current_quota(home,state,probe)
    except Exception:
        quota,basis=None,'local_check_error'
    result=decide(event,quota)
    # A single bounded local receipt; deliberately omit prompt, transcript and chat identifiers.
    try:
        atomic_json(Path(state)/'last-admission.json',{
            **{k:v for k,v in result.items() if k!='output'},'basis':basis,'at':time.time(),
            'scope':'next_user_prompt','max_shared_cache_seconds':LIVE_CACHE_SECONDS})
    except OSError:
        pass
    return result['output']
