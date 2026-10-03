import unittest
from tools.check_public_privacy import scan, PRIVATE_FILE


class PublicPrivacyTests(unittest.TestCase):
    def test_generated_credentials_are_detected_without_returning_values(self):
        samples = [b"ghp_" + b"A" * 36, b"github_pat_" + b"B" * 70,
                   b"sk-proj-" + b"C" * 40, b"AKIA" + b"D" * 16,
                   b"-----BEGIN " + b"PRIVATE KEY-----"]
        for sample in samples:
            with self.subTest(prefix=sample[:4]):
                matches = scan(b"line one\n" + sample)
                self.assertTrue(matches)
                self.assertEqual(matches[0][1], 2)
                self.assertNotIn(sample.decode(), repr(matches))

    def test_real_home_paths_fail_and_synthetic_examples_pass(self):
        self.assertTrue(scan(br"C:" + br"\Users\RealPerson\Documents\notes.txt"))
        self.assertTrue(scan(b"/home/" + b"real-person/private/data.json"))
        self.assertEqual(scan(br"C:\Users\synthetic-user\Documents\notes.txt"), [])
        self.assertEqual(scan(b"/home/synthetic-user/demo"), [])

    def test_local_literals_are_case_insensitive_and_redacted(self):
        matches = scan(b"visit PRIVATE-PERSON.EXAMPLE", (b"private-person.example",))
        self.assertEqual(matches, [("locally blocked personal literal", 1)])

    def test_runtime_authentication_data_is_never_source(self):
        for name in ("data/notes.json", ".env", ".env.local", "authentication/password-account.json",
                     "authentication/sessions.sqlite3", "exports/document.docx", "private.pem"):
            self.assertIsNotNone(PRIVATE_FILE.search(name))
        self.assertIsNone(PRIVATE_FILE.search("tests/test_password_auth.py"))
