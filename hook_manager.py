"""Register a user hook, retaining Codex's own review gate and other user hooks."""
import json
from pathlib import Path
from guard_core import atomic_bytes, atomic_json, read_json


def ps_quote(value):
    return "'"+str(value).replace("'","''")+"'"


def hook_command(root, home, state):
    root=Path(root)
    invoke=('& '+ps_quote(root/'python/python.exe')+' -X utf8 '+ps_quote(root/'live_hook.py')+
            ' --home '+ps_quote(home)+' --state '+ps_quote(state))
    # A loaded chat may retain its hook after uninstall. This stable Windows-shell
    # check allows it to become a no-op without calling an interpreter just removed.
    return ("if (Test-Path -LiteralPath "+ps_quote(Path(state)/'live-disabled.flag')+
            ") { '{}' } else { "+invoke+" }")


def install(root, home, state):
    home,state=Path(home),Path(state)
    path=home/'hooks.json';journal_path=state/'hook-ownership.json'
    raw=path.read_bytes() if path.exists() else b''
    data=json.loads(raw.decode('utf-8-sig')) if raw else {}
    if not isinstance(data,dict) or not isinstance(data.get('hooks',{}),dict):
        raise ValueError('existing_hooks_file_has_unsupported_shape')
    command=hook_command(root,home,state)
    group={'hooks':[{'type':'command','command':command,'timeout':12,
                    'statusMessage':'正在检查 Codex 额度与模型'}]}
    groups=data.setdefault('hooks',{}).setdefault('UserPromptSubmit',[])
    if not isinstance(groups,list):raise ValueError('existing_prompt_hooks_have_unsupported_shape')
    if group not in groups:
        journal=read_json(journal_path)
        if not journal:
            atomic_bytes(state/'hooks-before-install.json',raw)
            journal={'original_existed':bool(raw),'commands':[]}
        if command not in journal['commands']:journal['commands'].append(command)
        atomic_json(journal_path,journal)
        groups.append(group)
        if path.exists() and path.read_bytes()!=raw:raise ValueError('hooks_changed_concurrently')
        atomic_json(path,data)
    (state/'live-disabled.flag').unlink(missing_ok=True)
    return command


def status(rpc,command):
    result=rpc.call('hooks/list',{'cwds':[]},timeout=3)
    entries=[h for d in result.get('data',[]) for h in d.get('hooks',[])
             if h.get('eventName')=='userPromptSubmit' and h.get('command')==command]
    trusted=bool(entries) and all(h.get('enabled') and h.get('trustStatus') in ('trusted','managed') for h in entries)
    return {'registered':bool(entries),'trusted':trusted,'requires_review':not trusted,
            'scope':'next_user_prompt','registration_requires_codex_restart':False,
            'mid_turn_requests_enforced':False}


def restore(home,state):
    home,state=Path(home),Path(state)
    atomic_bytes(state/'live-disabled.flag',b'disabled\n')
    journal=read_json(state/'hook-ownership.json')
    if not journal:return
    path=home/'hooks.json'
    if path.exists():
        raw=path.read_bytes();data=json.loads(raw.decode('utf-8-sig'))
        groups=data.get('hooks',{}).get('UserPromptSubmit',[])
        commands=set(journal.get('commands',[]))
        kept=[]
        for group in groups:
            handlers=group.get('hooks',[])
            rest=[h for h in handlers if h.get('command') not in commands]
            if len(rest)==len(handlers):kept.append(group)
            elif rest:kept.append({**group,'hooks':rest})
        if kept:data['hooks']['UserPromptSubmit']=kept
        else:data.get('hooks',{}).pop('UserPromptSubmit',None)
        if path.read_bytes()!=raw:raise ValueError('hooks_changed_concurrently')
        atomic_json(path,data)
    (state/'hook-ownership.json').replace(state/'hook-ownership-restored.json')
