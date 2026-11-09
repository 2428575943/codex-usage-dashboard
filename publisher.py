"""Maintainer-only signed manifest creation. Never bundled with the installed app."""
import argparse
import base64
import ctypes
from ctypes import wintypes
import hashlib
import json
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding,PublicFormat
from guard_core import atomic_json
from updater import allowed


def unprotect(raw):
    class Blob(ctypes.Structure):
        _fields_=[('size',wintypes.DWORD),('data',ctypes.POINTER(ctypes.c_ubyte))]
    buf=(ctypes.c_ubyte*len(raw)).from_buffer_copy(raw);src=Blob(len(raw),buf);out=Blob()
    call=ctypes.windll.crypt32.CryptUnprotectData
    call.argtypes=[ctypes.POINTER(Blob),ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(Blob)]
    if not call(ctypes.byref(src),None,None,None,None,1,ctypes.byref(out)):
        raise OSError('cannot_decrypt_publisher_key_for_this_windows_user')
    try:return ctypes.string_at(out.data,out.size)
    finally:ctypes.windll.kernel32.LocalFree(ctypes.cast(out.data,ctypes.c_void_p))


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--key-dpapi',type=Path,required=True)
    p.add_argument('--installer',type=Path,required=True)
    p.add_argument('--url',required=True)
    p.add_argument('--version',required=True)
    p.add_argument('--sequence',type=int,required=True)
    p.add_argument('--output',type=Path,default=Path('release/latest.json'))
    args=p.parse_args()
    if not allowed(args.url):raise ValueError('invalid_release_url')
    key=Ed25519PrivateKey.from_private_bytes(unprotect(args.key_dpapi.read_bytes()))
    expected=json.loads((Path(__file__).parent/'update-trust.json').read_text(encoding='utf-8'))['public_key']
    actual=base64.b64encode(key.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw)).decode()
    if actual!=expected:raise ValueError('publisher_key_does_not_match_client_trust')
    raw=args.installer.read_bytes()
    manifest={'product':'codex-quota-guard','version':args.version,'sequence':args.sequence,
              'url':args.url,'size':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
    body=json.dumps(manifest,sort_keys=True,separators=(',',':')).encode()
    envelope={'payload':base64.b64encode(body).decode(),'signature':base64.b64encode(key.sign(body)).decode()}
    from updater import verify
    verify(envelope,expected)
    atomic_json(args.output,envelope)
    print(json.dumps({'signed':True,'version':args.version,'sequence':args.sequence,'sha256':manifest['sha256']}))


if __name__=='__main__':main()
