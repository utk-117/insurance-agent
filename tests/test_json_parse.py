import unittest

from app.adapters.base import check_required, extract_json


class TestExtractJson(unittest.TestCase):
    def test_plain(self):
        self.assertEqual(extract_json('{"a": 1}'), {"a": 1})

    def test_fenced(self):
        self.assertEqual(extract_json('```json\n{"a": "x"}\n```'), {"a": "x"})

    def test_prose_and_think(self):
        s = '<think>{"no": 1}</think>Sure! Here it is: {"reply": "hi {there}", "n": {"x": 2}} thanks'
        self.assertEqual(extract_json(s), {"reply": "hi {there}", "n": {"x": 2}})

    def test_skips_broken_first_object(self):
        self.assertEqual(extract_json('{bad} then {"ok": true}'), {"ok": True})

    def test_no_json(self):
        with self.assertRaises(ValueError):
            extract_json("sorry, I can't")

    def test_required(self):
        with self.assertRaises(ValueError):
            check_required({"a": 1}, {"required": ["a", "b"]})


if __name__ == "__main__":
    unittest.main()
