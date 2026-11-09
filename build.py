"""Build standard Inno Setup with vendor CPython. No packed executable bootstrap."""
import argparse
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from guard_core import VERSION


def main():
    p=argparse.ArgumentParser();p.add_argument('--runtime-source',type=Path,required=True);p.add_argument('--iscc',type=Path,required=True)
    args=p.parse_args();root=Path(__file__).resolve().parent;payload=root/'build/payload'
    payload.mkdir(parents=True,exist_ok=True)
    for name in ['guard_core.py','runtime.py','codex_rpc.py','updater.py','update-trust.json']:
        shutil.copy2(root/name,payload/name)
    target=payload/'python'
    target.mkdir(exist_ok=True)
    for f in args.runtime_source.iterdir():
        if f.is_file() and re.fullmatch(r'(python.*\.(exe|dll|zip)|vcruntime.*\.dll|LICENSE.*)',f.name,re.I):
            shutil.copy2(f,target/f.name)
    ignore=shutil.ignore_patterns('__pycache__','*.pyc','test','tests','*.ps1','*.bat','*.cmd','*.vbs')
    shutil.copytree(args.runtime_source/'DLLs',target/'DLLs',dirs_exist_ok=True,ignore=ignore)
    lib=target/'Lib';lib.mkdir(exist_ok=True)
    for f in (args.runtime_source/'Lib').iterdir():
        if f.name in ('site-packages','test','tests','idlelib','tkinter','turtledemo','ensurepip','__pycache__','venv'):
            continue
        if f.is_dir():shutil.copytree(f,lib/f.name,dirs_exist_ok=True,ignore=ignore)
        else:shutil.copy2(f,lib/f.name)
    site=lib/'site-packages';site.mkdir(exist_ok=True)
    for f in (args.runtime_source/'Lib/site-packages').iterdir():
        if f.name in ('cryptography','cffi','pycparser') or re.fullmatch(r'(cryptography-.*\.dist-info|cffi-.*\.dist-info|_cffi_backend.*\.pyd|pycparser-.*\.dist-info)',f.name):
            if f.is_dir():shutil.copytree(f,site/f.name,dirs_exist_ok=True,ignore=ignore)
            else:shutil.copy2(f,site/f.name)
    compiler=Path(os.environ['WINDIR'])/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    subprocess.run([str(compiler),'/nologo','/target:winexe','/platform:x64','/optimize+',
        '/out:'+str(payload/'CodexQuotaGuard.exe'),'/reference:System.Windows.Forms.dll',
        '/reference:System.Drawing.dll','/reference:System.Web.Extensions.dll',str(root/'windows/Guard.cs')],check=True)
    subprocess.run([str(target/'python.exe'),'-X','utf8',str(payload/'runtime.py'),'--healthcheck'],check=True)
    forbidden=[p for p in payload.rglob('*') if p.suffix.lower() in ('.ps1','.vbs','.bat','.cmd')]
    if forbidden:raise ValueError('shell_bootstrap_in_payload')
    subprocess.run([str(args.iscc),'/Qp',str(root/'windows/setup.iss')],check=True)
    artifact=root/('dist/codex-quota-guard-'+VERSION+'-setup.exe')
    sha=hashlib.sha256(artifact.read_bytes()).hexdigest()
    (artifact.parent/'SHA256SUMS.txt').write_text(sha+'  '+artifact.name+'\n',encoding='utf-8')
    print('BUILD_OK',artifact.stat().st_size,sha)


if __name__=='__main__':main()
