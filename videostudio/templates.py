"""Editable starting projects. Treat them as shot plans, not generated footage."""


def preset(name: str, title: str) -> dict:
    if name == "handcraft":
        names = [
            ("原作引子", "洁净的素纸与原作轮廓作为创作起点，不出现已经完成的手作痕迹。", "固定俯拍，纸张位于画面中央，桌边少量材料。", ["素纸", "铅笔"],
             [(0, 3, "桌面静物与素纸，手将素纸放平。"), (3, 7, "铅笔轻画构图轮廓，动作连续真实。"), (7, 10, "镜头停留在未完成的底稿。")]),
            ("真实材料", "展示叶片、花瓣、纽扣或纸片等真实材料的形状、厚度和细节。", "45度微距近景，动作缓慢可辨。", ["天然花瓣", "干叶", "镊子"],
             [(0, 3, "手从收纳盒取出真实材料。"), (3, 7, "指腹轻触材料，让叶脉与真实厚度清晰可见。"), (7, 10, "按颜色和形状把材料整齐排在桌面。")]),
            ("建立骨架", "先确定视觉重心和主要线条，避免跳过制作过程。", "固定俯拍，中景到手部特写的小幅切换。", ["素纸", "铅笔", "细枝"],
             [(0, 3, "对照轮廓放置第一根细枝。"), (3, 7, "手用镊子微调主线条位置。"), (7, 10, "关键构图骨架形成，仍可看见大片空白。")]),
            ("逐层构形", "真实叠放、压边与固定材料，表现可复现的工艺步骤。", "固定侧俯拍，重点表现接触阴影。", ["花瓣", "叶片", "安全胶点", "镊子"],
             [(0, 3, "镊子夹住一片花瓣，沿底稿摆放。"), (3, 7, "点胶、轻按固定，相邻材料遮挡关系清晰。"), (7, 10, "继续铺设局部，保持未完成区域。")]),
            ("细节润色", "添加纹理与色彩层次，但不遮盖材料原生特征。", "微距慢推，焦点落在真实连接位置。", ["花瓣", "细枝", "画笔"],
             [(0, 3, "细笔补充少量线条，避开材料主体纹理。"), (3, 7, "手修整边缘与局部层次，细节逐渐完整。"), (7, 10, "成品大体完成，停留在质感细节。")]),
            ("成品揭晓", "由局部纹理揭示完整实体手工画，保留真实摄影质感。", "先微距轻推，再平稳抬高成完整俯拍。", ["真实材料手工画", "素色桌面"],
             [(0, 3, "柔光扫过叶脉、材料厚度和手工连接点。"), (3, 7, "镜头平稳缓慢移至完整作品，画面不自动变形。"), (7, 10, "保持静态成品画面，让观众看清细节。")]),
        ]
        shots = []
        for i, (scene, action, camera, materials, beats) in enumerate(names, start=1):
            shots.append({"id": f"{i:02d}", "scene": scene, "action": action, "camera": camera,
                          "duration": 10, "materials": materials,
                          "beats": [{"start": a, "end": b, "visual": v} for a, b, v in beats], "dialogue": []})
        return {"title": title, "mode": "handcraft", "aspect_ratio": "9:16", "fps": 30,
                "style": "李子柒式静谧手作纪录片氛围，真实桌面微距摄影，柔和自然光，浅景深，不模仿具体镜头",
                "characters": {}, "postproduction": {"style":"clean", "voice":"auto", "subtitles":"auto"}, "shots": shots}
    if name == "story":
        shots = []
        scenes = ["人物与场景建立", "冲突触发", "动作推进", "局面变化", "结局收束"]
        for i, scene in enumerate(scenes, start=1):
            shots.append({"id": f"{i:02d}", "scene": scene,
                          "action": "在本镜写入一项可拍摄的剧情推进动作与真实的主体状态变化。",
                          "camera": "根据剧情选择固定机位或运动机位，明确人物位置。",
                          "duration": 12, "materials": [], "cast": ["角色A", "角色B"],
                          "beats": [{"start": 0, "end": 4, "visual": "明确人物动机和空间关系。"},
                                    {"start": 4, "end": 8, "visual": "一项可观察的动作推动故事。"},
                                    {"start": 8, "end": 12, "visual": "剧情状态明确落地，结尾留白。"}],
                          "dialogue": []})
        return {"title": title, "mode": "story", "aspect_ratio": "16:9", "fps": 30,
                "style": "人物剧情短片，摄影、美术、动作风格取决于具体创意",
                "characters": {"角色A": "固定外貌身份描述（不含跨镜站位）", "角色B": "固定外貌身份描述（不含跨镜站位）"},
                "postproduction": {"style": "clean", "voice": "auto", "subtitles": "auto"}, "shots": shots}
    if name == "general":
        scenes = ["主题建立", "核心特征", "过程与细节", "成果收束"]
        shots = [
            {"id": f"{i:02d}", "scene": scene, "action": "由创意替换为具体、可拍摄的行动与主体状态",
             "camera": "根据当前镜头目标选择合理机位", "duration": 10, "materials": [], "cast": [],
             "subject_ids": [], "beats": [{"start": 0, "end": 4, "visual": "建立本镜主体和空间"},
                                     {"start": 4, "end": 8, "visual": "执行一项清晰的主体动作"},
                                     {"start": 8, "end": 10, "visual": "停留在完成后的可辨状态"}],
             "dialogue": [], "acceptance": {"required_events": ["完成本镜的核心动作"]}}
            for i, scene in enumerate(scenes, start=1)
        ]
        return {"title": title, "mode": "general", "aspect_ratio": "9:16", "fps": 30,
                "style": "按创意决定影像风格", "characters": {}, "subjects": {},
                "postproduction": {"style": "clean", "voice": "auto", "subtitles": "auto"},
                "shots": shots}
    raise ValueError("Unknown preset")
