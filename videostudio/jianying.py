"""Official-UI-safe 剪映 (Jianying) narration handoff and timeline audio bridge.

No undocumented Jianying draft format, cookies, hidden endpoints or UI automation.
Jianying voices are created by the operator; this module prepares copyable scripts,
archives exported audio, validates timestamps and mixes approved tracks into the film.
"""
from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path

from .core import (AUDIO_EXTS, StudioError, digest, ingest, lines_with_offsets,
                   probe, srt_time, write_json)
from .narrative import timeline

VOICE_DIR = Path("production/jianying")
RECORD = VOICE_DIR / "import_record.json"
TIMINGS = VOICE_DIR / "alignment.json"


def _total(project: dict) -> float:
    items = timeline(project)
    return max((float(x["timeline_out"]) for x in items), default=0.0)


def _rows(project: dict) -> list[dict]:
    return [dict(id=x["id"], speaker=x["speaker"], text=x["text"],
                 start=round(x["absolute_start"], 3), end=round(x["absolute_end"], 3))
            for x in lines_with_offsets(project)]


def make_pack(root: Path, project: dict) -> Path:
    """Prepare operator handoff; preserve existing user-edited timestamp files."""
    root = root.resolve()
    folder = root / VOICE_DIR
    folder.mkdir(parents=True, exist_ok=True)
    rows = _rows(project)
    if not rows:
        raise StudioError("No dialogue/narration in the current edited timeline")
    with (folder / "voice_lines.csv").open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=["id", "speaker", "text", "start", "end"])
        writer.writeheader()
        writer.writerows(rows)
    (folder / "copy_to_jianying.txt").write_text("\n\n".join(x["text"] for x in rows) + "\n", encoding="utf-8")
    (folder / "line_by_line.txt").write_text("\n\n".join(
        f"[{x['id']} | {x['start']:.2f}–{x['end']:.2f}s | {x['speaker']}]\n{x['text']}" for x in rows) + "\n", encoding="utf-8")
    alignment = folder / "alignment.json"
    if not alignment.exists():
        write_json(alignment, {"project_sha256": digest(root / "project.json"),
                               "note": "将每段字幕 start/end 改成听完剪映导出音频后确认的真实起止时间；单位为成片秒数。",
                               "lines": rows})
    (folder / "INSTRUCTIONS.md").write_text(
        f"# 剪映配音交接包｜{project['title']}\n\n"
        "本模块不自动操作剪映，也不接入非公开接口。剪映的不同版本可能有不同音色和导出选项。\n\n"
        "1. 打开剪映专业版，使用 文本／文本朗读（或界面中的朗读入口），挑选合适音色。"
        "先做温暖与克制两段试听，并按项目既有 voice-audition / voice-approve 完成人工选音。\n"
        "2. 把 copy_to_jianying.txt 中的旁白复制进剪映，人工调整自然停顿、重音及配音片段。"
        "把原视频作为时间参考，**对齐完整影片时间线**。静音区（如渡江无旁白）须保留空白。\n"
        "3. 推荐从剪映导出仅音频 WAV（或 MP3/M4A/FLAC）。如果版本没有音频导出，"
        "可导出含旁白的视频，再用 FFmpeg 提取音轨为 WAV；不要导入含背景音乐的混音版。\n"
        "4. 使用 jianying-import --full-track 把对应完整时间线的音轨导入。"
        "如果逐句单独导出，也可用 --line ID 导入每条音频，自动采用计划起点。\n"
        "5. 使用 alignment.json 校准每句实际听到的语音起止（不是单纯对齐文本预计时刻）。"
        "调整后调用 jianying-approve --note 描述已听查的音色、停顿、字幕及静音区。\n"
        "6. Video Studio 会混入经批准的剪映人声，并把校准字幕烧录到成片；"
        "保留 Flow 原视频及原声，必要时降低原始音量。\n\n"
        f"目标成片总时长：{_total(project):.3f} 秒。"
        "音频不可比成片更长，且必须覆盖所有需要朗读的字幕时间。\n"
        "本交接包没有制造音频、没有上传剪映内容，也不声称剪映具有程序化语音 API。\n",
        encoding="utf-8")
    return folder


