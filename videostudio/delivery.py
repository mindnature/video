"""V1.4 delivery contracts: evidence, Flow budget reconciliation, voice auditions.

A container may be a valid MP4 while containing nothing but a still photo.
This module never infers that a subject performed a required action from metadata.
The operator must watch actual footage and attest observable movement.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from .core import StudioError, digest, need_binary, probe, write_json

DELIVERY_KINDS = {"flow_dynamic", "animatic", "mixed_media"}
EVIDENCE_ORIGINS = {"flow_browser", "operator_attested_flow", "local_animatic", "other"}


def policy(project: dict) -> dict:
    """Legacy projects have no strict deliverable promise unless opted in."""
    return project.get("delivery", {})


def validate_policy(project: dict) -> None:
    spec = policy(project)
    if not isinstance(spec, dict):
        raise StudioError("delivery must be an object")
    if spec and spec.get("kind") not in DELIVERY_KINDS:
        raise StudioError(f"delivery.kind must be one of {sorted(DELIVERY_KINDS)}")
    for field in ("require_performance_review", "voice_review_required"):
        if field in spec and type(spec[field]) is not bool:
            raise StudioError(f"delivery.{field} must be boolean")
    if spec.get("kind") == "flow_dynamic" and spec.get("require_performance_review") is False:
        raise StudioError("flow_dynamic delivery cannot disable performance review")


def register_candidate(root: Path, state: dict, shot_id: str, archived: Path,
                       origin: str, *, attestation: str = "") -> None:
    """Attach immutable-file evidence to the specific candidate, never to a whole project.

    A human claim of Flow origin is a *self-attestation*, not a verified Google API receipt.
    """
    if origin not in EVIDENCE_ORIGINS:
        raise StudioError(f"Unknown media origin {origin}")
    if origin == "operator_attested_flow" and not attestation.strip():
        raise StudioError("Manual Flow evidence requires an explicit source attestation")
    relative = archived.resolve().relative_to(root.resolve()).as_posix()
    record = {"path": relative, "sha256": digest(archived), "origin": origin,
              "source_attestation": attestation if origin == "operator_attested_flow" else None,
              "flow_attempt": state["shots"][shot_id]["attempts"]}
    state["shots"][shot_id].setdefault("candidate_evidence", {})[relative] = record


def credit_ledger(state: dict) -> dict:
    grants = [e for e in state.get("events", []) if e.get("type") == "approved_credits"]
    reservations = [e for e in state.get("events", []) if e.get("type") == "generation_attempt_reserved"]
    authorized = sum(int(e.get("additional_generations", 0)) for e in grants)
    reserved = len(reservations)
    remaining = state.get("credits_remaining", 0)
    click_events = [e for e in state.get("events", []) if e.get("type") == "flow_button_clicked"]
    issues = []
    if authorized < reserved or remaining != authorized - reserved:
        issues.append("Authorized generations and reserved attempts do not reconcile")
    return {"authorized": authorized, "reserved_possible_spend": reserved,
            "authorization_events": grants, "attempt_events": reservations,
            "unattempted_authorized": remaining,
            "visible_clicks_observed": len(click_events),
            "observed_click_events": click_events,
            "clicks_without_observable_receipt": reserved - len(click_events),
            "website_clicks_note": "Observed click is a Playwright UI event, not proof of Google billing. Unobserved reservations may still have clicked before timeout; reconcile with visible Flow history.",
            "issues": issues}


def _voice_record_path(root: Path) -> Path:
    return root / "production" / "voice_casting.json"


def voice_guide(root: Path, project: dict) -> Path:
    """Draft two contrasting audition texts; never synthesizes generic Windows voices."""
    lines = [(line["speaker"], line["text"]) for shot in project["shots"] for line in shot.get("dialogue", [])]
    warm = lines[0][1] if lines else "曾经，有一个故事，在这里静静地开始。"
    somber = lines[min(len(lines) - 1, max(1, len(lines)//2))][1] if lines else "多年之后，只有风还记得那一天。"
    dest = root / "production" / "voice_audition_guide.md"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(f"# 旁白声音试听与审核｜{project['title']}\n\n"
                    "请使用外部真实人声或高品质中文 TTS 制作两段不同情绪试音，先听后选。"
                    "禁止未经审查直接把系统默认语音当成正式纪录片配音。\n\n"
                    f"1. 温暖/回忆试音：{warm}\n"
                    f"2. 克制/沉静试音：{somber}\n\n"
                    "分别听：自然停顿、人物温度、字音、重音、气口、机械韵律。"
                    "审核应在真实画面和环境音下进行，字幕需跟随实际声音起止。\n",
                    encoding="utf-8")
    return dest


def register_voice_audition(root: Path, warm: Path, somber: Path, source: str) -> dict:
    """Version audition inputs and validate audio streams; does not score human likeness."""
    if not source.strip():
        raise StudioError("Provide provider/performer source for provenance")
    dest_dir = root / "assets" / "voice_auditions"
    dest_dir.mkdir(parents=True, exist_ok=True)
    candidates = {}
    for name, file in (("warm", warm), ("somber", somber)):
        file = file.expanduser().resolve()
        if not file.is_file() or file.suffix.lower() not in {".wav", ".mp3", ".m4a", ".flac"}:
            raise StudioError(f"Missing supported audition audio: {file}")
        media = probe(file)
        if not any(stream.get("codec_type") == "audio" for stream in media.get("streams", [])):
            raise StudioError(f"No audio stream in {file}")
        target = dest_dir / f"{name}_{digest(file)[:12]}{file.suffix.lower()}"
        if not target.exists():
            shutil.copy2(file, target)
        candidates[name] = {"file": target.relative_to(root).as_posix(), "sha256": digest(target),
                            "duration_seconds": float(media.get("format", {}).get("duration", 0))}
    record = {"source": source, "auditions": candidates, "approved": False, "human_review": None}
    write_json(_voice_record_path(root), record)
    return record


def approve_voice(root: Path, note: str) -> dict:
    if not note.strip():
        raise StudioError("Human voice approval note must describe delivery and naturalness")
    path = _voice_record_path(root)
    if not path.exists():
        raise StudioError("Two actual audition files required before voice approval")
    record = json.loads(path.read_text(encoding="utf-8"))
    if set(record.get("auditions", {})) != {"warm", "somber"}:
        raise StudioError("Both warm and somber auditions are required")
    for data in record["auditions"].values():
        file = root / data["file"]
        if not file.is_file() or digest(file) != data["sha256"]:
            raise StudioError("Audition changed or missing; register again")
    record["approved"] = True
    record["human_review"] = note
    write_json(path, record)
    return record


def _voice_gate(root: Path, project: dict) -> list[str]:
    if not policy(project).get("voice_review_required", False):
        return []
    from .core import asset_index, selected_asset, lines_with_offsets
    issues = []
    if project.get("postproduction", {}).get("voice", "auto") == "off":
        issues.append("Narration is required but postproduction.voice is disabled")
    from .jianying import approved_track
    full_track = None
    try:
        full_track = approved_track(root, project)
    except StudioError as exc:
        return [f"Jianying full narration: {exc}"]
    index = asset_index(root)
    for line in lines_with_offsets(project):
        if str(line.get("speaker", "")).lower() in ("旁白", "narrator", "voiceover", "解说"):
            if not full_track and not selected_asset(root, index, "voice", line["id"]):
                issues.append(f"Narration line {line['id']} has no imported replacement voice")
    if issues:
        return issues
    path = _voice_record_path(root)
    if not path.is_file():
        return ["Narrated delivery has no two-sample voice casting record"]
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
        if not record.get("approved") or not record.get("human_review"):
            return ["Narration voice auditions were not approved by operator"]
        for data in record["auditions"].values():
            file = root / data["file"]
            if not file.is_file() or digest(file) != data["sha256"]:
                return ["Approved audition asset changed"]
    except (ValueError, KeyError, OSError):
        return ["Voice casting record is malformed"]
    return []


def delivery_audit(root: Path, project: dict, state: dict) -> dict:
    """Proof-based final gate; records what is known and what requires human inspection."""
    spec = policy(project)
    kind = spec.get("kind", "unspecified")
    strict_dynamic = kind == "flow_dynamic"
    ledger = credit_ledger(state)
    issues = list(ledger["issues"])
    warnings = []
    shots = []
    char_count = {}
    for shot in project["shots"]:
        for name in shot.get("cast", []):
            char_count[name] = char_count.get(name, 0) + 1
    for shot in project["shots"]:
        sid = shot["id"]
        item = state["shots"].get(sid, {})
        relative = item.get("approved_file")
        evidence = item.get("candidate_evidence", {}).get(relative, {}) if relative else {}
        src = root / relative if relative else None
        hash_ok = bool(src and src.is_file() and evidence and digest(src) == evidence.get("sha256"))
        origin = evidence.get("origin", "unverified")
        human = item.get("human_verification", {})
        motion = human.get("motion")
        if item.get("status") != "approved" or not relative:
            issues.append(f"Shot {sid}: missing approved media")
        if strict_dynamic:
            if origin not in ("flow_browser", "operator_attested_flow") or not hash_ok:
                issues.append(f"Shot {sid}: missing matching Flow-origin evidence (manual sources require attestation)")
            if human.get("result") != "pass" or motion != "pass":
                issues.append(f"Shot {sid}: on-screen subject motion has not been human-verified")
            if any(char_count.get(name, 0) > 1 for name in shot.get("cast", [])) and human.get("identity") != "pass":
                issues.append(f"Shot {sid}: recurring character identity/age/wardrobe not verified against other shots")
            if origin == "operator_attested_flow":
                warnings.append(f"Shot {sid}: Flow source asserted by operator, not independently verified against Google history")
        motion_probe = frame_motion_probe(src) if src and src.is_file() and strict_dynamic else None
        if motion_probe and motion_probe.get("suspect_static"):
            warnings.append(f"Shot {sid}: three sampled decoded frames are identical; inspect for static-image substitution")
        shots.append({"id": sid, "status": item.get("status"), "asset": relative,
                      "origin": origin, "sha256_match": hash_ok, "human_motion": motion,
                      "human_visual_review": human.get("result"), "human_identity": human.get("identity"), "flow_attempts": item.get("attempts", 0),
                      "technical_frame_probe": motion_probe})
    issues.extend(_voice_gate(root, project))
    return {"title": project["title"], "delivery_kind": kind, "ready": not issues,
            "issues": issues, "warnings": warnings, "credits": ledger, "shots": shots,
            "limits": "Flow website click counts are not independently verifiable; human motion signoff is not automatic optical semantics; voice quality requires listening."}


def save_delivery_report(root: Path, project: dict, state: dict) -> dict:
    report = delivery_audit(root, project, state)
    write_json(root / "production" / "delivery_report.json", report)
    return report


def frame_motion_probe(path: Path) -> dict:
    """Three decoded frames; detects an identical still, not subject movement.

    Camera-only zoom can differ across samples and still lack acting; human
    performance signoff is always required for flow_dynamic output.
    """
    import hashlib
    try:
        meta = probe(path)
        duration = float(meta.get("format", {}).get("duration", 0))
        if duration < 0.5:
            return {"status": "unavailable", "reason": "video too short"}
        ffmpeg = need_binary("ffmpeg")
        marks = [max(0.0, min(duration - 0.04, when)) for when in (0.1, duration / 2, duration - .2)]
        hashes = []
        for mark in marks:
            process = subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-ss", f"{mark:g}",
                                      "-i", str(path), "-vf", "scale=64:64:flags=bilinear,format=gray",
                                      "-frames:v", "1", "-f", "rawvideo", "pipe:1"],
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=25)
            if process.returncode != 0 or len(process.stdout) != 4096:
                return {"status": "unavailable", "reason": "could not sample video frames"}
            hashes.append(hashlib.sha256(process.stdout).hexdigest())
        return {"status": "ok", "distinct_samples": len(set(hashes)),
                "suspect_static": len(set(hashes)) == 1,
                "limits": "Motion across frames can be camera-only; human inspection must verify actual subject actions"}
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return {"status": "unavailable", "reason": "technical frame sampling failed"}
