"""Fail-closed Cloudflare Access verification for the optional public origin."""
import re

class AccessValidator:
    def __init__(self,team="",audience="",client=None):
        self.team=str(team or "").strip().lower();self.audience=str(audience or "").strip()
        self.issuer="";self.client=None;self.jwt=None
        if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?",self.team) or not self.audience or len(self.audience)>512:return
        self.issuer="https://"+self.team+".cloudflareaccess.com"
        try:
            import jwt
            from cryptography.hazmat.primitives.asymmetric import rsa
            self.jwt=jwt
            self.client=client if client is not None else jwt.PyJWKClient(self.issuer+"/cdn-cgi/access/certs",cache_keys=False,cache_jwk_set=True,lifespan=300,timeout=5)
        except ImportError:
            # Optional dependencies missing: public traffic remains denied.
            self.jwt=None;self.client=None
    @property
    def configured(self):return bool(self.jwt and self.client and self.issuer and self.audience)
    def verify(self,token):
        if not self.configured:raise PermissionError("公网入口尚未配置可验证的Cloudflare Access保护")
        if not isinstance(token,str) or not token or len(token)>16384:raise PermissionError("请先通过Cloudflare Access登录")
        try:
            header=self.jwt.get_unverified_header(token)
            if header.get("alg")!="RS256" or not isinstance(header.get("kid"),str) or not 1<=len(header["kid"])<=256:raise ValueError("Invalid header")
            key=self.client.get_signing_key_from_jwt(token).key
            return self.jwt.decode(token,key,algorithms=["RS256"],audience=self.audience,issuer=self.issuer,options={"require":["exp","iat","iss","aud","sub"]})
        except Exception as exc:
            # Never expose JWT, key material, email claims or raw dependency errors.
            raise PermissionError("Cloudflare Access登录验证失败或已过期") from exc
