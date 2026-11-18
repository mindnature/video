"""V1.3 director-first gates, editorial trim, continuity and seam regression tests."""
from __future__ import annotations

import copy
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from videostudio import production
from videostudio.core import StudioError, ingest, load_project, render, lines_with_offsets, validate, write_json, probe
from videostudio.narrative import (continuity_audit, edit_duration, parse_story_response,
                                   timeline, validate_story)
from videostudio.quality import audit_plan
from videostudio.templates import preset


def story_bible():
    return {
        "title": "通用场景", "premise": "主角从起点走向新的状态", "viewer_hook": "开场发生一个可见的变化",
        "creative_goal": "观众理解变化如何发生", "opening": "主体静止等待", "development": "意外发生，主体作出反应",
        "turning_point": "新的状态打破预期", "ending": "回望开场，状态已不同",
        "emotional_progression": "期待到惊讶再到释然",
        "beats": [
            {"id": "B1", "purpose": "建立期待", "event": "主体察觉变化", "cause": "开场的等待",
             "effect": "主体决定行动", "emotional_change": "期待变为疑惑"},
            {"id": "B2", "purpose": "完成变化", "event": "主体迈出一步", "cause": "前镜的行动决定",
             "effect": "走向收束", "emotional_change": "疑惑转为释然"},
        ],
    }


def director_project():
    p = preset("general", "通用导演测试")
    p["shots"] = p["shots"][:2]
    p["story_bible"] = story_bible()
    p["continuity_required"] = True
    for i, shot in enumerate(p["shots"]):
        shot["duration"] = 2.0
        shot["beats"] = [{"start": 0, "end": 2, "visual": "清晰可见的行动"}]
        shot["narrative_purpose"] = ["建立", "收束"][i]
        shot["framing"] = "中景，可辨面部或主体状态"
        shot["coverage_type"] = "master"
        shot["emotional_state"] = ["期待", "释然"][i]
        shot["story_beat_ids"] = [f"B{i+1}"]
        shot["acceptance"] = {"required_events": ["主体完成预定动作"], "end_visible": ["主体"]}
        shot["continuity"] = {"entry": {"location": "庭院", "action": "等待" if i==0 else "行动"},
                              "exit": {"location": "庭院", "action": "行动" if i==0 else "完成"},
                              "link_from_previous": "开场" if i == 0 else "承接上一镜的迈步",
                              "reference_previous_end": False}
        shot["edit"] = {"source_in": 0, "source_out": 1.8,
                        "transition": "cut", "transition_seconds": 0,
                        "edit_intent": "只保留必要的动作，去掉无效停顿"}
    validate(p)
    return p


class DirectorSchemaTests(unittest.TestCase):
    def test_story_bible_and_coverage(self):
        st = story_bible()
        validate_story(st)
        self.assertEqual(parse_story_response('```json\n' + json.dumps(st, ensure_ascii=False) + '\n```'), st)
        p = director_project()
        audit = audit_plan(p)
        self.assertTrue(audit["ready"], audit)
        self.assertEqual(audit["errors"], 0)
        p["shots"][1]["story_beat_ids"] = ["B99"]
        self.assertFalse(audit_plan(p)["ready"])

    def test_trim_vs_generation_length_and_dissolve_timeline(self):
        p = director_project()
        p["shots"][0]["edit"].update(source_in=0.25, source_out=1.5)
        p["shots"][1]["edit"].update(source_in=0.1, source_out=1.8,
                                        transition="dissolve", transition_seconds=.3)
        validate(p)
        stamps = timeline(p)
        self.assertAlmostEqual(stamps[0]["duration"], 1.25)
        self.assertAlmostEqual(stamps[1]["timeline_in"], .95)
        self.assertAlmostEqual(stamps[1]["timeline_out"], 2.65)
        p["shots"][1]["dialogue"] = [{"speaker": "旁白", "text": "发现了", "start": .4, "end": .9}]
        lines = lines_with_offsets(p)
        self.assertAlmostEqual(lines[0]["absolute_start"], 1.25)
        self.assertAlmostEqual(lines[0]["absolute_end"], 1.75)
        p["shots"][1]["edit"]["transition_seconds"] = 2
        with self.assertRaises(StudioError):
            validate(p)

    def test_warn_long_detail_and_missing_continuity(self):
        p = director_project()
        p["shots"][0]["coverage_type"] = "detail"
        p["shots"][0]["edit"]["source_out"] = 1.8
        self.assertNotIn("LONG_DETAIL_INSERT", {f["code"] for f in audit_plan(p)["findings"]})
        p["shots"][1]["continuity"]["entry"] = {}
        self.assertFalse(continuity_audit(p)["ready"])

    def test_legacy_project_retained(self):
        for mode in ("story", "handcraft", "general"):
            p = preset(mode, "兼容")
            validate(p)
            self.assertTrue(continuity_audit(p)["ready"])


