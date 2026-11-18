import json
import tempfile
import unittest
from pathlib import Path
from videostudio.handoff import flow_pack, gemini_brief
from videostudio.templates import preset


class HandoffTests(unittest.TestCase):
    def test_exports_gemini_and_flow(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            project=preset("handcraft", "东方花影")
            director=gemini_brief(root,project,"叶片和花瓣制作东方仕女")
            self.assertIn("叶片和花瓣",director.read_text(encoding="utf-8"))
            agent, queue=flow_pack(root,project)
            self.assertIn("镜头 01",agent.read_text(encoding="utf-8"))
            payload=json.loads(queue.read_text(encoding="utf-8"))
            self.assertEqual(len(payload["shots"]),6)
            self.assertEqual(payload["shots"][0]["state"],"pending_manual_flow_generation")
            self.assertTrue((root/"production/prompts/shot_06.txt").exists())

if __name__ == "__main__":
    unittest.main()
