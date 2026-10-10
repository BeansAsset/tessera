"""How the phone's reply can arrive: raw, JSON or form, whatever the label says."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tessera.server import read_answer  # noqa: E402

ANSWER = "u.abc.def.ghi.jkl"


class ReadAnswerTest(unittest.TestCase):
    def test_raw_with_any_label(self):
        for label in (None, "application/octet-stream", "text/plain", "application/x-www-form-urlencoded"):
            self.assertEqual(read_answer(ANSWER.encode(), label), ANSWER)

    def test_json(self):
        self.assertEqual(read_answer(b'{"answer": "%s"}' % ANSWER.encode(), "application/json"), ANSWER)

    def test_form(self):
        self.assertEqual(read_answer(b"answer=" + ANSWER.encode(), "application/x-www-form-urlencoded"), ANSWER)


if __name__ == "__main__":
    unittest.main()
