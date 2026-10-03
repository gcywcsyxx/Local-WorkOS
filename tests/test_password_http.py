import http.client,io,json,re,tempfile,threading,unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from workos.server import Application,Handler
from workos.password_auth import PasswordAuth

PASSWORD="Synthetic-Password-2026!"
class PasswordHttpTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        with patch("workos.server.find_root",return_value=None),patch.dict("os.environ",{"WORKOS_SYNC_ROOT":"","WORKOS_PUBLIC_ORIGIN":"https://workos.example.invalid","WORKOS_PUBLIC_AUTH_MODE":"password"}):
            self.app=Application(Path(self.tmp.name)/"data",port=0)
        self.httpd=ThreadingHTTPServer(("127.0.0.1",0),Handler);self.httpd.daemon_threads=True
        self.app.port=self.httpd.server_address[1];self.httpd.app=self.app
        self.thread=threading.Thread(target=self.httpd.serve_forever,kwargs={"poll_interval":.02},daemon=True);self.thread.start()
    def tearDown(self):
        self.httpd.shutdown();self.httpd.server_close();self.thread.join(3)
        for store in self.app.stores.values():store.close()
        self.tmp.cleanup()
    def request(self,path,method="GET",body=None,public=True,cookie="",csrf="",extra=None):
        h={"X-Workspace":"demo"}
        if public:h.update({"Host":"workos.example.invalid","Origin":"https://workos.example.invalid"})
        if cookie:h["Cookie"]=cookie
        if csrf:h["X-CSRF-Token"]=csrf
        if body is not None:h["Content-Type"]="application/json"
        h.update(extra or {})
        conn=http.client.HTTPConnection("127.0.0.1",self.app.port,timeout=10)
        try:
            conn.request(method,path,json.dumps(body).encode() if body is not None else None,h)
            response=conn.getresponse();raw=response.read();return response.status,raw,dict(response.getheaders())
        finally:conn.close()
    def setup_password(self):
        status,body,_=self.request("/auth/setup",public=False)
        self.assertEqual(status,200)
        nonce=re.search(rb'id="csrf" value="([^"]+)"',body).group(1).decode()
        status,body,_=self.request("/auth/setup","POST",{"password":PASSWORD},public=False,csrf=nonce)
        self.assertEqual(status,200,body)
    def login(self,password=PASSWORD):
        status,page,headers=self.request("/auth/login");self.assertEqual(status,200)
        nonce=re.search(rb'id="csrf" value="([^"]+)"',page).group(1).decode()
        challenge=headers["Set-Cookie"].split(";")[0]
        return self.request("/auth/login","POST",{"username":"workos-user","password":password,"remember":True},cookie=challenge,csrf=nonce)
    def test_anonymous_all_private_routes_are_protected(self):
        for path in ("/api/bootstrap","/api/state","/api/backup","/api/sync/status","/api/memory/scan","/api/agent/tools","/api/documents/no-such","/api/export/no-such?format=docx"):
            with self.subTest(path=path):self.assertEqual(self.request(path)[0],401)
        status,body,headers=self.request("/");self.assertEqual(status,303);self.assertEqual(headers["Location"],"/auth/login")
        self.assertEqual(self.request("/auth/ui.js")[0],200)
    def test_remote_setup_is_never_allowed(self):
        self.assertEqual(self.request("/auth/setup")[0],403)
        self.assertEqual(self.request("/auth/setup","POST",{"password":PASSWORD},csrf=self.app.csrf)[0],403)
        self.assertEqual(self.request("/auth/setup",public=False,extra={"Cf-Connecting-IP":"198.51.100.1"})[0],403)
        self.assertFalse(self.app.password_auth.configured)
    def test_local_setup_requires_csrf_and_stores_no_plaintext(self):
        self.assertEqual(self.request("/auth/setup","POST",{"password":PASSWORD},public=False)[0],403)
        self.setup_password();self.assertNotIn(PASSWORD,self.app.password_auth.account_file.read_text())
    def test_login_session_csrf_logout_and_restart(self):
        self.setup_password();status,raw,headers=self.login();self.assertEqual(status,200,raw)
        cookie=headers["Set-Cookie"].split(";")[0]
        for flag in ("Secure","HttpOnly","SameSite=Lax","Max-Age=604800"):self.assertIn(flag,headers["Set-Cookie"])
        status,raw,_=self.request("/api/bootstrap",cookie=cookie);self.assertEqual(status,200)
        boot=json.loads(raw);self.assertNotEqual(boot["csrf"],self.app.csrf)
        self.assertTrue(boot["auth"]["public_login"])
        self.app.password_auth=PasswordAuth(self.app.password_auth.directory)
        self.assertEqual(self.request("/api/state",cookie=cookie)[0],200)
        self.assertEqual(self.request("/api/projects","POST",{"name":"Synthetic"},cookie=cookie)[0],403)
        self.assertEqual(self.request("/api/projects","POST",{"name":"Synthetic"},cookie=cookie,csrf=boot["csrf"])[0],201)
        self.assertEqual(self.request("/auth/logout","POST",{},cookie=cookie,csrf=boot["csrf"])[0],200)
        self.assertEqual(self.request("/api/state",cookie=cookie)[0],401)
    def test_bad_password_and_login_nonce_are_rejected(self):
        self.setup_password();self.assertEqual(self.login("Wrong-Synthetic-Password!")[0],403)
        self.assertEqual(self.request("/auth/login","POST",{"username":"workos-user","password":PASSWORD})[0],403)
        for i in range(4):self.assertEqual(self.login("Wrong-Synthetic-Password!")[0],403)
        self.assertEqual(self.login()[0],429)
    def test_cross_site_login_and_write_are_rejected(self):
        self.setup_password()
        self.assertEqual(self.request("/auth/login","POST",{"username":"workos-user","password":PASSWORD},extra={"Origin":"https://evil.invalid"})[0],403)
        self.assertEqual(self.request("/auth/login","POST",{"username":"workos-user","password":PASSWORD},extra={"Origin":"http://workos.example.invalid"})[0],403)
    def test_local_app_remains_usable_without_public_session(self):
        self.assertEqual(self.request("/api/health",public=False)[0],200)
        self.assertEqual(self.request("/api/state",public=False)[0],200)
    def test_uninitialized_public_account_cannot_login_or_read_data(self):
        self.assertEqual(self.request("/api/state")[0],401)
        self.assertEqual(self.login()[0],403)
    def test_public_login_does_not_disclose_configured_username(self):
        self.setup_password()
        data=json.loads(self.app.password_auth.account_file.read_text())
        data["username"]="legacy-account"
        self.app.password_auth.account_file.write_text(json.dumps(data))
        self.app.password_auth=PasswordAuth(self.app.password_auth.directory)
        status,page,headers=self.request("/auth/login")
        self.assertEqual(status,200)
        self.assertNotIn(b"legacy-account",page)
        self.assertIn(b'name="username" value=""',page)
        nonce=re.search(rb'id="csrf" value="([^"]+)"',page).group(1).decode()
        challenge=headers["Set-Cookie"].split(";")[0]
        status,_,headers=self.request("/auth/login","POST",{"username":"legacy-account","password":PASSWORD},cookie=challenge,csrf=nonce)
        self.assertEqual(status,200)
        status,body,_=self.request("/api/bootstrap",cookie=headers["Set-Cookie"].split(";")[0])
        self.assertEqual(status,200)
        self.assertEqual(json.loads(body)["auth"]["username"],"legacy-account")