class MockDirectorBrowser:
    def __init__(self, plan, fail_story=False):
        self.story = story_bible()
        self.plan = plan
        self.fail_story = fail_story
        self.actions = []
    def preflight(self, references):
        self.actions.append("preflight")
    def generate_story(self, idea, mode, title, count, references):
        self.actions.append("story")
        if self.fail_story:
            raise RuntimeError("page timed out")
        return self.story
    def review_plan(self, project):
        self.actions.append("review")
        return {"pass": True, "summary": "导演复核通过，镜头连续性标注完整", "hard_problems": [], "soft_notes": []}
    def generate_plan_from_story(self, idea, mode, title, count, references, story):
        self.actions.append("plan")
        assert story == self.story
        return self.plan


class DirectorWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "director"

    def test_gemini_two_stage_and_approval_gates(self):
        p = director_project()
        browser = MockDirectorBrowser(p)
        state = production.start(self.root, "一个因果完整的故事", "general", "通用场景", 2,
                                 provider="gemini-web", gemini_browser=browser, director_first=True)
        self.assertEqual(state["phase"], "awaiting_story_approval")
        self.assertFalse((self.root / "production/storyboard.md").exists())
        with self.assertRaises(StudioError):
            production.approve(self.root, "storyboard")
        production.approve(self.root, "story")
        self.assertEqual(production.get_state(self.root)["phase"], "gemini_plan_ready")
        state = production.generate_gemini(self.root, browser=browser)
        self.assertEqual(state["phase"], "awaiting_storyboard_approval")
        self.assertEqual(browser.actions.count("story"), 1)
        self.assertEqual(browser.actions.count("plan"), 1)
        self.assertTrue((self.root / "production/cut_review.md").exists())
        with self.assertRaisesRegex(StudioError, 'director-review'):
            production.approve(self.root, "storyboard")
        production.director_review(self.root, browser=browser)
        self.assertEqual(browser.actions.count("review"), 1)
        production.approve(self.root, "storyboard")
        self.assertEqual(production.get_state(self.root)["phase"], "awaiting_credit_approval")

    def test_story_failure_does_not_retry_automatically(self):
        p = director_project()
        browser = MockDirectorBrowser(p, fail_story=True)
        with self.assertRaises(StudioError):
            production.start(self.root, "故事", "general", "通用场景", 2,
                             provider="gemini-web", gemini_browser=browser, director_first=True)
        state = production.get_state(self.root)
        self.assertEqual(state["phase"], "gemini_submission_uncertain")
        self.assertEqual(state["gemini_step"], "story")
        with self.assertRaises(StudioError):
            production.generate_gemini(self.root, browser=browser)
        self.assertEqual(browser.actions.count("story"), 1)
        production.resolve_gemini(self.root, "retry")
        self.assertEqual(production.get_state(self.root)["phase"], "gemini_story_ready")

    def test_modified_story_blocks_plan(self):
        p = director_project()
        browser = MockDirectorBrowser(p)
        production.start(self.root,"test","general","通用场景",2,provider="gemini-web",
                         gemini_browser=browser,director_first=True)
        production.approve(self.root,"story")
        original = json.loads((self.root/"production/story_bible.json").read_text())
        original["premise"] = "被篡改的前提"
        write_json(self.root/"production/story_bible.json",original)
        with self.assertRaises(StudioError):
            production.generate_gemini(self.root,browser=browser)
        self.assertEqual(browser.actions.count("plan"),0)


