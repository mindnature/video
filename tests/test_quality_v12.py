"""Regression coverage across narrative, products and physical handcraft."""
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from videostudio import production
from videostudio.core import StudioError, export, ingest, render, shot_prompt, validate, write_json
from videostudio.postfx import style_filters
from videostudio.quality import acceptance_checks, audit_plan
from videostudio.templates import preset


class CrossGenreTests(unittest.TestCase):
    def test_narrative_scopes_cast_not_absent_character(self):
        p = preset("story", "四人对话")
        p["characters"] = {"甲": "红衣男子，短发", "乙": "绿衣男子，长髯", "丙": "蓝衣男子",
                           "童子": "白衣小童", "未出场者": "灰袍智者", "角色A": "占位角色A", "角色B": "占位角色B"}
        s = p["shots"][0]
        s["cast"] = ["甲", "乙", "丙", "童子"]
        s["acceptance"] = {"end_visible": ["童子在门内"], "end_absent": ["甲", "乙", "丙"]}
        s["dialogue"] = [{"speaker": "童子", "text": "来客请回", "start": 2, "end": 4}]
        prompt = shot_prompt(p, s)
        self.assertIn("绿衣男子，长髯", prompt)
        self.assertNotIn("未出场者", prompt)
        self.assertNotIn("不超过三名主要演员", prompt)
        self.assertIn("结束不得出现", prompt)
        self.assertIn("童子在门内", prompt)
        self.assertTrue(audit_plan(p)["ready"])

    def test_product_subject_appearance_and_scene_local_action(self):
        p = preset("general", "展示便携水杯")
        p["subjects"] = {"水杯": "磨砂蓝色杯身、黑色杯盖", "广告牌": "巨大红色墙牌"}
        s = p["shots"][0]
        s["subject_ids"] = ["水杯"]
        s["action"] = "打开杯盖检查密封圈"
        s["acceptance"] = {"end_visible": ["杯盖已打开，密封圈清晰"]}
        prompt = shot_prompt(p, s)
        self.assertIn("磨砂蓝色杯身", prompt)
        self.assertNotIn("广告牌", prompt)
        self.assertTrue(audit_plan(p)["ready"])

    def test_handcraft_does_not_inherit_cast_and_needs_material_physics(self):
        p = preset("handcraft", "叶片画")
        p["characters"] = {"画师": "白色衬衣、扎袖", "访客": "灰色礼帽"}
        p["shots"][0]["cast"] = ["画师"]
        prompt = shot_prompt(p, p["shots"][0])
        self.assertIn("扎袖", prompt)
        self.assertNotIn("礼帽", prompt)
        self.assertIn("接触、固定、厚度和遮挡", prompt)

    def test_conflicting_acceptance_blocked(self):
        p = preset("story", "冲突测试")
        p["shots"][0]["acceptance"] = {"end_visible": ["甲"], "end_absent": ["甲"]}
        report = audit_plan(p)
        self.assertFalse(report["ready"])
        self.assertIn("CONTRADICTORY_END", [item["code"] for item in report["findings"]])

    def test_action_density_warning_not_arbitrary_actor_limit(self):
        p = preset("story", "忙乱动作")
        p["shots"][0]["duration"] = 6
        p["shots"][0]["beats"] = [{"start": 0, "end": 6, "visual": "连续动作"}]
        p["shots"][0]["acceptance"] = {"required_events": ["开门", "退后", "转身", "挥手", "走出", "关门"]}
        report = audit_plan(p)
        self.assertTrue(report["ready"])
        self.assertIn("DENSE_ACTIONS", [item["code"] for item in report["findings"]])

    def test_project_rejects_invalid_sfx_and_style(self):
        p = preset("general", "出错配置")
        p["postproduction"]["style"] = "watchdog"
        with self.assertRaises(StudioError):
            validate(p)
        p["postproduction"]["style"] = "clean"
        p["shots"][0]["sound_events"] = [{"path": "../private.wav", "time": 1}]
        with self.assertRaises(StudioError):
            validate(p)

    def test_acceptance_criteria_include_end_frame_even_if_not_specified(self):
        p = preset("general", "end")
        checks = acceptance_checks(p["shots"][0])
        self.assertTrue(any(item["category"] == "end_frame" for item in checks))

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg not installed")
    def test_real_surveillance_render_with_subtitles_and_sound_cue(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            source = root / "source.mp4"
            voice = root / "voice.wav"
            fx = root / "hit.wav"
            subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
                            "-i", "testsrc2=size=320x180:rate=24:duration=1.1", "-f", "lavfi",
                            "-i", "anullsrc=channel_layout=stereo:sample_rate=48000", "-t", "1.1",
                            "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(source)], check=True)
            for dest in (voice, fx):
                subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
                                "-i", "sine=frequency=540:sample_rate=48000:duration=0.3", str(dest)], check=True)
            p = preset("general", "surveillance")
            p["shots"] = [p["shots"][0]]
            p["shots"][0].update(duration=1.0,
                beats=[{"start": 0, "end": 1.0, "visual": "敲门"}],
                dialogue=[{"speaker": "旁白", "text": "请进", "start": 0.2, "end": 0.65}],
                sound_events=[{"path": "hit.wav", "time": 0.1}])
            p["postproduction"].update(style="surveillance", clock_start="08:00:00",
                                       subtitles="auto", voice="auto")
            validate(p)
            ingest(root, p, "01", source, "video")
            ingest(root, p, "01", voice, "voice", "01_01")
            self.assertEqual(render(root, p).suffix, ".mp4")
            info = subprocess.check_output(["ffprobe", "-v", "error", "-show_entries",
                "stream=codec_type", "-of", "csv=p=0", str(root / "exports" / "final_master.mp4")], text=True)
            self.assertIn("video", info)
            self.assertIn("audio", info)


class ApprovalGateTests(unittest.TestCase):
    def test_explicit_end_state_requires_human_verification(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "film"
            production.start(root, "test", "general", "review-test", 4, provider="template")
            file = root / "project.json"
            p = json.loads(file.read_text(encoding="utf-8"))
            p["shots"] = p["shots"][:1]
            p["shots"][0]["duration"] = 1
            p["shots"][0]["beats"] = [{"start": 0, "end": 1, "visual": "move"}]
            write_json(file, p)
            production.replan(root)
            production.approve(root, "storyboard")
            production.approve(root, "credits", max_generations=1)
            class MockBrowser:
                def preflight(self, refs): pass
                def generate(self, *args): return None
            production.advance(root, browser=MockBrowser())
            video = Path(d) / "candidate.mp4"
            video.write_bytes(b"test bytes")
            with patch("videostudio.production.probe", return_value={"streams": [{"codec_type": "video"}]}):
                production.receive(root, "01", video)
            with self.assertRaises(StudioError):
                production.approve(root, "shot", shot_id="01")
            production.verify_shot(root, "01", "pass", "完整观看：动作与结束画面符合要求")
            state = production.approve(root, "shot", shot_id="01")
            self.assertEqual(state["shots"]["01"]["status"], "approved")

if __name__ == "__main__":
    unittest.main()
