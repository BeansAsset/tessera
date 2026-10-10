"""The checks that decide whether a Face ID answer unlocks the laptop."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fakephone import FakePhone  # noqa: E402
from tessera import webauthn  # noqa: E402
from tessera.webauthn import FLAG_UP, Refused  # noqa: E402

RP, ORIGIN = "beansasset.github.io", "https://beansasset.github.io"


class PairThenUnlock(unittest.TestCase):
    def setUp(self):
        self.phone = FakePhone()
        challenge = os.urandom(32)
        client, att = self.phone.create(challenge)
        self.cred_id, self.pem, self.count = webauthn.verify_registration(client, att, challenge, RP, ORIGIN)

    def unlock(self, challenge, answer):
        return webauthn.verify_assertion(self.pem, self.count, *answer, challenge, RP, ORIGIN)

    def test_pairing_reads_the_key(self):
        self.assertEqual(self.cred_id, self.phone.credential_id)
        self.assertIn("BEGIN PUBLIC KEY", self.pem)

    def test_a_good_answer_unlocks(self):
        c = os.urandom(32)
        self.assertEqual(self.unlock(c, self.phone.sign(c)), 0)

    def test_answer_to_another_challenge_is_refused(self):
        with self.assertRaisesRegex(Refused, "challenge"):
            self.unlock(os.urandom(32), self.phone.sign(os.urandom(32)))

    def test_without_face_id_is_refused(self):
        c = os.urandom(32)
        with self.assertRaisesRegex(Refused, "Face ID"):
            self.unlock(c, self.phone.sign(c, flags=FLAG_UP))

    def test_another_website_is_refused(self):
        c = os.urandom(32)
        with self.assertRaisesRegex(Refused, "origin"):
            self.unlock(c, self.phone.sign(c, origin="https://evil.example"))

    def test_another_site_hash_is_refused(self):
        other = FakePhone(rp_id="evil.example")
        other.key, other.credential_id = self.phone.key, self.phone.credential_id
        c = os.urandom(32)
        with self.assertRaisesRegex(Refused, "different site"):
            self.unlock(c, other.sign(c))

    def test_a_different_phone_is_refused(self):
        c = os.urandom(32)
        with self.assertRaisesRegex(Refused, "signature"):
            self.unlock(c, FakePhone().sign(c))

    def test_tampered_data_is_refused(self):
        c = os.urandom(32)
        auth, client, sig = self.phone.sign(c)
        with self.assertRaisesRegex(Refused, "signature"):
            self.unlock(c, (auth[:33] + b"\x00\x00\x00\x09", client, sig))

    def test_counter_going_backwards_is_refused(self):
        self.phone.count = 5
        c = os.urandom(32)
        self.count = self.unlock(c, self.phone.sign(c))
        self.phone.count = 5
        c = os.urandom(32)
        with self.assertRaisesRegex(Refused, "counter"):
            self.unlock(c, self.phone.sign(c))

    def test_pairing_without_face_id_is_refused(self):
        c = os.urandom(32)
        client, att = FakePhone().create(c, flags=FLAG_UP)
        with self.assertRaisesRegex(Refused, "Face ID"):
            webauthn.verify_registration(client, att, c, RP, ORIGIN)

    def test_garbage_is_refused_not_crashing(self):
        c = os.urandom(32)
        for client, att in ((b"{", b""), (b'{"type":"webauthn.create"}', b"\xff"), (b"", b"\xa1")):
            with self.assertRaises(Refused):
                webauthn.verify_registration(client, att, c, RP, ORIGIN)

    def test_pairing_code_is_four_digits_and_stable(self):
        code = webauthn.pairing_code(b"abc", b"def")
        self.assertRegex(code, r"^\d{4}$")
        self.assertEqual(code, webauthn.pairing_code(b"abc", b"def"))


if __name__ == "__main__":
    unittest.main()
