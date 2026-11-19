"""V1.4 strict Flow provenance, performance, dubbing and ledger regression tests."""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from videostudio import production
from videostudio.core import StudioError, write_json, digest
from videostudio.delivery import (
    approve_voice, credit_ledger, delivery_audit, frame_motion_probe,
    register_voice_audition, save_delivery_report, voice_guide,
)
from videostudio.templates import preset


class Browser:
    def __init__(self, media=None):
        self.media = media
        self.calls = []
    def preflight(self, references):
        self.calls.append("preflight")
    def generate(self, root, project, shot, references):
        self.calls.append("submit")
        return self.media


class StrictFlowTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name) / "demo"
        production.start(self.root, "short clip", "general", "Demo", 4,
                         provider="template", delivery_mode="flow_dynamic")
        project = json.loads((self.root / "project.json").read_text(encoding="utf-8"))
        project["shots"] = project["shots"][:1]
        project["shots"][0]["duration"] = 1
        project["shots"][0]["beats"] = [{"start": 0, "end": .8, "visual": "perform visible gesture"}]
        write_json(self.root / "project.json", project)
        production.replan(self.root)
        self.sid = project["shots"][0]["id"]
        production.approve(self.root, "storyboard")
        production.approve(self.root, "credits", max_generations=1)
        self.media = Path(self.folder.name) / "shot.mp4"
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                        "testsrc2=size=128x72:rate=15:duration=1", "-f", "lavfi", "-i",
                        "anullsrc=r=48000:cl=stereo", "-t", "1", "-c:v", "libx264",
                        "-pix_fmt", "yuv420p", "-c:a", "aac", str(self.media)], check=True)

    def test_strict_auto_flow_requires_actual_motion_signoff(self):
        st = production.advance(self.root, browser=Browser(self.media))
        self.assertEqual(st["phase"], "awaiting_shot_approval")
        self.assertEqual(st["shots"][self.sid]["candidate_evidence"][st["shots"][self.sid]["candidates"][-1]]["origin"], "flow_browser")
        production.verify_shot(self.root, self.sid, "pass", "reviewed appearance and lip movements")
        with self.assertRaisesRegex(StudioError, "motion"):
            production.approve(self.root, "shot", shot_id=self.sid)
        production.verify_shot(self.root, self.sid, "pass", "subject visibly moves, not camera only", motion="pass")
        production.approve(self.root, "shot", shot_id=self.sid)
        report = delivery_audit(self.root, json.loads((self.root / "project.json").read_text()), production.get_state(self.root))
        self.assertTrue(report["ready"], report)
        self.assertEqual(report["credits"]["authorized"], 1)
        self.assertEqual(report["credits"]["reserved_possible_spend"], 1)
        self.assertEqual(report["credits"]["visible_clicks_observed"], 0)  # injected test browser
        self.assertEqual(report["shots"][0]["technical_frame_probe"]["status"], "ok")
        # Actual final rendering is covered by V1.3 media integration tests.
        expected_master = self.root / "exports" / "final_master.mp4"
        expected_master.parent.mkdir(parents=True, exist_ok=True)
        expected_master.write_bytes(b"master stub")
        with patch("videostudio.production.qa", return_value={"ready": True, "checks": []}), \
             patch("videostudio.production.render", return_value=expected_master):
            state = production.advance(self.root, browser=Browser(self.media))
            self.assertEqual(state["phase"], "awaiting_final_approval")
        self.assertEqual(production.approve(self.root, "final")["phase"], "completed")

    def test_manual_media_not_silently_equated_to_flow(self):
        production.advance(self.root, browser=Browser())
        production.receive(self.root, self.sid, self.media, from_flow=False)
        production.verify_shot(self.root, self.sid, "pass", "I watched this real actor moving", motion="pass")
        with self.assertRaisesRegex(StudioError, "Flow source"):
            production.approve(self.root, "shot", shot_id=self.sid)

    def test_manual_flow_attestation_is_labeled_unverified(self):
        production.advance(self.root, browser=Browser())
        production.receive(self.root, self.sid, self.media, from_flow=True)
        production.verify_shot(self.root, self.sid, "pass", "real subject movement checked", motion="pass")
        production.approve(self.root, "shot", shot_id=self.sid)
        report = delivery_audit(self.root, json.loads((self.root / "project.json").read_text()), production.get_state(self.root))
        self.assertTrue(report["ready"])
        self.assertTrue(any("not independently verified" in issue for issue in report["warnings"]))

    def test_credit_ceiling_and_ledger(self):
        browser = Browser()
        production.advance(self.root, browser=browser)
        with self.assertRaises(StudioError):
            production.advance(self.root, browser=browser)
        st = production.get_state(self.root)
        report = credit_ledger(st)
        self.assertEqual((report["authorized"], report["reserved_possible_spend"], report["unattempted_authorized"]), (1, 1, 0))
        self.assertFalse(report["issues"])
        st["events"].append({"type": "generation_attempt_reserved", "shot": "01", "attempt": 2})
        self.assertTrue(credit_ledger(st)["issues"])

    def test_recurring_actor_identity_gate(self):
        st = production.get_state(self.root)
        pr = json.loads((self.root / "project.json").read_text())
        pr["characters"] = {"角色": "red coat and short dark hair"}
        pr["shots"].append(dict(pr["shots"][0], id="02", cast=["角色"]))
        pr["shots"][0]["cast"] = ["角色"]
        # Modify project without spending then re-approve.
        write_json(self.root / "project.json", pr)
        production.replan(self.root)
        production.approve(self.root, "storyboard")
        production.approve(self.root, "credits", max_generations=2)
        production.advance(self.root, browser=Browser(self.media))
        production.verify_shot(self.root, "01", "pass", "motion checked", motion="pass")
        with self.assertRaisesRegex(StudioError, "identity"):
            production.approve(self.root, "shot", shot_id="01")
        production.verify_shot(self.root, "01", "pass", "age and wardrobe match", motion="pass", identity="pass")
        production.approve(self.root, "shot", shot_id="01")


