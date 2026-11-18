"""Offline handoff packages for Gemini director and the Google Flow web Agent."""
from __future__ import annotations

import json
from pathlib import Path

from .core import export, shot_prompt
from .templates import preset


def gemini_brief(root: Path, project: dict, idea: str) -> Path:
    """Create a copy/paste ready director brief without calling any external API."""
    production = root / "production"
    production.mkdir(parents=True, exist_ok=True)
    target = production / "gemini_director_brief.md"
    template = preset(project["mode"], project["title"])
    shots = len(project["shots"])
    target.write_text(
        "# Gemini 总导演任务书\n\n"
        "请根据下列创意，为 Video Studio 制作完整可执行的项目 JSON。\n"
        "仅输出一个合法 JSON 对象，不要 Markdown 围栏、不附解释。\n\n"
        f"## 创意\n{idea}\n\n"
        f"## 固定条件\n片名：{project['title']}。模式：{project['mode']}。"
        f"画幅：{project['aspect_ratio']}。镜头数量：{shots}。帧率：{project.get('fps', 30)}。\n"
        "人物描述需跨镜头一致；每镜给出具体动作、镜位、材料、按秒分段的 beats；"
        "有台词才填写 dialogue，写明 speaker/text/start/end。\n"
        "手作必须真实可制作：不允许材料自动飞入或瞬间成形，清晰展示手部/工具/固定方式。"
        "真实画面首尾帧若尚未提供，只能写规划要求，不能声称图片已经生成。\n"
        "所有 beat 按顺序、不重叠、不得超过镜头 duration。"
        "不要生成 UI 字幕水印，最后留至少 1 秒停顿；按项目要求保证场景连续性。\n\n"
        "## JSON 字段模板（仅参考结构，全部内容须按创意重写）\n```json\n"
        + json.dumps(template, ensure_ascii=False, indent=2)
        + "\n```\n\n"
        "## 使用说明\n将 Gemini 输出保存为当前项目的 project.json，"
        "然后运行 `video-studio plan 项目路径`；旧文件先备份，先验证后替换。\n",
        encoding="utf-8")
    return target


def flow_pack(root: Path, project: dict) -> tuple[Path, Path]:
    """Export separate prompts and an Agent handoff; never claims the site generated footage."""
    production = export(root, project)
    queue = [{"shot_id": shot["id"], "scene": shot["scene"],
              "duration_target_seconds": shot["duration"],
              "aspect_ratio": project["aspect_ratio"],
              "prompt_file": f"prompts/shot_{shot['id']}.txt",
              "prompt": shot_prompt(project, shot),
              "state": "pending_manual_flow_generation"} for shot in project["shots"]]
    manifest = production / "flow_queue.json"
    manifest.write_text(json.dumps({"title": project["title"], "shots": queue}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    target = production / "flow_agent_handoff.md"
    intro = [
        f"# Google Flow Agent 制片任务｜{project['title']}", "",
        "以下为多条**不同分镜**，不是同一个镜头的多种变体。",
        "请按顺序逐镜执行。先核对模型、画幅、时长和用户提供的首尾帧/参考素材，",
        "缺少参考图时请提醒用户上传，不能擅自假设图像已存在。",
        "请保持『生成前确认』开启，任何扣费操作都须用户明确批准。",
        "若 Agent 无法批量执行多个不同提示词，请明确告知并使用每段独立提示词逐条生成；",
        "不要把六镜误当成一镜的六个变体。",
        "每次生成后按镜号标注素材，记录失败/重拍及实际时长，不要自动清理旧版本。",
        "生成完成后让用户在 Flow 下载视频或下载项目，导入 Video Studio 再拼接。", "",
        "注意：Flow 账户是否支持某种模型、目标时长和一次性生成若干不同镜头，均由当时页面决定。", "",
    ]
    for shot in project["shots"]:
        intro += [f"## 镜头 {shot['id']}｜{shot['scene']}", "", "```text", shot_prompt(project, shot).rstrip(), "```", ""]
    target.write_text("\n".join(intro), encoding="utf-8")
    return target, manifest
