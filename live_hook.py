"""Trusted Codex UserPromptSubmit entry point. Always produce an explicit admission result."""
import argparse
import json
from pathlib import Path
import sys
from live_guard import check


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--home',type=Path,required=True)
    p.add_argument('--state',type=Path,required=True)
    args=p.parse_args()
    try:
        raw=sys.stdin.buffer.read(16*1024*1024+1)
        if len(raw)>16*1024*1024:
            raise ValueError('input_too_large')
        event=json.loads(raw.decode('utf-8-sig'))
        if not isinstance(event,dict):raise ValueError('input_not_object')
        output=check(event,args.home,args.state)
    except Exception:
        output={'decision':'block','reason':'额度守护无法完成本次模型检查，已阻止提交。请检查守护状态后重试。'}
    print(json.dumps(output,ensure_ascii=False))


if __name__=='__main__':main()
