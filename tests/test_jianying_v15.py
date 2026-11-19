"""V1.5 Jianying desktop audio handoff tests, including real FFmpeg mixing."""
import json
import shutil
import subprocess
import tempfile
import unittest
import wave
from pathlib import Path

from videostudio.core import StudioError, ingest, load_project, probe, render, write_json
from videostudio.delivery import _voice_gate
from videostudio.jianying import approved_track, approve, import_audio, make_pack, status
from videostudio.templates import preset


class JianyingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "film"
        self.root.mkdir()
        self.project = preset("general", "声音测试")
        self.project["shots"] = self.project["shots"][:1]
        shot = self.project["shots"][0]
        shot["duration"] = 3
        shot["beats"] = [{"start": 0, "end": 3, "visual": "主角缓慢抬头"}]
        shot["dialogue"] = [
            {"speaker": "旁白", "text": "昨夜风雨。", "start": .3, "end": 1.1},
            {"speaker": "旁白", "text": "天亮了。", "start": 1.5, "end": 2.4},
        ]
        self.project["delivery"] = {"kind": "flow_dynamic", "voice_review_required": True}
        self.project["postproduction"] = {"voice": "on", "subtitles": "on"}
        write_json(self.root / "project.json", self.project)
        self.audio = Path(self.tmp.name) / "jianying.wav"
        with wave.open(str(self.audio), "wb") as wavefile:
            wavefile.setnchannels(1)
            wavefile.setsampwidth(2)
            wavefile.setframerate(16000)
            wavefile.writeframes(b"\x20\x05" * (16000 * 3))

    def _pack_import(self):
        make_pack(self.root, self.project)
        return import_audio(self.root, self.project, self.audio, full_track=True)

    def test_pack_script_contains_all_lines_and_timing(self):
        folder = make_pack(self.root, self.project)
        script = (folder / "copy_to_jianying.txt").read_text("utf-8")
        self.assertIn("昨夜风雨", script)
        self.assertIn("天亮了", script)
        data = json.loads((folder / "alignment.json").read_text("utf-8"))
        self.assertEqual([x["id"] for x in data["lines"]], ["01_01", "01_02"])
        self.assertEqual(data["lines"][0]["start"], .3)
        self.assertIn("时间线", (folder / "INSTRUCTIONS.md").read_text("utf-8"))

    def test_full_track_import_must_be_human_approved(self):
        record = self._pack_import()
        self.assertFalse(record["approved"])
        self.assertTrue((self.root / record["path"]).is_file())
        with self.assertRaisesRegex(StudioError, "not yet approved"):
            approved_track(self.root, self.project)
        self.assertTrue(_voice_gate(self.root, self.project))
        accepted = approve(self.root, self.project, "已在视频中听查气口、两句时点和文字")
        self.assertTrue(accepted["approved"])
        path, captions = approved_track(self.root, self.project)
        self.assertTrue(path.is_file())
        self.assertEqual(len(captions), 2)
        self.assertEqual(captions[0]["absolute_start"], .3)
        self.assertTrue(status(self.root, self.project)["approved"])
        self.assertIn("00:00:00,300", (self.root / "production/jianying/aligned_subtitles.srt").read_text("utf-8"))

    def test_manual_subtitle_alignment_and_stale_changes(self):
        self._pack_import()
        file = self.root / "production/jianying/alignment.json"
        data = json.loads(file.read_text("utf-8"))
        data["lines"][0]["start"] = .4
        data["lines"][0]["end"] = 1.2
        write_json(file, data)
        approve(self.root, self.project, "实际听到的起止已校准")
        self.assertEqual(approved_track(self.root, self.project)[1][0]["absolute_start"], .4)
        data["lines"][0]["start"] = .5
        write_json(file, data)
        with self.assertRaisesRegex(StudioError, "Alignment changed"):
            approved_track(self.root, self.project)
        self.assertFalse(status(self.root, self.project)["approved"])

    def test_invalid_and_overlapping_alignments_rejected(self):
        self._pack_import()
        fp = self.root / "production/jianying/alignment.json"
        data = json.loads(fp.read_text("utf-8"))
        data["lines"][1]["start"] = .4
        write_json(fp, data)
        with self.assertRaisesRegex(StudioError, "overlapping"):
            approve(self.root, self.project, "我审过了")

    def test_reimport_new_version_invalidates_old_approval(self):
        self._pack_import()
        approve(self.root, self.project, "初版声线和字幕都已核对")
        updated = import_audio(self.root, self.project, self.audio, full_track=True)
        self.assertTrue(updated["path"].endswith("v002.wav"))
        self.assertFalse(updated["approved"])
        self.assertTrue((self.root / "assets/voice_tracks/jianying_full_v001.wav").exists())

    def test_line_import_uses_existing_ingest_and_versioning(self):
        make_pack(self.root, self.project)
        first = import_audio(self.root, self.project, self.audio, line_id="01_01")
        second = import_audio(self.root, self.project, self.audio, line_id="01_01")
        self.assertNotEqual(first["path"], second["path"])
        self.assertEqual(first["mode"], "line")

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required")
    def test_approved_full_track_is_mixed_and_captioned_into_real_mp4(self):
        self._pack_import()
        approve(self.root, self.project, "已听完真实音频，停顿时点和字幕均一致")
        video = Path(self.tmp.name) / "raw.mp4"
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                        "color=c=black:size=320x180:rate=10:duration=3", "-t", "3", "-c:v", "libx264",
                        "-pix_fmt", "yuv420p", str(video)], check=True)
        ingest(self.root, self.project, "01", video, "video")
        result = render(self.root, self.project, output=self.root / "exports" / "jianying.mp4")
        info = probe(result)
        self.assertGreater(float(info["format"]["duration"]), 2.8)
        self.assertTrue(any(stream.get("codec_type") == "audio" for stream in info["streams"]))
        self.assertTrue(any(stream.get("codec_type") == "video" for stream in info["streams"]))
        srt = (self.root / "work/render_subtitles.srt").read_text("utf-8")
        self.assertIn("昨夜风雨", srt)
        self.assertIn("00:00:01,500", srt)


if __name__ == "__main__":
    unittest.main()