class VoiceAndDirectorTests(unittest.TestCase):
    def test_two_auditions_and_human_approval(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = preset("general", "Narration")
            project["delivery"] = {"kind": "flow_dynamic", "require_performance_review": True, "voice_review_required": True}
            guide = voice_guide(root, project)
            self.assertTrue(guide.is_file())
            a = root / "a.wav"
            b = root / "b.wav"
            for file, freq in ((a, 300), (b, 500)):
                subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                                f"sine=frequency={freq}:duration=0.2", str(file)], check=True)
            record = register_voice_audition(root, a, b, "external sampled speech")
            self.assertFalse(record["approved"])
            self.assertTrue(approve_voice(root, "Both sounded naturally voiced in their different emotional moods")["approved"])
            a.write_bytes(b"changed unrelated original input")
            self.assertTrue((root / record["auditions"]["warm"]["file"]).exists())
            project["postproduction"] = {"voice": "on"}
            project["shots"][0]["dialogue"] = [{"speaker": "旁白", "text": "一句旁白", "start": 0, "end": 1}]
            mock_state = {"credits_remaining": 0, "events": [], "shots": {s["id"]: {"status": "pending"} for s in project["shots"]}}
            report = delivery_audit(root, project, mock_state)
            self.assertTrue(any("no imported replacement voice" in x for x in report["issues"]))

    def test_static_probe_and_motion_limitations(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "still.mp4"
            subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                            "color=c=blue:s=64x64:r=15:d=2", "-c:v", "libx264", str(path)], check=True)
            report = frame_motion_probe(path)
            self.assertTrue(report["suspect_static"], report)

    def test_director_round_cap_and_human_resolution(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "film"
            production.start(root, "x", "general", "Demo", 4, provider="template")
            state = production.get_state(root)
            state.update(director_first=True, director_review_rounds=2, phase="awaiting_storyboard_approval",
                         director_review_pass=False)
            production.save_state(root, state)
            write_json(root / "production/director_review.json", {"pass": False, "summary": "Two conflicting suggestions", "hard_problems": [], "soft_notes": []})
            with self.assertRaisesRegex(StudioError, "capped"):
                production.director_review(root)
            with self.assertRaisesRegex(StudioError, "12 characters"):
                production.director_override(root, "short")
            st = production.director_override(root, "Reviewed contradictory comments and retained an approved ending.")
            self.assertTrue(st["director_review_pass"])
            self.assertTrue(st["director_override_note"])

if __name__ == "__main__":
    unittest.main()
