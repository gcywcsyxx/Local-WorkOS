import time,unittest
from types import SimpleNamespace
from unittest.mock import Mock
from workos.access_auth import AccessValidator
try:
    import jwt
    from cryptography.hazmat.primitives.asymmetric import rsa
except ImportError:
    jwt=None

class DefaultAccessTests(unittest.TestCase):
    def test_unconfigured_access_denies_even_a_forged_token(self):
        validator=AccessValidator()
        self.assertFalse(validator.configured)
        with self.assertRaises(PermissionError):validator.verify("forged")
    def test_arbitrary_issuer_hosts_cannot_be_configured(self):
        for team in ("https://evil.invalid","localhost:8080","team.example.invalid","../path"):
            self.assertFalse(AccessValidator(team,"aud").configured)

@unittest.skipIf(jwt is None,"Optional public-auth dependencies unavailable")
class SignedAccessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        cls.other=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    def setUp(self):
        self.client=Mock();self.client.get_signing_key_from_jwt.return_value=SimpleNamespace(key=self.key.public_key())
        self.validator=AccessValidator("synthetic-team","workos-aud",self.client)
        self.claims={"iss":"https://synthetic-team.cloudflareaccess.com","aud":["workos-aud"],"sub":"synthetic-user","iat":int(time.time())-10,"exp":int(time.time())+120}
    def token(self,claims=None,key=None):
        return jwt.encode(self.claims if claims is None else claims,self.key if key is None else key,algorithm="RS256",headers={"kid":"synthetic-key"})
    def test_valid_signed_application_token_passes(self):
        self.assertEqual(self.validator.verify(self.token())["sub"],"synthetic-user")
    def test_invalid_claims_are_rejected(self):
        cases=[{**self.claims,"aud":["different-app"]},{**self.claims,"iss":"https://other.cloudflareaccess.com"},{**self.claims,"exp":int(time.time())-1},{**self.claims,"iat":int(time.time())+120}]
        for missing in ("exp","iat","aud","iss","sub"):
            case=dict(self.claims);case.pop(missing);cases.append(case)
        for claims in cases:
            with self.subTest(claims=claims),self.assertRaises(PermissionError):self.validator.verify(self.token(claims))
    def test_wrong_signature_is_rejected(self):
        with self.assertRaises(PermissionError):self.validator.verify(self.token(key=self.other))
    def test_algorithm_confusion_is_rejected_before_key_fetch(self):
        token=jwt.encode(self.claims,"synthetic-hmac-secret-of-at-least-32-characters",algorithm="HS256",headers={"kid":"synthetic-key"})
        with self.assertRaises(PermissionError):self.validator.verify(token)
        self.client.get_signing_key_from_jwt.assert_not_called()
    def test_key_fetch_failure_does_not_leak_token_or_details(self):
        token=self.token();self.client.get_signing_key_from_jwt.side_effect=RuntimeError("synthetic internal detail")
        with self.assertRaises(PermissionError) as caught:self.validator.verify(token)
        self.assertNotIn(token,str(caught.exception));self.assertNotIn("internal detail",str(caught.exception))
    def test_missing_and_oversize_tokens_are_denied(self):
        for token in ("",None,"X"*16385):
            with self.subTest(token_type=type(token).__name__),self.assertRaises(PermissionError):self.validator.verify(token)
        self.client.get_signing_key_from_jwt.assert_not_called()
