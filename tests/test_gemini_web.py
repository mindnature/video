import json
import tempfile
import unittest
from pathlib import Path

from videostudio import production
from videostudio.core import StudioError
from videostudio.gemini_browser import (extract_project, director_prompt, load_gemini_ui)
from videostudio.templates import preset


class FakeGemini:
    def __init__(self, fail=False):
        self.fail = fail
        self.preflight_calls = 0
        self.generate_calls = 0

    def preflight(self, references):
        self.preflight_calls += 1

    def generate_plan(self, idea, mode, title, shots, references):
        self.generate_calls += 1
        if self.fail:
            raise RuntimeError("website timed out after send")
        return preset(mode, title)


class GeminiWebTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "test-film"

    def test_default_web_succeeds_to_storyboard_gate_without_api_key(self):
        web = FakeGemini()
        state = production.start(self.root, "花瓣真实手工", "handcraft", "花影", 6,
                                 provider="gemini-web", gemini_browser=web)
        self.assertEqual(state["phase"], "awaiting_storyboard_approval")
        self.assertEqual(state["provider"], "gemini-web")
        self.assertEqual(web.generate_calls, 1)
        self.assertTrue((self.root / "production/storyboard.md").exists())
        self.assertEqual(len(state["shots"]), 6)
        self.assertEqual(state["credits_remaining"], 0)

    def test_failed_website_submission_never_automatically_retries(self):
        web = FakeGemini(fail=True)
        with self.assertRaises(StudioError):
            production.start(self.root, "真实花瓣", "handcraft", "花影", 6,
                             provider="gemini-web", gemini_browser=web)
        state = production.get_state(self.root)
        self.assertEqual(state["phase"], "gemini_submission_uncertain")
        self.assertEqual(state["gemini_attempts"], 1)
        with self.assertRaises(StudioError):
            production.generate_gemini(self.root, browser=web)
        self.assertEqual(web.generate_calls, 1)
        production.resolve_gemini(self.root, "retry")
        good = FakeGemini()
        state = production.generate_gemini(self.root, browser=good)
        self.assertEqual(state["phase"], "awaiting_storyboard_approval")
        self.assertEqual(state["gemini_attempts"], 2)

    def test_receive_gemini_after_failed_browser(self):
        with self.assertRaises(StudioError):
            production.start(self.root, "photo", "handcraft", "花影", 6,
                             provider="gemini-web", gemini_browser=FakeGemini(fail=True))
        path = Path(self.tmp.name) / "verified.json"
        path.write_text(json.dumps(preset("handcraft", "花影"), ensure_ascii=False), encoding="utf-8")
        state = production.receive_gemini(self.root, path)
        self.assertEqual(state["phase"], "awaiting_storyboard_approval")
        self.assertEqual(state["gemini_attempts"], 1)
        with self.assertRaises(StudioError):
            production.receive_gemini(self.root, path)

    def test_extract_strict_json_and_schema(self):
        valid = json.dumps(preset("story", "西游"), ensure_ascii=False)
        self.assertEqual(len(extract_project("```json\n" + valid + "\n```", "story", 5)["shots"]), 5)
        for invalid in ["irrelevant " + valid, valid + " extra", '{"shots":[]}']:
            with self.assertRaises(StudioError):
                extract_project(invalid, "story", 5)
        with self.assertRaises(StudioError):
            extract_project(valid, "handcraft", 5)

    def test_local_cdp_only(self):
        config = Path(self.tmp.name) / "unsafe.json"
        config.write_text('{"cdp_url":"http://192.168.1.10:9222"}')
        with self.assertRaises(StudioError):
            load_gemini_ui(config)
        self.assertIn("JSON", director_prompt("some idea", "handcraft", "Title", 6, 1))


if __name__ == "__main__":
    unittest.main()
