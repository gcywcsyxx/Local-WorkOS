"""Local hashed password account and opaque persistent HTTPS sessions."""
import base64,hashlib,hmac,json,os,secrets,sqlite3,threading,time
from pathlib import Path
from contextlib import contextmanager
from http.cookies import SimpleCookie,CookieError

SESSION_COOKIE="__Host-workos-session"
CHALLENGE_COOKIE="__Host-workos-login"
class LoginRequired(PermissionError):pass
class TooManyLogins(PermissionError):pass

def cookie_value(header,name):
    if not isinstance(header,str) or len(header)>8192:return ""
    try:
        cookies=SimpleCookie();cookies.load(header)
        return cookies[name].value if name in cookies else ""
    except CookieError:return ""

class PasswordAuth:
    iterations=600000
    def __init__(self,directory,clock=time.time):
        self.directory=Path(directory);self.account_file=self.directory/"password-account.json"
        self.session_file=self.directory/"sessions.sqlite3"
        self.clock=clock;self.lock=threading.RLock();self.challenges={};self.failures={};self.global_failures=[]
        self.account=None
        try:
            data=json.loads(self.account_file.read_text(encoding="utf-8"))
            if not isinstance(data,dict):raise ValueError("Invalid account")
            if data.get("username")!="workos-user" or data.get("iterations")!=self.iterations:raise ValueError("Invalid account")
            if len(base64.b64decode(data["salt"],validate=True))!=16 or len(base64.b64decode(data["digest"],validate=True))!=32:raise ValueError("Invalid hash")
            self.account=data
        except (OSError,ValueError,KeyError,TypeError):pass
    @property
    def configured(self):return self.account is not None
    @property
    def generation(self):
        return hashlib.sha256((self.account["salt"]+self.account["digest"]).encode()).hexdigest() if self.account else ""
    @contextmanager
    def database(self):
        self.directory.mkdir(parents=True,exist_ok=True)
        with self.lock:
            db=sqlite3.connect(self.session_file,timeout=5)
            try:
                db.execute("CREATE TABLE IF NOT EXISTS sessions (digest TEXT PRIMARY KEY,csrf TEXT NOT NULL,expires REAL NOT NULL,generation TEXT NOT NULL)")
                yield db;db.commit()
            finally:db.close()
    def configure_password(self,password):
        if not isinstance(password,str) or not 8<=len(password)<=128 or not password.strip():raise ValueError("密码需8至128个字符，建议使用至少12字符的独立密码")
        salt=secrets.token_bytes(16)
        derived=hashlib.pbkdf2_hmac("sha256",password.encode(),salt,self.iterations)
        data={"version":1,"username":"workos-user","iterations":self.iterations,"salt":base64.b64encode(salt).decode(),"digest":base64.b64encode(derived).decode()}
        with self.lock:
            self.directory.mkdir(parents=True,exist_ok=True)
            temp=self.account_file.with_name("password-account.tmp-"+secrets.token_hex(6))
            try:
                with temp.open("w",encoding="utf-8") as stream:json.dump(data,stream);stream.flush();os.fsync(stream.fileno())
                if os.name!="nt":os.chmod(temp,0o600)
                os.replace(temp,self.account_file)
            finally:temp.unlink(missing_ok=True)
            self.account=data;self.challenges.clear();self.failures.clear();self.global_failures.clear()
            with self.database() as db:db.execute("DELETE FROM sessions")
    def issue_challenge(self,ip):
        nonce=secrets.token_urlsafe(32);now=self.clock()
        with self.lock:
            self.challenges={key:value for key,value in self.challenges.items() if value[0]>now}
            if len(self.challenges)>=1024:self.challenges.pop(next(iter(self.challenges)))
            self.challenges[nonce]=(now+300,str(ip)[:64])
        return nonce
    def login(self,username,password,ip,nonce,cookie_nonce,remember=False):
        if not self.configured:raise PermissionError("账号尚未初始化，请先在本机设置密码")
        now=self.clock();ip=str(ip)[:64]
        with self.lock:
            self.failures={key:[t for t in values if t>now-600] for key,values in self.failures.items() if values and values[-1]>now-600}
            self.global_failures=[t for t in self.global_failures if t>now-600]
            if len(self.failures.get(ip,[]))>=5 or len(self.global_failures)>=50:raise TooManyLogins("登录尝试过多，请10分钟后重试")
            challenge=self.challenges.get(nonce) if isinstance(nonce,str) else None
            if not challenge or challenge[0]<=now or challenge[1]!=ip or not isinstance(cookie_nonce,str) or not hmac.compare_digest(nonce,cookie_nonce):raise PermissionError("登录会话已过期，请刷新登录页")
            if not isinstance(password,str) or len(password)>128:raise PermissionError("用户名或密码不正确")
            derived=hashlib.pbkdf2_hmac("sha256",password.encode(),base64.b64decode(self.account["salt"]),self.iterations)
            correct=hmac.compare_digest(derived,base64.b64decode(self.account["digest"])) and username=="workos-user"
            if not correct:
                self.failures.setdefault(ip,[]).append(now);self.global_failures.append(now)
                raise PermissionError("用户名或密码不正确")
            self.challenges.pop(nonce,None);self.failures.pop(ip,None)
            token=secrets.token_urlsafe(32);digest=hashlib.sha256(token.encode()).hexdigest();csrf=secrets.token_urlsafe(32)
            seconds=7*86400 if remember else 12*3600
            with self.database() as db:
                db.execute("DELETE FROM sessions WHERE expires<=?",(now,))
                if db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]>=128:db.execute("DELETE FROM sessions WHERE digest=(SELECT digest FROM sessions ORDER BY expires LIMIT 1)")
                db.execute("INSERT INTO sessions VALUES (?,?,?,?)",(digest,csrf,now+seconds,self.generation))
            return token,seconds
    def get_session(self,cookie_header):
        token=cookie_value(cookie_header,SESSION_COOKIE)
        if not self.configured or not 24<=len(token)<=128:return None
        digest=hashlib.sha256(token.encode()).hexdigest()
        with self.database() as db:
            db.execute("DELETE FROM sessions WHERE expires<=?",(self.clock(),))
            row=db.execute("SELECT csrf,expires,generation FROM sessions WHERE digest=?",(digest,)).fetchone()
        if row is None or not hmac.compare_digest(row[2],self.generation):return None
        return {"csrf":row[0],"expires":row[1],"username":"workos-user"}
    def logout(self,cookie_header):
        token=cookie_value(cookie_header,SESSION_COOKIE)
        if token:
            with self.database() as db:db.execute("DELETE FROM sessions WHERE digest=?",(hashlib.sha256(token.encode()).hexdigest(),))
    @staticmethod
    def session_cookie(token,seconds):
        return SESSION_COOKIE+"="+token+"; Path=/; Secure; HttpOnly; SameSite=Lax; Max-Age="+str(seconds)
    @staticmethod
    def challenge_cookie(nonce):
        return CHALLENGE_COOKIE+"="+nonce+"; Path=/; Secure; HttpOnly; SameSite=Strict; Max-Age=300"
