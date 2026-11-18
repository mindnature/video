import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from videostudio import production
from videostudio.core import StudioError, selected_asset, asset_index, write_json


class DummyBrowser:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def preflight(self, references):
        self.calls.append("preflight")

    def generate(self, root, project, shot, references):
        self.calls.append("submit:" + shot["id"])
        if self.error:
            raise RuntimeError(self.error)
        return self.response


class RejectingPreflight(DummyBrowser):
    def preflight(self, references):
        raise StudioError("missing UI selector")


class ProductionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "film"
        self.state = production.start(self.root, "test idea", "handcraft", "Testing", 6, provider="template")
        project_file = self.root / "project.json"
        p = json.loads(project_file.read_text(encoding="utf-8"))
        p["shots"] = p["shots"][:1]
        p["shots"][0]["duration"] = 1
        p["shots"][0]["beats"] = [{"start": 0, "end": 0.9, "visual": "test"}]
        write_json(project_file, p)
        production.replan(self.root)
        self.sid = p["shots"][0]["id"]

    def ready(self, credits=1):
        production.approve(self.root, "storyboard")
        production.approve(self.root, "credits", max_generations=credits)

    def test_review_gate_before_any_browser_action(self):
        browser = DummyBrowser()
        with self.assertRaises(StudioError):
            production.advance(self.root, browser=browser)
        self.assertFalse(browser.calls)
        self.assertEqual(production.get_state(self.root)["shots"][self.sid]["attempts"], 0)

    def test_preflight_failure_does_not_reserve_credit(self):
        self.ready()
        with self.assertRaises(StudioError):
            production.advance(self.root, browser=RejectingPreflight())
        state = production.get_state(self.root)
        self.assertEqual(state["credits_remaining"], 1)
        self.assertEqual(state["shots"][self.sid]["attempts"], 0)

    def test_submission_failure_never_auto_retries(self):
        self.ready()
        browser = DummyBrowser(error="website changed")
        with self.assertRaises(StudioError):
            production.advance(self.root, browser=browser)
        state = production.get_state(self.root)
        self.assertEqual(state["phase"], "generation_uncertain")
        self.assertEqual(state["shots"][self.sid]["attempts"], 1)
        with self.assertRaises(StudioError):
            production.advance(self.root, browser=browser)
        self.assertEqual(browser.calls.count("submit:" + self.sid), 1)
        production.resolve_uncertain(self.root, self.sid, "retry")
        self.assertEqual(production.get_state(self.root)["phase"], "awaiting_extra_credit_approval")

    def test_manual_download_and_explicit_approval(self):
        self.ready()
        state = production.advance(self.root, browser=DummyBrowser())
        self.assertEqual(state["phase"], "awaiting_download")
        with self.assertRaises(StudioError):
            production.approve(self.root, "shot", shot_id=self.sid)
        # Tests do not need a valid video; ingest archives bytes and makes a best-effort preview.
        source = Path(self.tmp.name) / "test.mp4"
        source.write_bytes(b"mock video bytes")
        with patch("videostudio.production.probe", return_value={"streams": [{"codec_type": "video"}]}):
            production.receive(self.root, self.sid, source)
        state = production.approve(self.root, "shot", shot_id=self.sid)
        self.assertEqual(state["phase"], "ready_to_generate")
        self.assertEqual(state["shots"][self.sid]["status"], "approved")
        self.assertTrue(selected_asset(self.root, asset_index(self.root), "shots", self.sid).is_file())
        # Fake QA/render to exercise final approval logic without 1080p encoding in unit tests.
        out = self.root / "exports" / "final_master.mp4"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"mock master")
        with patch("videostudio.production.qa", return_value={"ready": True, "checks": []}), \
             patch("videostudio.production.render", return_value=out):
            state = production.advance(self.root, browser=DummyBrowser())
        self.assertEqual(state["phase"], "awaiting_final_approval")
        self.assertEqual(production.approve(self.root, "final")["phase"], "completed")

    def test_plan_digest_blocks_stale_approved_prompts(self):
        self.ready()
        project_file = self.root / "project.json"
        p = json.loads(project_file.read_text(encoding="utf-8"))
        p["shots"][0]["scene"] = "new scene"
        write_json(project_file, p)
        with self.assertRaises(StudioError):
            production.advance(self.root, browser=DummyBrowser())
        self.assertEqual(production.get_state(self.root)["credits_remaining"], 1)

    def test_reject_retains_candidate_and_requires_new_credit(self):
        self.ready()
        production.advance(self.root, browser=DummyBrowser())
        src = Path(self.tmp.name) / "scene.mp4"
        src.write_bytes(b"test")
        with patch("videostudio.production.probe", return_value={"streams": [{"codec_type": "video"}]}):
            production.receive(self.root, self.sid, src)
        state = production.reject_shot(self.root, self.sid, "Not natural enough")
        self.assertEqual(state["phase"], "awaiting_extra_credit_approval")
        self.assertEqual(len(state["shots"][self.sid]["candidates"]), 1)
        production.approve(self.root, "credits", max_generations=1)
        self.assertEqual(production.get_state(self.root)["credits_remaining"], 1)


if __name__ == "__main__":
    unittest.main()