def _audio(path: Path) -> float:
    if not path.is_file() or path.suffix.lower() not in AUDIO_EXTS:
        raise StudioError("Import an existing WAV, MP3, M4A or FLAC audio file")
    try:
        meta = probe(path)
    except Exception as exc:
        raise StudioError("Cannot inspect exported voice audio") from exc
    if not any(x.get("codec_type") == "audio" for x in meta.get("streams", [])):
        raise StudioError("The provided media has no audio stream")
    duration = float(meta.get("format", {}).get("duration", 0))
    if duration <= 0:
        raise StudioError("Audio duration is zero")
    return duration


def _record(root: Path) -> dict | None:
    p = root / RECORD
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None


def import_audio(root: Path, project: dict, source: Path, *, line_id: str | None = None,
                 full_track: bool = False) -> dict:
    """Import a user-exported audio file; never synthesizes or guesses timing."""
    if bool(line_id) == bool(full_track):
        raise StudioError("Choose exactly one of --line ID or --full-track")
    root, source = root.resolve(), source.expanduser().resolve()
    duration = _audio(source)
    folder = root / VOICE_DIR
    folder.mkdir(parents=True, exist_ok=True)
    if line_id:
        found = next((r for r in _rows(project) if r["id"] == line_id), None)
        if not found:
            raise StudioError(f"Unknown edited dialogue line: {line_id}")
        archived = ingest(root, project, line_id.rsplit("_", 1)[0], source, "voice", line_id)
        record = {"provider": "jianying_manual_export", "mode": "line", "line_id": line_id,
                  "path": archived.relative_to(root).as_posix(), "sha256": digest(archived),
                  "duration_seconds": duration, "planned_window_seconds": found["end"]-found["start"],
                  "warning": "Actual speech and SRT timing must be listened to and approved"}
        write_json(folder / f"line_{line_id}_import.json", record)
        return record
    # A continuous exported track is the user's *entire film timeline*, with
    # intentionally silent passages. Do not silently time-stretch or redistribute.
    if duration > _total(project) + .5:
        raise StudioError(f"Export {duration:.2f}s exceeds film duration {_total(project):.2f}s; align/export again")
    versions = sorted((root / "assets" / "voice_tracks").glob("jianying_full_v*")) if (root / "assets" / "voice_tracks").exists() else []
    dest_dir = root / "assets" / "voice_tracks"
    dest_dir.mkdir(parents=True, exist_ok=True)
    n = 1 + max((int(p.stem.split("_v")[-1]) for p in versions if p.stem.split("_v")[-1].isdigit()), default=0)
    dest = dest_dir / f"jianying_full_v{n:03d}{source.suffix.lower()}"
    shutil.copy2(source, dest)
    record = {"provider": "jianying_manual_export", "mode": "full_track",
              "path": dest.relative_to(root).as_posix(), "sha256": digest(dest),
              "project_sha256": digest(root / "project.json"),
              "duration_seconds": duration, "timeline_seconds": _total(project),
              "approved": False, "approval_note": None, "timings": None}
    write_json(root / RECORD, record)
    # Preserve edited alignment.json when it is already present.
    make_pack(root, project)
    return record


