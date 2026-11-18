"""Static, cross-genre planning audit and explicit (human-verifiable) shot criteria.

This module does NOT claim to understand actual video pixels. Visual acceptance
requires watching the produced candidate and recording evidence.
"""
from __future__ import annotations

from typing import Any

ACCEPTANCE_FIELDS = ("start_visible", "end_visible", "end_absent", "required_events", "audio_checks")
SUPPORTED_STYLES = {"clean", "surveillance", "vintage", "cinematic"}


def acceptance_checks(shot: dict) -> list[dict]:
    checks: list[dict] = []
    for key in ACCEPTANCE_FIELDS:
        for description in shot.get("acceptance", {}).get(key, []):
            checks.append({"category": key, "description": description, "verified": False})
    # Always require an actual last-frame review, even when a storyboard
    # does not provide end-state criteria. It prevents sampled stills hiding a bad ending.
    checks.append({"category": "end_frame", "description": "检查最后 0.5 秒：主体、动作、剪辑余量正确", "verified": False})
    return checks


def audit_plan(project: dict) -> dict:
    """Provide blocking schema/logic errors and nonblocking production warnings.

    It deliberately avoids brittle NLP claims about logical contradiction.
    """
    findings: list[dict[str, Any]] = []

    def issue(level: str, code: str, message: str, shot: str | None = None) -> None:
        findings.append({"level": level, "code": code, "shot": shot, "message": message})

    characters = project.get("characters", {})
    subjects = project.get("subjects", {})
    for name, identity in characters.items():
        # Cross-shot identity fields must not contain permanent spatial/action rules.
        if any(term in identity for term in ("始终停在", "始终站在", "一直站在", "一直停留在", "一直待在", "不能离开", "始终不离开", "全程不离开")):
            issue("ERROR", "ACTION_IN_IDENTITY", f"{name!r} 的全局身份描述包含持续站位/不离场命令；请移至具体镜头动作")
    for shot in project.get("shots", []):
        sid = shot["id"]
        cast = shot.get("cast", [])
        visible_subjects = shot.get("subject_ids", [])
        if len(set(cast)) < len(cast):
            issue("ERROR", "DUPLICATE_CAST", "本镜 cast 存在重复名字", sid)
        for name in cast:
            if name not in characters:
                issue("ERROR", "UNKNOWN_CAST", f"角色 {name!r} 不在全局 characters 身份库中", sid)
        for name in visible_subjects:
            if name not in subjects:
                issue("ERROR", "UNKNOWN_SUBJECT", f"主体 {name!r} 不在全局 subjects 库中", sid)
        speakers = {x.get("speaker") for x in shot.get("dialogue", [])}
        for speaker in speakers:
            if characters and speaker in characters and speaker not in cast:
                issue("ERROR", "SPEAKER_NOT_IN_CAST", f"台词说话人 {speaker!r} 未列入本镜 cast；旁白可使用非角色名", sid)
        if characters and "cast" not in shot and shot.get("dialogue"):
            issue("WARN", "MISSING_CAST", "建议显式填写本镜 cast；全局角色不会被自动注入", sid)
        acc = shot.get("acceptance", {})
        both = set(acc.get("end_visible", [])) & set(acc.get("end_absent", []))
        if both:
            issue("ERROR", "CONTRADICTORY_END", f"结束画面同时要求出现和不出现：{sorted(both)}", sid)
        if not acc:
            issue("WARN", "MISSING_ACCEPTANCE", "建议指定本镜可核查的结束画面和必要动作", sid)
        count = len(acc.get("required_events", []))
        if count >= 4 and shot["duration"] / count < 2.0:
            issue("WARN", "DENSE_ACTIONS", f"在 {shot['duration']} 秒内需呈现 {count} 项独立事件，建议拆镜或加入跳切", sid)
        for beat in shot.get("beats", []):
            if len(beat.get("events", [])) >= 3 and beat["end"] - beat["start"] < 3:
                issue("WARN", "DENSE_BEAT", "一个短时间段内包含过多独立动作，建议拆分", sid)
    style = project.get("postproduction", {}).get("style", "clean")
    if style == "surveillance" and not project.get("postproduction", {}).get("camera_prefix", "CAM"):
        issue("WARN", "CAMERA_LABEL", "建议为监控画面配置机位标识")
    return {"ready": not any(x["level"] == "ERROR" for x in findings),
            "errors": sum(x["level"] == "ERROR" for x in findings),
            "warnings": sum(x["level"] == "WARN" for x in findings),
            "findings": findings,
            "limitations": "仅检查结构化规划和冲突；无法自动证明真实视频的人物走位或口型正确"}