class RealEditAndSeamTests(unittest.TestCase):
    def test_ffmpeg_trim_dissolve_audio(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            p = director_project()
            p["shots"][1]["edit"].update(transition="dissolve", transition_seconds=.35)
            validate(p)
            for i, shot in enumerate(p["shots"]):
                path = root / f"clip_{i}.mp4"
                subprocess.run(["ffmpeg","-hide_banner","-loglevel","error","-y","-f","lavfi","-i",
                                f"color=c={'blue' if i == 0 else 'red'}:s=160x90:r=30:d=2",
                                "-f","lavfi","-i",f"sine=frequency={400+100*i}:sample_rate=48000:duration=2",
                                "-c:v","libx264","-pix_fmt","yuv420p","-c:a","aac","-shortest",str(path)],check=True)
                ingest(root,p,shot["id"],path,"video")
            with patch("videostudio.core.dimensions",return_value=(160,90)):
                output=render(root,p)
            self.assertAlmostEqual(float(probe(output)["format"]["duration"]), 3.25, delta=.18)
            self.assertTrue((root / "work/cuts/cut_01.mp4").exists())
            self.assertTrue((root / "work/cuts/cut_02.mp4").exists())

if __name__=="__main__":
    unittest.main()

class FakeFlow:
    def __init__(self, mapping):
        self.mapping = mapping
        self.references = {}
    def preflight(self, references):
        if any(not x.is_file() for x in references):
            raise ValueError('missing reference')
    def generate(self, root, project, shot, references):
        self.references[shot['id']] = list(references)
        return self.mapping[shot['id']]


class RealReviewPipelineTests(unittest.TestCase):
    def test_pair_preview_and_human_seam_gate_and_reference_frame(self):
        with tempfile.TemporaryDirectory() as d:
            workspace = Path(d)
            root = workspace / 'film'
            production.start(root,'simple story','general','Demo',4,provider='template')
            p = director_project()
            p['shots'][1]['continuity']['reference_previous_end'] = True
            write_json(root/'project.json',p)
            production.replan(root)
            production.approve(root,'storyboard')
            production.approve(root,'credits',max_generations=2)
            mapping={}
            for i,s in enumerate(p['shots']):
                dest=workspace/f'clip_{i}.mp4'
                subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y',
                                '-f','lavfi','-i',f'color=c={"green" if i==0 else "blue"}:s=160x90:r=30:d=2',
                                '-f','lavfi','-i','anullsrc=r=48000:cl=stereo',
                                '-t','2','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac',str(dest)],check=True)
                mapping[s['id']]=dest
            browser=FakeFlow(mapping)
            with patch('videostudio.core.dimensions',return_value=(160,90)):
                first=production.advance(root,browser=browser)
                self.assertEqual(first['phase'],'awaiting_shot_approval')
                production.verify_shot(root,'01','pass','Verified the full shot')
                production.approve(root,'shot',shot_id='01')
                second=production.advance(root,browser=browser)
                self.assertEqual(second['phase'],'awaiting_shot_approval')
                self.assertTrue(second['shots']['02'].get('seam_review'))
                self.assertTrue((root/second['shots']['02']['seam_review']).is_file())
                self.assertEqual(len(browser.references['02']),1)
                self.assertEqual(browser.references['02'][0].suffix,'.png')
                production.verify_shot(root,'02','pass','second scene works in isolation')
                with self.assertRaisesRegex(StudioError,'verify-seam'):
                    production.approve(root,'shot',shot_id='02')
                production.verify_seam(root,'01','02','pass','Action and sound continuity checked')
                production.approve(root,'shot',shot_id='02')
                final=production.advance(root,browser=browser)
                self.assertEqual(final['phase'],'awaiting_final_approval')
                self.assertTrue((root/final['master']).is_file())

class IndependentReviewTests(unittest.TestCase):
    def test_director_review_parse_and_block_on_critical_notes(self):
        from videostudio.narrative import parse_director_review, director_review_prompt
        p = director_project()
        self.assertIn("镜头", director_review_prompt(p))
        blocked = {"pass": False, "summary": "主角连续性断裂",
                   "hard_problems": [{"shot": "01->02", "category": "continuity",
                                      "issue": "相邻镜头动作不同", "fix": "用同一动作在画内继续"}],
                   "soft_notes": []}
        self.assertEqual(parse_director_review(json.dumps(blocked))["pass"], False)
        for invalid in ({"pass": True, "summary": "yes", "hard_problems": blocked["hard_problems"], "soft_notes": []},
                        {"pass": "true", "summary": "yes", "hard_problems": [], "soft_notes": []}):
            with self.assertRaises(StudioError):
                parse_director_review(json.dumps(invalid))

    def test_review_failure_prevents_storyboard_approval(self):
        class CriticalBrowser(MockDirectorBrowser):
            def review_plan(self, project):
                return {"pass": False, "summary": "断裂", "hard_problems": [{
                    "shot": "01->02", "category": "continuity", "issue": "缺少过渡", "fix": "调整 cut"}],
                        "soft_notes": []}
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)/'film'
            browser = CriticalBrowser(director_project())
            production.start(root,'demo','general','通用场景',2,provider='gemini-web',
                             gemini_browser=browser,director_first=True)
            production.approve(root,'story')
            production.generate_gemini(root,browser=browser)
            state=production.director_review(root,browser=browser)
            self.assertFalse(state['director_review_pass'])
            with self.assertRaisesRegex(StudioError,'director-review'):
                production.approve(root,'storyboard')

    def test_stale_review_cannot_authorize_changed_storyboard(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/'film'
            web=MockDirectorBrowser(director_project())
            production.start(root,'demo','general','通用场景',2,provider='gemini-web',
                             gemini_browser=web,director_first=True)
            production.approve(root,'story')
            production.generate_gemini(root,browser=web)
            production.director_review(root,browser=web)
            project_file=root/'project.json'
            p=json.loads(project_file.read_text(encoding='utf-8'))
            p['shots'][0]['camera']='人为修改的摄像机'
            write_json(project_file,p)
            with self.assertRaisesRegex(StudioError,'director-review'):
                production.approve(root,'storyboard')
