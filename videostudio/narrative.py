"""Script-first director pipeline, cross-shot continuity, and editable timeline.

This module checks declared intent, never claims to understand actual video pixels.
Legacy 1.2 projects with no screenplay/continuity/edit fields remain valid.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ALLOWED_TRANSITIONS = {"cut", "dissolve", "match_action", "match_eyeline", "sound_bridge"}
STATE_FIELDS = ("location", "time", "lighting", "screen_direction", "action", "emotion", "prop_state")


def _required_text(value: Any, path: str) -> None:
    from .core import StudioError
    if not isinstance(value, str) or not value.strip():
        raise StudioError(f"{path} requires nonempty text")


def validate_story(story: dict) -> None:
    """Story spine works for fiction, product demos, landscapes and craft process.

    It does not impose a three-act plot on instructional/nonfiction videos.
    """
    from .core import StudioError
    if not isinstance(story, dict):
        raise StudioError("Story bible must be a JSON object")
    for field in ("title", "premise", "viewer_hook", "creative_goal", "opening", "development", "turning_point", "ending", "emotional_progression"):
        _required_text(story.get(field), f"story_bible.{field}")
    beats = story.get("beats")
    if not isinstance(beats, list) or not beats:
        raise StudioError("story_bible.beats must be a nonempty list")
    seen = set()
    for beat in beats:
        if not isinstance(beat, dict):
            raise StudioError("story beat must be an object")
        sid = beat.get("id")
        _required_text(sid, "story_bible.beats[].id")
        if sid in seen:
            raise StudioError(f"Duplicate story beat id: {sid}")
        seen.add(sid)
        for key in ("purpose", "event", "cause", "effect", "emotional_change"):
            _required_text(beat.get(key), f"story_bible.beats[{sid}].{key}")


def parse_story_response(text: str) -> dict:
    """Fail closed on extraneous chat text; no JSON extraction from arbitrary prose."""
    import re
    from .core import StudioError
    body = text.strip()
    if body.startswith("```"):
        match = re.fullmatch(r"```(?:json)?\s*([\s\S]*?)\s*```", body, re.I)
        if not match:
            raise StudioError("Gemini screenplay response contains invalid code fence")
        body = match.group(1)
    try:
        story = json.loads(body)
    except ValueError as exc:
        raise StudioError("Gemini screenplay response must contain one JSON object") from exc
    validate_story(story)
    return story


def story_prompt(idea: str, mode: str, title: str, shot_count: int) -> str:
    """Stage 1 prompt: deliberately produces NO shots, prompts or Flow submissions."""
    example = {
        "title": title,
        "premise": "一句话概括内容与主要变化",
        "viewer_hook": "首几秒让观众有兴趣继续观看的可视化事件",
        "creative_goal": "作品希望观众理解/体验/感受什么",
        "opening": "开头具体状态",
        "development": "事件与情绪如何逐步推进",
        "turning_point": "关键变化；非剧情视频可为关键发现/制作转折",
        "ending": "结尾与开头的回应",
        "emotional_progression": "观众情绪如何随进程变化",
        "beats": [{"id": "B1", "purpose": "功能与叙事目的", "event": "可见发生的事件",
                   "cause": "为什么发生（开场可以是初始条件）", "effect": "对下一事件有什么影响",
                   "emotional_change": "人物或观众此刻的变化"}],
    }
    return (
        "你是影视编剧和导演，不是分镜模型。现在仅制作第一阶段《故事圣经》，"
        "禁止输出 shot、prompt、scene、camera 或时间轴，也不调用视频生成。\n"
        f"片名：{title}；题材：{mode}；预期镜头数量约 {shot_count}；创意：{idea}\n"
        "先写清楚为什么发生、人物/主体如何变化、高潮或关键发现、结尾如何回扣开头。"
        "故事和神话可有戏剧矛盾，产品/手工/自然类不必强制戏剧化，但必须有可理解的过程和视觉推进。"
        "每个 beat 必须有因果与情绪/认知变化，防止把生成模型时长误当成剪辑镜头长度。"
        "严格只输出一个合法 JSON 对象，不要代码围栏或解释。字段及结构示例（内容全部重写）：\n"
        + json.dumps(example, ensure_ascii=False, indent=2)
    )


def storyboard_prompt(idea: str, mode: str, title: str, shots: int, story: dict, reference_count: int) -> str:
    """Stage 2 only after story approval. Prompt describes real continuity fields."""
    from .templates import preset
    sample = preset(mode, title)
    # Describe the full schema for *every* shot so Gemini cannot accidentally
    # omit continuity/edit fields by imitating only the first filled example.
    for idx, shot in enumerate(sample["shots"]):
        shot.update({
            "story_beat_ids": [story["beats"][min(idx, len(story["beats"]) - 1)]["id"]],
            "narrative_purpose": "为什么这一镜必须出现，而不是重复前一镜",
            "framing": "全景/中景/近景及人物脸和关键动作可见要求",
            "coverage_type": "master",
            "emotional_state": "人物在这一镜的反应与情感变化",
            "continuity": {
                "entry": {"location": "进入时的位置", "action": "进入时进行的动作", "emotion": "情绪"},
                "exit": {"location": "离开时的位置", "action": "离开时完成的动作", "emotion": "情绪"},
                "link_from_previous": "说明与上一镜的因果与动作/视线/声音衔接，首镜写开场",
                "reference_previous_end": False,
            },
            "edit": {"source_in": 0, "source_out": min(shot["duration"], 5),
                     "transition": "cut", "transition_seconds": 0,
                     "edit_intent": "实际剪入的片段内容与切点理由"},
            "acceptance": {"required_events": ["导演指定的关键画面动作"],
                           "end_visible": ["本镜的目标结束画面"]}
        })
    sample["story_bible"] = story
    sample["continuity_required"] = True
    return (
        "你是第二阶段分镜导演和技术总监。下方故事圣经已人工审核通过，禁止改动其中的剧情因果与结局。\n"
        f"创意：{idea}；片名：{title}；模式：{mode}；镜头数量：{shots}；参考图数量：{reference_count}\n"
        "先从故事 beat 推导镜头，而不是每 8 秒换一镜。每个镜头必须有明确叙事目的、情绪、景别。"
        "每镜 coverage_type 选 master/reaction/detail/insert/establishing；"
        "人物的重要反应和完整姿态不能长期只以局部特写代替；局部特写只占需要的几秒。"
        "每一镜必须规划 entry/exit 状态（位置、动作、视线、道具、光线、运动方向），"
        "和上一镜的衔接理由；无法连续的动作可设计明确有意跳切。"
        "原始视频生成片段 duration 与剪入正片的 edit.source_in/source_out 是不同概念。"
        "允许剪入 2–5 秒的有效动作，而不是机械保留全部 8 秒。"
        "edit.transition 可为 cut/dissolve/match_action/match_eyeline/sound_bridge。"
        "当过渡选 dissolve 时，transition_seconds 必须大于0但不能超过相邻镜头长度。"
        "只在确实需要参考已通过镜头尾帧时，将 continuity.reference_previous_end 设 true。"
        "剪接方式 match_action/match_eyeline/sound_bridge 需要出入状态和对应音画描述支持，"
        "不是告诉 FFmpeg 仅靠转场就能修复人物走位。保持每镜 cast/subject_ids 仅包含本镜出场实体。"
        "每镜如有对白，依照原始视频片段时间轴标记。不得让字幕或HUD在模型原片内生成。"
        "必须提供 acceptance 与每镜可验证的结尾状态。不得添加与故事无关的额外人物。"
        "严格只输出一个合法 JSON 对象，不要代码围栏或解释。结构示例（内容全部重写）：\n"
        + json.dumps(sample, ensure_ascii=False, indent=2) + "\n"
        "已批准的故事圣经（必须原样复制到 project.story_bible）：\n"
        + json.dumps(story, ensure_ascii=False, indent=2)
    )


def edit_range(shot: dict) -> tuple[float, float]:
    edit = shot.get("edit", {})
    return float(edit.get("source_in", 0)), float(edit.get("source_out", shot["duration"]))


def edit_duration(shot: dict) -> float:
    start, end = edit_range(shot)
    return end - start


def transition_duration(shot: dict) -> float:
    edit = shot.get("edit", {})
    return float(edit.get("transition_seconds", 0)) if edit.get("transition") == "dissolve" else 0.0


def timeline(project: dict) -> list[dict]:
    """Timeline entries with source and output seconds and incoming overlaps."""
    position = 0.0
    result = []
    for i, shot in enumerate(project["shots"]):
        duration = edit_duration(shot)
        overlap = transition_duration(shot) if i else 0.0
        position -= overlap
        a, b = edit_range(shot)
        result.append({"id": shot["id"], "source_in": a, "source_out": b,
                       "duration": duration, "timeline_in": round(position, 6),
                       "timeline_out": round(position + duration, 6),
                       "incoming_transition": shot.get("edit", {}).get("transition", "cut"),
                       "overlap_seconds": overlap,
                       "edit_intent": shot.get("edit", {}).get("edit_intent", "")})
        position += duration
    return result


def validate_shot_edit(shot: dict, previous: dict | None) -> None:
    from .core import StudioError
    edit = shot.get("edit", {})
    if not isinstance(edit, dict):
        raise StudioError(f"shot {shot['id']}: edit must be a dictionary")
    allowed = {"source_in", "source_out", "transition", "transition_seconds", "edit_intent"}
    if any(k not in allowed for k in edit):
        raise StudioError(f"shot {shot['id']}: unsupported edit field")
    if any(k in edit and (isinstance(edit[k], bool) or not isinstance(edit[k], (int, float)))
           for k in ("source_in", "source_out")):
        raise StudioError(f"shot {shot['id']}: edit source range must be numeric")
    start, end = edit_range(shot)
    if not 0 <= start < end <= shot["duration"]:
        raise StudioError(f"shot {shot['id']}: 0 <= source_in < source_out <= generation duration required")
    mode = edit.get("transition", "cut")
    if mode not in ALLOWED_TRANSITIONS:
        raise StudioError(f"shot {shot['id']}: unsupported edit transition {mode}")
    d = edit.get("transition_seconds", 0)
    if isinstance(d, bool) or not isinstance(d, (int, float)) or d < 0:
        raise StudioError(f"shot {shot['id']}: transition_seconds must be a nonnegative number")
    if mode == "dissolve":
        if previous is None or not (0 < d < min(edit_duration(previous), edit_duration(shot))):
            raise StudioError(f"shot {shot['id']}: dissolve duration must fit both adjacent edited clips")
    elif d != 0:
        raise StudioError(f"shot {shot['id']}: non-dissolve transitions use 0 seconds")
    if previous is None and mode != "cut":
        raise StudioError(f"shot {shot['id']}: first shot has no incoming transition")
    if "edit_intent" in edit and not isinstance(edit["edit_intent"], str):
        raise StudioError(f"shot {shot['id']}: edit_intent must be a string")


def validate_continuity(shot: dict) -> None:
    from .core import StudioError
    data = shot.get("continuity", {})
    if not isinstance(data, dict):
        raise StudioError(f"shot {shot['id']}: continuity must be an object")
    for key in ("entry", "exit"):
        value = data.get(key, {})
        if not isinstance(value, dict) or any(k not in STATE_FIELDS or not isinstance(v, str) for k, v in value.items()):
            raise StudioError(f"shot {shot['id']}: continuity.{key} must have string state fields")
    if "link_from_previous" in data and not isinstance(data["link_from_previous"], str):
        raise StudioError(f"shot {shot['id']}: continuity.link_from_previous must be a string")
    if "reference_previous_end" in data and not isinstance(data["reference_previous_end"], bool):
        raise StudioError(f"shot {shot['id']}: reference_previous_end must be boolean")
    for field in ("narrative_purpose", "framing", "emotional_state"):
        if field in shot and (not isinstance(shot[field], str) or not shot[field].strip()):
            raise StudioError(f"shot {shot['id']}: {field} must be nonempty text")
    if shot.get("coverage_type", "master") not in ("master", "reaction", "detail", "insert", "establishing"):
        raise StudioError(f"shot {shot['id']}: coverage_type must be master/reaction/detail/insert/establishing")
    if "story_beat_ids" in shot and (not isinstance(shot["story_beat_ids"], list) or
                                    any(not isinstance(x, str) or not x for x in shot["story_beat_ids"])):
        raise StudioError(f"shot {shot['id']}: story_beat_ids must be list of ids")


def continuity_audit(project: dict) -> dict:
    """Deterministic structural checks only. Narrative truth stays with reviewer."""
    findings = []
    story = project.get("story_bible")
    beat_ids = {x["id"] for x in story["beats"]} if story else set()
    shots = project["shots"]
    strict = bool(project.get("continuity_required", False))
    def issue(level: str, code: str, msg: str, shot: str | None = None):
        findings.append({"level": level, "code": code, "message": msg, "shot": shot})
    covered = set()
    for i, shot in enumerate(shots):
        sid = shot["id"]
        mapping = shot.get("story_beat_ids", [])
        covered.update(mapping)
        for bid in mapping:
            if story and bid not in beat_ids:
                issue("ERROR", "UNKNOWN_STORY_BEAT", f"Story beat {bid} not in approved bible", sid)
        if strict and story and not mapping:
            issue("ERROR", "MISSING_BEAT_MAPPING", "本镜必须对应故事圣经的叙事节拍", sid)
        for field in ("narrative_purpose", "framing", "emotional_state"):
            if strict and not shot.get(field):
                issue("ERROR", "MISSING_DIRECTOR_FIELD", f"缺少导演字段 {field}", sid)
        if strict and not shot.get("acceptance"):
            issue("ERROR", "MISSING_ACCEPTANCE", "需要首尾状态/动作验收要求", sid)
        cont = shot.get("continuity", {})
        if strict and "edit" not in shot:
            issue("ERROR", "MISSING_EDIT", "严格模式每镜都须规定实际剪入时长与剪接策略", sid)
        if strict and (not cont.get("entry") or not cont.get("exit")):
            issue("ERROR", "MISSING_CONTINUITY", "必须描述本镜 entry/exit 状态", sid)
        if i:
            previous = shots[i - 1]
            prev = previous.get("continuity", {}).get("exit", {})
            cur = cont.get("entry", {})
            if strict and not cont.get("link_from_previous"):
                issue("ERROR", "MISSING_LINK", "没有与上一镜的衔接说明", sid)
            if cont.get("reference_previous_end") and not previous.get("acceptance"):
                issue("WARN", "REFERENCE_FROM_UNVERIFIED_EXIT", "引用上一镜尾帧前，需实看并审核上一镜", sid)
            # Explicit declared continuity contradictions are not always mistakes; intentional
            # ellipses are allowed when explained and flagged for human review.
            for key in ("location", "time", "lighting", "screen_direction", "prop_state"):
                if key in prev and key in cur and prev[key] != cur[key]:
                    issue("WARN", "STATE_CHANGED", f"镜头边界 {key} 从 {prev[key]!r} 到 {cur[key]!r}；请检查是否有意省略/跳切", sid)
    if story:
        for bid in beat_ids - covered:
            issue("ERROR" if strict else "WARN", "UNCOVERED_STORY_BEAT", f"故事节拍 {bid} 没有被镜头覆盖")
    if strict and not story:
        issue("ERROR", "MISSING_STORY", "连贯性模式需要先完成故事圣经")
    return {"ready": not any(f["level"] == "ERROR" for f in findings),
            "errors": sum(f["level"] == "ERROR" for f in findings),
            "warnings": sum(f["level"] == "WARN" for f in findings),
            "findings": findings,
            "limits": "只能检查明确声明的剧本映射与状态矛盾；无法证明画面中的人物、动作或口型连续"}


def export_narrative(root: Path, project: dict) -> None:
    from .core import write_json
    output = root / "production"
    output.mkdir(parents=True, exist_ok=True)
    if project.get("story_bible"):
        story = project["story_bible"]
        lines = [f"# {story['title']}｜故事圣经", "", f"创作目标：{story['creative_goal']}", "",
                 f"核心概念：{story['premise']}", f"开场：{story['opening']}",
                 f"推进：{story['development']}", f"转折：{story['turning_point']}",
                 f"结尾：{story['ending']}", f"情感曲线：{story['emotional_progression']}", "", "## 故事节拍", ""]
        for beat in story["beats"]:
            lines.append(f"- {beat['id']}：{beat['event']}。因为：{beat['cause']}；结果：{beat['effect']}；情绪：{beat['emotional_change']}")
        (output / "story_bible.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    write_json(output / "continuity_audit.json", continuity_audit(project))
    write_json(output / "edit_timeline.json", {"title": project["title"], "timeline": timeline(project),
                                                 "note": "source_in/source_out 为原始生成素材秒数；实际成片时长由此计算，dissolve 会产生交叠"})
    pair_lines = ["# 相邻镜头剪接审查表", "", "本表是待核查的导演计划，不是视频语义检验报告。", ""]
    for left, right in zip(project["shots"], project["shots"][1:]):
        edit = right.get("edit", {})
        pair_lines.extend([
            f"## {left['id']} → {right['id']}",
            f"接续逻辑：{right.get('continuity', {}).get('link_from_previous', '待填写')}",
            f"上一镜结束状态：{json.dumps(left.get('continuity', {}).get('exit', {}), ensure_ascii=False)}",
            f"下一镜进入状态：{json.dumps(right.get('continuity', {}).get('entry', {}), ensure_ascii=False)}",
            f"剪法：{edit.get('transition', 'cut')}；叠化：{transition_duration(right):g}秒；目的：{edit.get('edit_intent', '待填写')}",
            "待验收：空间、动作方向、视线、音轨连续和人物身份是否在实际影像中一致。", "",
        ])
    (output / "cut_review.md").write_text("\n".join(pair_lines), encoding="utf-8")


def director_review_prompt(project: dict) -> str:
    """Fresh-chat critic review after storyboard generation, before any Flow spend."""
    return (
        "你是一名独立、严格的电影导演和剪辑指导。你没有参与本项目的创作，请只找真实问题，不夸奖。"
        "只根据下面已经写出的故事和分镜审核，不要声称看到了未生成的视频。\n"
        "逐项检查：①故事动机、因果、转折、情绪弧线是否连贯；"
        "②镜头是否过度使用局部特写，是否有可见的人物面部反应和主体状态；"
        "③相邻镜头出入位置、视线、运动方向、道具、光照与声音能否衔接；"
        "④从生成视频里裁取短片段的入点出点是否合理，叠化是否掩盖动作错误；"
        "⑤模型是否难以执行过密动作。每个硬伤必须写可执行修改建议。\n"
        "严格返回一个合法 JSON 对象且不含代码围栏。格式为："
        '{"pass":true,"summary":"总体评价","hard_problems":[],"soft_notes":["可选改进"]}。'
        "若有阻断级问题则 pass=false 且 hard_problems 非空，每个问题是"
        '{"shot":"01或01->02或all","category":"story|continuity|framing|emotion|edit|model",'
        '"issue":"具体问题","fix":"如何修正"}。'
        "注意：本次仅审核尚未拍摄的计划。人工还需审核实际 Flow 画面。\n"
        "计划 JSON：\n" + json.dumps(project, ensure_ascii=False, indent=2)
    )


def parse_director_review(text: str) -> dict:
    """Review parser: fail closed, no invented positive gate on invalid output."""
    from .core import StudioError
    import re
    value = text.strip()
    if value.startswith("```"):
        match = re.fullmatch(r"```(?:json)?\s*([\s\S]*?)\s*```", value, re.I)
        if not match:
            raise StudioError("Director review code fence invalid")
        value = match.group(1)
    try:
        doc = json.loads(value)
    except ValueError as exc:
        raise StudioError("Director review must return one JSON object") from exc
    if (not isinstance(doc, dict) or type(doc.get("pass")) is not bool or
            not isinstance(doc.get("summary"), str) or not doc["summary"].strip() or
            not isinstance(doc.get("hard_problems"), list) or
            not isinstance(doc.get("soft_notes"), list) or
            any(not isinstance(x, str) for x in doc["soft_notes"])):
        raise StudioError("Director review fields invalid")
    for x in doc["hard_problems"]:
        if not isinstance(x, dict) or any(not isinstance(x.get(f), str) or not x[f].strip()
                                          for f in ("shot", "category", "issue", "fix")):
            raise StudioError("Director review hard_problems entries invalid")
    if bool(doc["hard_problems"]) == bool(doc["pass"]):
        raise StudioError("Director review pass must be true iff there are no hard problems")
    return doc
