"""Start only the explicitly configured dedicated password-protected WorkOS tunnel."""
import base64,json,os,re,subprocess,sys,urllib.request,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def main():
    env={key:value for key,value in os.environ.items() if key.lower() not in ("http_proxy","https_proxy","no_proxy","all_proxy")}
    sys.path.insert(0,str(ROOT))
    from launch import configure_saved_env
    configure_saved_env(env)
    config=Path(env.get("WORKOS_TUNNEL_CONFIG") or str(Path.home()/".cloudflared"/"config-workos.yml"))
    tunnel_id=env.get("WORKOS_TUNNEL_ID","")
    if not tunnel_id or str(uuid.UUID(tunnel_id))!=tunnel_id:raise ValueError("Dedicated tunnel UUID must be configured")
    if env.get("WORKOS_PUBLIC_AUTH_MODE")!="password" or not env.get("WORKOS_PUBLIC_ORIGIN","").startswith("https://"):raise ValueError("Password-protected HTTPS public origin must be configured")
    cf=Path(env.get("WORKOS_CLOUDFLARED") or str(Path(env.get("ProgramFiles(x86)","C:/Program Files (x86)"))/"cloudflared"/"cloudflared.exe"))
    if not config.is_file() or not cf.is_file():raise ValueError("Dedicated connector configuration or executable unavailable")
    configured_id=re.search(r"(?m)^tunnel:[ \t]*([a-z0-9-]+)[ \t]*$",config.read_text(encoding="utf-8"))
    if not configured_id or configured_id.group(1)!=tunnel_id:raise ValueError("Connector config does not match the dedicated tunnel UUID")
    subprocess.run([sys.executable,str(ROOT/"launch.py"),"--no-browser"],env=env,cwd=ROOT,check=True,timeout=25)
    with urllib.request.urlopen("http://127.0.0.1:18866/api/public/status",timeout=3) as response:status=json.load(response)
    if status.get("auth_mode")!="password" or status.get("origin")!=env["WORKOS_PUBLIC_ORIGIN"].rstrip("/"):raise ValueError("Running app does not enforce the configured password authentication")
    local=Path(env.get("LOCALAPPDATA",str(Path.home()/".local"/"share")))/"LocalWorkOS"/"tunnel";local.mkdir(parents=True,exist_ok=True)
    pid_file=local/"workos.pid"
    if pid_file.is_file() and os.name=="nt":
        try:
            pid=int(pid_file.read_text().strip())
            script="$p=Get-CimInstance Win32_Process -Filter 'ProcessId="+str(pid)+"'; [bool]($p.Name -eq 'cloudflared.exe' -and $p.CommandLine -like '*"+tunnel_id+"*')"
            encoded=base64.b64encode(script.encode("utf-16-le")).decode()
            probe=subprocess.run(["powershell.exe","-NoProfile","-EncodedCommand",encoded],env=env,capture_output=True,text=True,timeout=10)
            if probe.stdout.strip().lower()=="true":print(json.dumps({"already_running":True,"pid":pid}));return
        except (ValueError,OSError,subprocess.TimeoutExpired):pass
    with (local/"connector.stdout.log").open("ab") as out,(local/"connector.stderr.log").open("ab") as error:
        process=subprocess.Popen([str(cf),"--config",str(config),"tunnel","run",tunnel_id],env=env,cwd=config.parent,stdin=subprocess.DEVNULL,stdout=out,stderr=error,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
    pid_file.write_text(str(process.pid),encoding="ascii")
    print(json.dumps({"started":True,"pid":process.pid,"password_configured":status.get("password_configured",False)}))
if __name__=="__main__":
    try:main()
    except Exception as error:print("Public connector failed: "+str(error),file=sys.stderr);raise SystemExit(1)
