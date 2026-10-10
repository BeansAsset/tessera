"""Pairing and unlocking end to end, through the same text the shortcuts send."""

import os
import sys
import tempfile
import unittest
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fakephone import FakePhone  # noqa: E402
from tessera import gate as gate_module  # noqa: E402
from tessera.gate import Gate  # noqa: E402
from tessera.webauthn import FLAG_UP, Refused, b64url, pairing_code, unb64url  # noqa: E402


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def fragment(url):
    return dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).fragment))


class GateTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.dir.name, "devices.json")
        self.clock = Clock()
        self.unlocked, self.codes = [], []
        self.gate = self.make()
        self.phone = FakePhone()

    def tearDown(self):
        self.dir.cleanup()

    def make(self):
        return Gate(self.path, self.unlocked.append, self.codes.append, now=self.clock)

    def pair(self, phone=None, confirm=True):
        phone = phone or self.phone
        self.gate.start_pairing()
        c = unb64url(fragment(self.gate.start("Laptop"))["pair"])
        client, att = phone.create(c)
        self.gate.answer(".".join(["p", b64url(phone.credential_id), b64url(client), b64url(att)]))
        if confirm:
            self.assertTrue(self.gate.confirm(pairing_code(c, phone.credential_id)))
        return c

    def unlock_answer(self, phone=None, **sign):
        phone = phone or self.phone
        url = self.gate.start("Laptop")
        c = unb64url(fragment(url)["c"])
        auth, client, sig = phone.sign(c, **sign)
        return ".".join(["u", b64url(phone.credential_id), b64url(auth), b64url(client), b64url(sig)])

    def test_before_pairing_the_page_explains(self):
        self.assertIn("isn't paired", urllib.parse.unquote(fragment(self.gate.start("Laptop"))["error"]))

    def test_pair_then_unlock(self):
        self.pair()
        self.assertEqual(len(self.codes), 1)
        self.assertEqual(self.gate.answer(self.unlock_answer()), "Unlocked")
        self.assertEqual(len(self.unlocked), 1)

    def test_paired_devices_are_remembered_and_private(self):
        self.pair()
        self.assertEqual(oct(os.stat(self.path).st_mode & 0o777), "0o600")
        again = self.make()
        self.assertEqual(again.answer(self.unlock_answer_for(again)), "Unlocked")

    def unlock_answer_for(self, gate):
        c = unb64url(fragment(gate.start("Laptop"))["c"])
        auth, client, sig = self.phone.sign(c)
        return ".".join(["u", b64url(self.phone.credential_id), b64url(auth), b64url(client), b64url(sig)])

    def test_the_wrong_code_does_not_pair(self):
        c = self.pair(confirm=False)
        right = pairing_code(c, self.phone.credential_id)
        wrong = f"{(int(right) + 1) % 10000:04d}"
        self.assertFalse(self.gate.confirm(wrong))
        self.assertEqual(self.gate.device_list(), [])

    def test_pairing_closes_by_itself(self):
        self.gate.start_pairing()
        c = unb64url(fragment(self.gate.start("Laptop"))["pair"])
        self.clock.t += gate_module.PAIRING_LIFE + 1
        client, att = self.phone.create(c)
        with self.assertRaisesRegex(Refused, "pairing isn't open"):
            self.gate.answer(".".join(["p", b64url(self.phone.credential_id), b64url(client), b64url(att)]))

    def test_an_answer_works_only_once(self):
        self.pair()
        answer = self.unlock_answer()
        self.gate.answer(answer)
        with self.assertRaisesRegex(Refused, "unknown or expired"):
            self.gate.answer(answer)
        self.assertEqual(len(self.unlocked), 1)

    def test_a_slow_answer_expires(self):
        self.pair()
        answer = self.unlock_answer()
        self.clock.t += gate_module.CHALLENGE_LIFE + 1
        with self.assertRaisesRegex(Refused, "expired"):
            self.gate.answer(answer)

    def test_unpaired_phone_cannot_unlock(self):
        self.pair()
        with self.assertRaisesRegex(Refused, "isn't paired"):
            self.gate.answer(self.unlock_answer(phone=FakePhone()))
        self.assertEqual(self.unlocked, [])

    def test_no_face_id_no_unlock(self):
        self.pair()
        with self.assertRaisesRegex(Refused, "Face ID"):
            self.gate.answer(self.unlock_answer(flags=FLAG_UP))

    def test_a_flood_of_starts_is_bounded(self):
        self.pair()
        for _ in range(100):
            self.gate.start("Laptop")
        self.assertLessEqual(len(self.gate.open), gate_module.MAX_OPEN)

    def test_removed_phone_cannot_unlock(self):
        self.pair()
        self.gate.remove(b64url(self.phone.credential_id))
        url = self.gate.start("Laptop")
        self.assertIn("error", fragment(url))

    def test_nonsense_is_refused(self):
        for text in ("", "u.a.b", "x.1.2.3.4", "u.!!.@@.##.$$"):
            with self.assertRaises(Refused):
                self.gate.answer(text)


if __name__ == "__main__":
    unittest.main()
