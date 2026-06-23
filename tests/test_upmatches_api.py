import unittest

from app.upmatches_api import generate_totp


class UpmatchesApiTest(unittest.TestCase):
    def test_generate_totp_uses_standard_sha1_totp(self):
        # RFC 6238 SHA1 test secret. The RFC displays 8 digits; this service
        # uses the standard 6-digit truncation of the same value.
        self.assertEqual(generate_totp("GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ", now=59), "287082")


if __name__ == "__main__":
    unittest.main()
