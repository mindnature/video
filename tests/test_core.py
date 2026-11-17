import json
import tempfile
import unittest
from pathlib import Path

from videostudio.core import StudioError, available_output, export, ingest, lines_with_offsets, load_project, srt_time, validate
from videostudio.templates import preset


class CoreTests(unittest.TestCase):
    def test_presets_and_prompts(self):
        for mode, expected in [("handcraft", 6), ("story", 5)]:
            p = preset(mode, "测试")
            validate(p)
            self.assertEqual(len(p["shots"]), expected)
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                out = export(root, p)
                self.assertTrue((out / "prompts" / "shot_01.txt").exists())
                self.assertTrue((out / "subtitles.srt").exists())
                self.assertEqual(len(list((out / "prompts").glob("shot_*.txt"))), expected)

    def test_timing_and_captions(self):
        p = preset("story", "有配音")
        p["shots"][1]["dialogue"] = [{"speaker": "A", "text": "你好", "start": 1.2, "end": 2.5}]
        rows = lines_with_offsets(p)
        self.assertEqual(rows[0]["id"], "02_01")
        self.assertEqual(rows[0]["absolute_start"], 13.2)
        self.assertEqual(srt_time(rows[0]["absolute_start"]), "00:00:13,200")

    def test_reject_overlap(self):
        p = preset("handcraft", "坏时间轴")
        p["shots"][0]["beats"][1]["start"] = 2
        with self.assertRaises(StudioError):
            validate(p)

    def test_assets_are_versioned_and_non_overwriting(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            p = preset("handcraft", "测试")
            source = root / "sample.mp4"
            source.write_bytes(b"fake video bytes")
            p1 = ingest(root, p, "01", source, "video")
            p2 = ingest(root, p, "01", source, "video")
            self.assertNotEqual(p1, p2)
            self.assertTrue(p1.exists())
            self.assertEqual(p1.read_bytes(), p2.read_bytes())

    def test_available_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "master.mp4"
            self.assertEqual(available_output(output), output)
            output.write_bytes(b"x")
            self.assertEqual(available_output(output).name, "master_v002.mp4")


if __name__ == "__main__":
    unittest.main()