def _validated_timings(root: Path, project: dict, length: float) -> tuple[list[dict], str]:
    path = root / TIMINGS
    if not path.is_file():
        raise StudioError("Run jianying-pack to create alignment.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("project_sha256") != digest(root / "project.json"):
        raise StudioError("Storyboard changed after alignment template; recreate and review timings")
    raw = data.get("lines")
    if not isinstance(raw, list):
        raise StudioError("alignment.lines must be an array")
    expected = _rows(project)
    if [x.get("id") for x in raw] != [x["id"] for x in expected]:
        raise StudioError("alignment lines must match current edited dialogue IDs in order")
    prev = 0.0
    result = []
    for proposed, orig in zip(raw, expected):
        if proposed.get("text") != orig["text"] or proposed.get("speaker") != orig["speaker"]:
            raise StudioError(f"alignment line {orig['id']} changed speaker/text; keep approved script")
        start, end = proposed.get("start"), proposed.get("end")
        if (type(start) not in (int,float) or type(end) not in (int,float) or
                not prev <= start < end <= min(_total(project), length) + .1):
            raise StudioError(f"alignment {orig['id']} invalid, overlapping or exceeds actual exported track")
        result.append({**orig, "absolute_start": float(start), "absolute_end": float(end)})
        prev = float(end)
    return result, digest(path)


def approve(root: Path, project: dict, note: str) -> dict:
    if not note.strip():
        raise StudioError("Describe the actual listening/visual subtitle review in --note")
    root = root.resolve()
    record = _record(root)
    if not record or record.get("mode") != "full_track":
        raise StudioError("No full-timeline Jianying track was imported")
    path = (root / record["path"]).resolve()
    if not path.is_relative_to(root) or not path.is_file() or digest(path) != record["sha256"]:
        raise StudioError("Imported voice asset missing or changed")
    if record["project_sha256"] != digest(root / "project.json"):
        raise StudioError("Project edited after importing voice; reimport and confirm alignment")
    duration = _audio(path)
    rows, hash_value = _validated_timings(root, project, duration)
    if not rows:
        raise StudioError("No narration lines to align")
    record.update(approved=True, approval_note=note, timings=hash_value,
                  verified_line_count=len(rows))
    write_json(root / RECORD, record)
    (root / VOICE_DIR / "aligned_subtitles.srt").write_text("\n\n".join(
        f"{i}\n{srt_time(x['absolute_start'])} --> {srt_time(x['absolute_end'])}\n{x['speaker']}：{x['text']}"
        for i, x in enumerate(rows, 1)) + "\n", encoding="utf-8")
    return record


def approved_track(root: Path, project: dict, *, require: bool = False) -> tuple[Path, list[dict]] | None:
    """Return only an approved, unmodified full track and its real-timing subtitle rows."""
    root = root.resolve()
    record = _record(root)
    if not record:
        return None
    try:
        if not record.get("approved") or record.get("mode") != "full_track":
            raise StudioError("Jianying full narration is imported but not yet approved")
        path = (root / record["path"]).resolve()
        if not path.is_relative_to(root) or not path.is_file() or digest(path) != record["sha256"]:
            raise StudioError("Approved Jianying narration changed or disappeared")
        if digest(root / "project.json") != record["project_sha256"]:
            raise StudioError("Story/edit changed after approved narration: reimport/reapprove")
        rows, h = _validated_timings(root, project, float(record["duration_seconds"]))
        if h != record.get("timings"):
            raise StudioError("Alignment changed after approval: review and approve again")
        return path, rows
    except (KeyError, OSError, ValueError) as exc:
        raise StudioError("Jianying record invalid: import and approve again") from exc


def status(root: Path, project: dict) -> dict:
    root = root.resolve()
    record = _record(root)
    result = {"provider": "jianying_manual_export", "imported": bool(record),
              "mode": record.get("mode") if record else None,
              "approved": False, "line_count": len(_rows(project)),
              "note": "Uses visible Jianying desktop workflow, not a private API"}
    if record:
        try:
            verified = approved_track(root, project)
            result["approved"] = verified is not None
            if verified:
                result["audio_path"] = verified[0].relative_to(root).as_posix()
                result["aligned_lines"] = len(verified[1])
        except StudioError as exc:
            result["blocker"] = str(exc)
    return result
