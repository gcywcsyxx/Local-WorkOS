"""User-invoked launcher. Opens the app, never installs startup tasks."""
from __future__ import annotations
import argparse
import json
import shutil
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

ROOT=Path(__file__).resolve().parent
PORT=18866
URL=f'http://127.0.0.1:{PORT}'
DATA=Path(os.environ.get('LOCALAPPDATA',str(Path.home()/'.local'/'share')))/'LocalWorkOS'

def request(path,method='GET',data=None,token=''):
 headers={'Content-Type':'application/json'}
 if token:headers['X-CSRF-Token']=token
 req=urllib.request.Request(URL+path,data=json.dumps(data).encode() if data is not None else None,headers=headers,method=method)
 with urllib.request.urlopen(req,timeout=1.5) as response:return json.load(response)

def healthy():
 try:return request('/api/health').get('app')=='local-workos'
 except (OSError,ValueError):return False

def configure_saved_env(env):
 """Load only WorkOS-specific non-secret settings saved for this Windows user."""
 if os.name!='nt':return
 try:
  import winreg
  with winreg.OpenKey(winreg.HKEY_CURRENT_USER,'Environment') as key:
   for name in ('WORKOS_PUBLIC_AUTH_MODE','WORKOS_PUBLIC_ORIGIN','WORKOS_TUNNEL_ID','WORKOS_TUNNEL_CONFIG','WORKOS_CLOUDFLARED','WORKOS_SYNC_ROOT','WORKOS_LIBREOFFICE_CLI','WORKOS_NODE'):
    if not env.get(name):
     try:env[name]=str(winreg.QueryValueEx(key,name)[0])
     except OSError:pass
 except OSError:pass

def configure_sync_env(env):
 if env.get('WORKOS_SYNC_ROOT'):return
 one_drive=env.get('OneDriveCommercial') or env.get('OneDrive') or env.get('OneDriveConsumer')
 if not one_drive:return
 root=Path(one_drive)
 try:candidates=[item for item in root.iterdir() if item.is_dir() and 'AI Agent' in item.name]
 except OSError:return
 agent_root=candidates[0] if len(candidates)==1 else (root/'AI Agent' if (root/'AI Agent').is_dir() else None)
 if agent_root:env['WORKOS_SYNC_ROOT']=str(agent_root/'Local WorkOS')

def notify(message):
 if os.name=='nt':
  import ctypes
  ctypes.windll.user32.MessageBoxW(None,message,'Local WorkOS',0x10)
 else:print(message)

def main():
 parser=argparse.ArgumentParser(description='Launch Local WorkOS with an existing Python 3.11+.')
 parser.add_argument('--stop',action='store_true')
 parser.add_argument('--no-browser',action='store_true')
 parser.add_argument('--setup-password',action='store_true')
 parser.add_argument('--python',default=os.environ.get('WORKOS_PYTHON',sys.executable),help='Python executable path or command (default: current interpreter)')
 args=parser.parse_args()
 DATA.mkdir(parents=True,exist_ok=True)
 if args.stop:
  if healthy():
   info=request('/api/bootstrap');request('/api/shutdown','POST',{},info['csrf'])
  return 0
 if not healthy():
  env=dict(os.environ)
  configure_saved_env(env)
  configure_sync_env(env)
  env['PYTHONPATH']=str(ROOT/'vendor')+os.pathsep+env.get('PYTHONPATH','')
  env['PYTHONDONTWRITEBYTECODE']='1'
  bundled_root=Path(os.environ.get('LOCALAPPDATA',''))/'Programs'/'DeepSeek Harness'/'resources'/'app.asar.unpacked'/'dsh'/'node_modules'/'@deepseek-ai'
  bundled_cli=bundled_root/'libreoffice-kit'/'lib'/'cli.js'
  bundled_node=Path.home()/'.dsh'/'dsh-runtimes'/'dsh-primary-runtime'/'dependencies'/'node'/'bin'/'node.exe'
  if bundled_cli.is_file() and bundled_node.is_file():
   env.setdefault('WORKOS_LIBREOFFICE_CLI',str(bundled_cli));env.setdefault('WORKOS_NODE',str(bundled_node))
  selected=shutil.which(args.python)
  if not selected:
   notify('无法找到指定的 Python。请通过 --python 指定现有 Python 3.11+。');return 1
  executable=Path(selected)
  if os.name=='nt' and executable.with_name('pythonw.exe').exists():executable=executable.with_name('pythonw.exe')
  try:
   output=open(DATA/'launcher.log','w',encoding='utf-8')
   proc=subprocess.Popen([str(executable),'-m','workos.server','--port',str(PORT),'--data-dir',str(DATA)],cwd=ROOT,env=env,stdout=output,stderr=output,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
   output.close()
  except OSError as exc:
   notify('无法启动平台。请检查 Python 3.11 或更新版本是否安装。\n'+str(exc));return 1
  for _ in range(100):
   if healthy():break
   if proc.poll() is not None:
    notify('平台未能启动。请查看 '+str(DATA/'launcher.log')+'，或检查18866端口是否被其他程序占用。');return 1
   time.sleep(.15)
  else:
   proc.terminate();notify('启动超时，已停止本次启动的进程。请查看本机启动日志。');return 1
 if not args.no_browser:webbrowser.open(URL+'/auth/setup' if args.setup_password else URL)
 return 0

if __name__=='__main__':raise SystemExit(main())
