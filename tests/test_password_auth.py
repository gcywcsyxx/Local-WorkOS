import json,tempfile,unittest
from pathlib import Path
from workos.password_auth import PasswordAuth,TooManyLogins,SESSION_COOKIE

PASSWORD="Synthetic-Password-2026!"
class PasswordAuthTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.now=1000000.;self.auth=PasswordAuth(Path(self.tmp.name)/"authentication",clock=lambda:self.now)
    def login(self,password=PASSWORD):
        nonce=self.auth.issue_challenge("synthetic-ip")
        return self.auth.login("workos-user",password,"synthetic-ip",nonce,nonce,True)[0]
    def test_password_is_hashed_and_remains_available_after_restart(self):
        self.auth.configure_password(PASSWORD)
        text=self.auth.account_file.read_text();self.assertNotIn(PASSWORD,text)
        data=json.loads(text);self.assertNotEqual(data["salt"],data["digest"])
        restarted=PasswordAuth(self.auth.directory,clock=lambda:self.now)
        self.assertTrue(restarted.configured)
    def test_session_survives_restart_but_only_digest_is_saved(self):
        self.auth.configure_password(PASSWORD);token=self.login()
        cookie=SESSION_COOKIE+"="+token
        restarted=PasswordAuth(self.auth.directory,clock=lambda:self.now)
        self.assertEqual(restarted.get_session(cookie)["username"],"workos-user")
        self.assertNotIn(token.encode(),self.auth.session_file.read_bytes())
    def test_expiry_and_logout_invalidate_session(self):
        self.auth.configure_password(PASSWORD);token=self.login();cookie=SESSION_COOKIE+"="+token
        self.assertIsNotNone(self.auth.get_session(cookie))
        self.auth.logout(cookie);self.assertIsNone(self.auth.get_session(cookie))
        token=self.login();self.now+=8*86400
        self.assertIsNone(self.auth.get_session(SESSION_COOKIE+"="+token))
    def test_reset_invalidates_old_sessions(self):
        self.auth.configure_password(PASSWORD);token=self.login()
        self.auth.configure_password("Another-Synthetic-Password!")
        self.assertIsNone(self.auth.get_session(SESSION_COOKIE+"="+token))
    def test_nonce_cookie_and_ip_must_match(self):
        self.auth.configure_password(PASSWORD);nonce=self.auth.issue_challenge("ip")
        for ip,token,cookie in (("other",nonce,nonce),("ip",nonce,"bad"),("ip","unknown","unknown")):
            with self.assertRaises(PermissionError):self.auth.login("workos-user",PASSWORD,ip,token,cookie)
    def test_bruteforce_is_limited(self):
        self.auth.configure_password(PASSWORD)
        for i in range(5):
            with self.assertRaises(PermissionError):self.login("Wrong-Synthetic-Password!")
        with self.assertRaises(TooManyLogins):self.login()
        self.now+=601;self.assertTrue(self.login())
    def test_missing_account_and_short_password_deny(self):
        self.assertFalse(self.auth.configured)
        with self.assertRaises(ValueError):self.auth.configure_password("weak")
        with self.assertRaises(PermissionError):self.login()
    def test_secure_cookie_attributes(self):
        cookie=self.auth.session_cookie("opaque",60)
        for flag in ("__Host-","Secure","HttpOnly","SameSite=Lax","Path=/"):self.assertIn(flag,cookie)
