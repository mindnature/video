"""Project schema, prompts, asset versioning, subtitle timings and FFmpeg rendering."""
from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

SHOT_ID = re.compile(r"^[A-Za-z0-9_-]+$")
VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm"}
AUDIO_EXTS = {".wav", ".mp3", ".m4a", ".flac"}


class StudioError(RuntimeError):
    pass


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def validate(project: dict) -> None:
    if not isinstance(project, dict):
        raise StudioError("project.json must contain a JSON object")
    if project.get("mode") not in ("handcraft", "story", "general"):
        raise StudioError("mode must be handcraft, story or general")
    if project.get("aspect_ratio") not in ("9:16", "16:9", "1:1", "3:4"):
        raise StudioError("aspect_ratio must be 9:16, 16:9, 1:1 or 3:4")
    if not isinstance(project.get("title"), str) or not project["title"].strip():
        raise StudioError("title is required")
    fps = project.get("fps", 30)
    if isinstance(fps, bool) or not isinstance(fps, int) or not 1 <= fps <= 60:
        raise StudioError("fps must be an integer between 1 and 60")
    shots = project.get("shots")
    if not isinstance(shots, list) or not shots:
        raise StudioError("shots must contain at least one shot")
    for field in ("characters", "subjects"):
        value = project.get(field, {})
        if not isinstance(value, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in value.items()):
            raise StudioError(f"{field} must be a dictionary of identity strings")
    post = project.get("postproduction", {})
    from .quality import SUPPORTED_STYLES, ACCEPTANCE_FIELDS
    if not isinstance(post, dict) or post.get("style", "clean") not in SUPPORTED_STYLES:
        raise StudioError(f"postproduction.style must be one of {sorted(SUPPORTED_STYLES)}")
    if post.get("style") == "surveillance":
        if post.get("clock_start") is not None:
            from .postfx import _clock_time
            try:
                _clock_time(post["clock_start"], 0, fps)
            except (ValueError, TypeError) as exc:
                raise StudioError(str(exc)) from exc
        for key, low, high in (("surveillance_fps", 1, fps), ("sensor_noise", 0, 30)):
            value = post.get(key)
            if value is not None and (type(value) is not int or not low <= value <= high):
                raise StudioError(f"postproduction.{key} must be an integer {low}..{high}")
    for flag in ("voice", "subtitles"):
        if post.get(flag, "auto") not in ("auto", "on", "off"):
            raise StudioError(f"postproduction.{flag} must be auto/on/off")
    from .delivery import validate_policy
    validate_policy(project)
    from .narrative import validate_story, validate_shot_edit, validate_continuity
    if "story_bible" in project:
        validate_story(project["story_bible"])
    if "continuity_required" in project and not isinstance(project["continuity_required"], bool):
        raise StudioError("continuity_required must be boolean")
    used = set()
    previous_shot = None
    for shot in shots:
        sid = shot.get("id")
        if not isinstance(sid, str) or not SHOT_ID.fullmatch(sid) or sid in used:
            raise StudioError(f"shot id invalid or duplicated: {sid!r}")
        used.add(sid)
        duration = shot.get("duration")
        if isinstance(duration, bool) or not isinstance(duration, (float, int)) or not 0 < duration <= 60:
            raise StudioError(f"shot {sid}: duration must be 0–60 seconds")
        for field in ("scene", "action", "camera"):
            if not isinstance(shot.get(field), str) or not shot[field].strip():
                raise StudioError(f"shot {sid}: missing {field}")
        for field in ("cast", "subject_ids"):
            members = shot.get(field, [])
            if not isinstance(members, list) or any(not isinstance(m, str) or not m for m in members):
                raise StudioError(f"shot {sid}: {field} must be a list of names")
        acceptance = shot.get("acceptance", {})
        if not isinstance(acceptance, dict) or any(k not in ACCEPTANCE_FIELDS for k in acceptance):
            raise StudioError(f"shot {sid}: unsupported acceptance field")
        for key, values in acceptance.items():
            if not isinstance(values, list) or any(not isinstance(v, str) or not v.strip() for v in values):
                raise StudioError(f"shot {sid}: acceptance.{key} must be nonempty strings")
        for sound in shot.get("sound_events", []):
            if not isinstance(sound, dict) or not isinstance(sound.get("path"), str) or not sound.get("path"):
                raise StudioError(f"shot {sid}: sound_event must specify path")
            t = sound.get("time")
            if isinstance(t, bool) or not isinstance(t, (int, float)) or not 0 <= t < duration:
                raise StudioError(f"shot {sid}: sound_event.time outside the shot")
            gain = sound.get("gain", 1.0)
            if isinstance(gain, bool) or not isinstance(gain, (int, float)) or not 0 <= gain <= 4:
                raise StudioError(f"shot {sid}: invalid sound_event.gain")
            raw = Path(sound["path"])
            if raw.is_absolute() or ".." in raw.parts or raw.suffix.lower() not in AUDIO_EXTS:
                raise StudioError(f"shot {sid}: sound_event must be a relative local audio file")
        hold = shot.get("hold_tail_seconds", min(1.0, duration / 4))
        if isinstance(hold, bool) or not isinstance(hold, (int, float)) or not 0 <= hold < duration:
            raise StudioError(f"shot {sid}: invalid hold_tail_seconds")
        previous_end = 0.0
        for beat in shot.get("beats", []):
            start, end = beat.get("start"), beat.get("end")
            if not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in (start, end)) or not (previous_end <= start < end <= duration):
                raise StudioError(f"shot {sid}: invalid/overlapping beats")
            if not isinstance(beat.get("visual"), str):
                raise StudioError(f"shot {sid}: beat must have visual text")
            previous_end = end
        validate_shot_edit(shot, previous_shot)
        validate_continuity(shot)
        previous_shot = shot
        for line in shot.get("dialogue", []):
            if not all(k in line for k in ("speaker", "text", "start", "end")):
                raise StudioError(f"shot {sid}: dialogue requires speaker/text/start/end")
            if not (isinstance(line["start"], (int, float)) and isinstance(line["end"], (int, float)) and 0 <= line["start"] < line["end"] <= duration):
                raise StudioError(f"shot {sid}: dialogue timing invalid")


def project_file(value: str | Path) -> Path:
    path = Path(value).expanduser().resolve()
    return path / "project.json" if path.is_dir() else path


def load_project(path: str | Path) -> tuple[Path, dict]:
    target = project_file(path)
    if not target.is_file():
        raise StudioError(f"project not found: {target}")
    data = read_json(target)
    validate(data)
    return target.parent, data


def shot_prompt(project: dict, shot: dict) -> str:
    """Build a *scoped* prompt from shot-local subjects, never the whole cast.

    A global identity describes appearance, not a permanent spatial state.
    Action, position and departure belong to each specific shot.
    """
    mode = project["mode"]
    ratio = project["aspect_ratio"]
    duration = shot["duration"]
    cast = shot.get("cast", [])
    people = project.get("characters", {})
    identities = [f"- {name}: {people[name]}" for name in cast if name in people]
    subjects = project.get("subjects", {})
    identities.extend(f"- {name}: {subjects[name]}" for name in shot.get("subject_ids", []) if name in subjects)
    listed = "\n".join(identities) if identities else "- 无需额外的全局身份词"
    materials = "、".join(shot.get("materials", [])) or "以场景动作要求为准"
    beats = "\n".join(f"[{b['start']:05.2f}-{b['end']:05.2f}秒] {b['visual']}"
                      for b in shot.get("beats", [])) or f"[00.00-{duration:.2f}秒] {shot['action']}"
    lines = "\n".join(f"[{l['start']:.2f}-{l['end']:.2f}秒] {l['speaker']}说：{l['text']}；其他在场角色不说话。"
                      for l in shot.get("dialogue", [])) or "无台词，保留合适的现场环境声音。"
    constraints = (
        "真实手工工艺：实际材料可辨，接触、固定、厚度和遮挡符合物理逻辑；"
        "工序由人物或工具完成，不允许物体瞬间出现或自发运动。" if mode == "handcraft" else
        "遵循真实空间、人物数量和可拍摄的动作顺序；跨镜头保持身份一致，但位置与姿态只由本镜动作规定。"
        if mode == "story" else
        "尊重主体外观与真实物理关系；根据本镜设定选择镜头运动和表演，不添加未授权主体。"
    )
    acc = shot.get("acceptance", {})
    acc_names = {"start_visible": "起始必须出现", "end_visible": "结束必须出现", "end_absent": "结束不得出现",
                 "required_events": "必须发生的动作事件", "audio_checks": "待核实的声音事件"}
    acceptance = "\n".join(f"- {acc_names[key]}：{'、'.join(acc[key])}" for key in acc_names if acc.get(key))
    acceptance = acceptance or "- 依照本镜动作结尾验收；检查末尾关键帧。"
    from .narrative import edit_range
    start, end = edit_range(shot)
    cont = shot.get("continuity", {})
    direction = (f"叙事目的：{shot.get('narrative_purpose', '遵循本镜动作')}。"
                 f"情绪：{shot.get('emotional_state', '自然表演')}。"
                 f"景别与主体：{shot.get('framing', shot['camera'])}。\n"
                 f"进入状态：{json.dumps(cont.get('entry', {}), ensure_ascii=False)}。"
                 f"退出状态：{json.dumps(cont.get('exit', {}), ensure_ascii=False)}。"
                 f"与前镜衔接：{cont.get('link_from_previous', '根据场景自然衔接')}。\n"
                 f"预计有效剪入区间：原生成素材 {start:g}-{end:g} 秒（不要将整段生成时长当作必须使用的镜头时长）。\n")
    return (
        f"# 镜头 {shot['id']}｜{shot['scene']}\n"
        f"画幅 {ratio}，时长 {duration} 秒，{project.get('style', '自然真实影视风格')}。\n"
        f"场景：{shot['scene']}。镜头：{shot['camera']}。\n"
        f"本镜目标/动作：{shot['action']}\n"
        f"导演设计：{direction}"
        f"本镜出场人物和主体身份（身份描述不是永久站位指令）：\n{listed}\n"
        f"材料/道具：{materials}\n"
        f"动作时间轴：\n{beats}\n"
        f"台词：\n{lines}\n"
        f"镜头验收目标：\n{acceptance}\n"
        f"制作约束：{constraints}\n"
        f"结尾预留约 {shot.get('hold_tail_seconds', min(1.0, duration / 4)):g} 秒，自然结束动作并保持可验证的结束状态。"
        "画面不直接生成字幕、水印、时间码、监控UI及其它文字（风格包装留到后期）。"
        "动态镜头或固定机位以本镜 camera 为准。实际生成后必须依据视频验收目标人工检查。\n"
    )


def srt_time(seconds: float) -> str:
    milliseconds = round(seconds * 1000)
    hrs, remainder = divmod(milliseconds, 3600 * 1000)
    mins, remainder = divmod(remainder, 60 * 1000)
    sec, ms = divmod(remainder, 1000)
    return f"{hrs:02d}:{mins:02d}:{sec:02d},{ms:03d}"


def lines_with_offsets(project: dict) -> list[dict]:
    from .narrative import timeline
    result: list[dict] = []
    by_id = {entry["id"]: entry for entry in timeline(project)}
    for shot in project["shots"]:
        entry = by_id[shot["id"]]
        for i, dialogue in enumerate(shot.get("dialogue", []), start=1):
            visible_start = max(float(dialogue["start"]), entry["source_in"])
            visible_end = min(float(dialogue["end"]), entry["source_out"])
            if visible_start >= visible_end:
                continue  # Dialogue outside the final editorial range.
            item = dict(dialogue)
            item.update(id=f"{shot['id']}_{i:02d}", shot=shot["id"],
                        absolute_start=entry["timeline_in"] + visible_start - entry["source_in"],
                        absolute_end=entry["timeline_in"] + visible_end - entry["source_in"])
            result.append(item)
    return result


def export(project_root: Path, project: dict) -> Path:
    output = project_root / "production"
    (output / "prompts").mkdir(parents=True, exist_ok=True)
    rows = ["# 分镜总表", "", f"片名：{project['title']} | {project['aspect_ratio']} | {project['mode']}", ""]
    for shot in project["shots"]:
        (output / "prompts" / f"shot_{shot['id']}.txt").write_text(shot_prompt(project, shot), encoding="utf-8")
        rows.extend([f"## {shot['id']} · {shot['scene']}（{shot['duration']}秒）",
                     f"镜头：{shot['camera']}", f"动作：{shot['action']}", ""])
    (output / "storyboard.md").write_text("\n".join(rows), encoding="utf-8")
    from .narrative import export_narrative
    export_narrative(project_root, project)
    from .quality import audit_plan
    write_json(output / "plan_audit.json", audit_plan(project))
    review = output / "review"
    review.mkdir(exist_ok=True)
    from .quality import acceptance_checks
    for shot in project["shots"]:
        write_json(review / f"shot_{shot['id']}_criteria.json", {
            "shot": shot["id"], "scene": shot["scene"],
            "checks": acceptance_checks(shot), "human_verification_required": True})
    dialogues = lines_with_offsets(project)
    with (output / "voice_lines.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["id", "shot", "speaker", "text", "start", "end", "absolute_start", "absolute_end"])
        writer.writeheader()
        writer.writerows({k: row[k] for k in writer.fieldnames} for row in dialogues)
    subtitles = "\n\n".join(
        f"{n}\n{srt_time(d['absolute_start'])} --> {srt_time(d['absolute_end'])}\n{d['speaker']}：{d['text']}"
        for n, d in enumerate(dialogues, start=1)
    )
    (output / "subtitles.srt").write_text(subtitles + ("\n" if subtitles else ""), encoding="utf-8")
    write_json(output / "shot_list.json", [{"id": s["id"], "duration": s["duration"], "prompt": f"prompts/shot_{s['id']}.txt"} for s in project["shots"]])
    return output


def digest(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            sha.update(block)
    return sha.hexdigest()


def asset_index(root: Path) -> dict:
    path = root / "assets" / "index.json"
    return read_json(path) if path.exists() else {"shots": {}, "voice": {}}


def ingest(root: Path, project: dict, shot: str, source: Path, kind: str, line_id: str | None = None) -> Path:
    source = source.expanduser().resolve()
    if not source.is_file():
        raise StudioError(f"source not found: {source}")
    ids = {item["id"] for item in project["shots"]}
    if shot not in ids:
        raise StudioError(f"unknown shot: {shot}")
    if kind not in ("video", "voice"):
        raise StudioError("kind must be video or voice")
    if kind == "video" and source.suffix.lower() not in VIDEO_EXTS:
        raise StudioError(f"not a supported video file: {source.suffix}")
    if kind == "voice":
        if source.suffix.lower() not in AUDIO_EXTS:
            raise StudioError(f"not a supported audio file: {source.suffix}")
        valid_line_ids = {item["id"] for item in lines_with_offsets(project)}
        if not line_id or line_id not in valid_line_ids or not line_id.startswith(shot + "_"):
            raise StudioError(f"invalid voice line id for shot {shot}: {line_id}")
    index = asset_index(root)
    category = "shots" if kind == "video" else "voice"
    key = shot if kind == "video" else line_id
    versions = index.setdefault(category, {}).setdefault(key, [])
    dest_folder = root / "assets" / ("raw" if kind == "video" else "voice") / f"shot_{shot}"
    dest_folder.mkdir(parents=True, exist_ok=True)
    dest = dest_folder / f"{key}_v{len(versions)+1:03d}{source.suffix.lower()}"
    shutil.copy2(source, dest)
    versions.append({"path": dest.relative_to(root).as_posix(), "sha256": digest(dest), "bytes": dest.stat().st_size})
    write_json(root / "assets" / "index.json", index)
    return dest


def selected_asset(root: Path, index: dict, category: str, key: str) -> Path | None:
    versions = index.get(category, {}).get(key, [])
    if not versions:
        return None
    selection_file = root / "assets" / "selection.json"
    if selection_file.is_file():
        selection = read_json(selection_file).get(category, {}).get(key)
        if selection and selection in {v["path"] for v in versions}:
            return root / selection
    return root / versions[-1]["path"]


def need_binary(name: str) -> str:
    command = shutil.which(name)
    if not command:
        raise StudioError(f"Missing executable: {name}. Install FFmpeg (includes ffprobe) and retry.")
    return command


def run(command: list[str]) -> None:
    try:
        subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    except subprocess.CalledProcessError as e:
        raise StudioError(f"command failed: {' '.join(command[:5])}\n{e.stderr[-2000:]}") from e


def probe(path: Path) -> dict:
    ffprobe = need_binary("ffprobe")
    output = subprocess.run([ffprobe, "-v", "error", "-show_entries", "format=duration:stream=codec_type,width,height", "-of", "json", str(path)], capture_output=True, text=True, check=True)
    return json.loads(output.stdout)


def dimensions(aspect: str) -> tuple[int, int]:
    return {"9:16": (1080, 1920), "16:9": (1920, 1080), "1:1": (1080, 1080), "3:4": (1080, 1440)}[aspect]


def available_output(path: Path) -> Path:
    if not path.exists():
        return path
    i = 2
    while True:
        candidate = path.with_name(f"{path.stem}_v{i:03d}{path.suffix}")
        if not candidate.exists():
            return candidate
        i += 1



def join_edited_clips(pieces: list[Path], shots: list[dict], joined: Path, fps: int) -> None:
    """Join cuts and optional short AV dissolves on a *real edited timeline*.

    Match cuts/eyelines are director semantics and remain hard cuts. Dissolve
    is the only overlap transition implemented in FFmpeg; no silent fake effect.
    """
    from .narrative import edit_duration, transition_duration
    ffmpeg = need_binary("ffmpeg")
    if len(pieces) == 1:
        shutil.copy2(pieces[0], joined)
        return
    if not any(transition_duration(shot) for shot in shots[1:]):
        listing = joined.parent / "concat.txt"
        listing.write_text("".join("file '" + p.as_posix().replace("'", "'\\''") + "'\n" for p in pieces), encoding="utf-8")
        run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(listing),
             "-c", "copy", "-movflags", "+faststart", str(joined)])
        return
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y"]
    for piece in pieces:
        cmd.extend(["-i", str(piece)])
    filters = []
    vl, al, length = "0:v", "0:a", edit_duration(shots[0])
    for i, shot in enumerate(shots[1:], 1):
        delta = transition_duration(shot)
        next_v, next_a = f"v{i}", f"a{i}"
        if delta:
            # xfade expects identical size, fps, timebase and pixel format.
            # Normalize the joined operand before it is fed into subsequent fades.
            filters.append(f"[{vl}][{i}:v]xfade=transition=fade:duration={delta:g}:offset={length-delta:g}[{next_v}]")
            filters.append(f"[{al}][{i}:a]acrossfade=d={delta:g}:c1=tri:c2=tri[{next_a}]")
        else:
            filters.append(f"[{vl}][{al}][{i}:v][{i}:a]concat=n=2:v=1:a=1[{next_v}][{next_a}]")
        length += edit_duration(shot) - delta
        vl, al = next_v, next_a
    cmd += ["-filter_complex", ";".join(filters), "-map", f"[{vl}]", "-map", f"[{al}]",
            "-r", str(fps), "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-ar", "48000", "-b:a", "192k", "-movflags", "+faststart", str(joined)]
    run(cmd)

def render(root: Path, project: dict, output: Path | None = None, mix_voice: bool | None = None, burn_subtitles: bool | None = None, shot_ids: list[str] | None = None) -> Path:
    ffmpeg = need_binary("ffmpeg")
    # Preserve original project order regardless of which shots the caller requests.
    selected_project = project if shot_ids is None else dict(project, shots=[s for s in project["shots"] if s["id"] in shot_ids])
    from .narrative import edit_range, edit_duration, timeline
    if not selected_project["shots"]:
        raise StudioError("No shots selected for render")
    post = project.get("postproduction", {})
    index = asset_index(root)
    voice_files = any(selected_asset(root, index, "voice", l["id"]) for l in lines_with_offsets(selected_project))
    if mix_voice is None:
        mix_voice = post.get("voice", "auto") == "on" or (post.get("voice", "auto") == "auto" and voice_files)
    if burn_subtitles is None:
        burn_subtitles = post.get("subtitles", "auto") == "on" or (post.get("subtitles", "auto") == "auto" and bool(lines_with_offsets(selected_project)))
    output = (output or root / "exports" / "final_master.mp4").expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output = available_output(output)
    width, height = dimensions(project["aspect_ratio"])
    fps = project.get("fps", 30)
    work = root / "work" / "cuts"
    work.mkdir(parents=True, exist_ok=True)
    pieces = []
    source_offsets = {entry["id"]: entry["timeline_in"] for entry in timeline(project)}
    for shot in selected_project["shots"]:
        src = selected_asset(root, index, "shots", shot["id"])
        if not src or not src.is_file():
            raise StudioError(f"Missing video for shot {shot['id']}; run ingest first")
        info = probe(src)
        if not any(s.get("codec_type") == "video" for s in info.get("streams", [])):
            raise StudioError(f"Shot {shot['id']} has no video stream")
        has_audio = any(s.get("codec_type") == "audio" for s in info.get("streams", []))
        duration = edit_duration(shot)
        source_in, source_out = edit_range(shot)
        dest = work / f"cut_{shot['id']}.mp4"
        # Scale to fit WITHOUT cropping or stretching original artwork.
        from .postfx import style_filters
        fx = style_filters(project, shot, width, height, fps, source_offsets[shot["id"]])
        video_filter = (f"[0:v]tpad=stop_mode=clone:stop_duration={shot['duration']:g},"
                        f"trim=start={source_in:g}:end={source_out:g},setpts=PTS-STARTPTS,"
                        f"fps={fps},scale={width}:{height}:force_original_aspect_ratio=decrease:flags=lanczos,"
                        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,"
                        "setpts=PTS-STARTPTS" + ("," + ",".join(fx) if fx else "") + ",format=yuv420p[v]")
        cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(src)]
        ainput = "0:a:0"
        if not has_audio:
            cmd += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
            ainput = "1:a:0"
        afilter = (f"[{ainput}]aresample=48000,apad,atrim=start={source_in:g}:end={source_out:g},"
                   "asetpts=PTS-STARTPTS[a]")
        cmd += ["-filter_complex", video_filter + ";" + afilter, "-map", "[v]", "-map", "[a]",
                "-r", str(fps), "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-ar", "48000", "-b:a", "192k", "-movflags", "+faststart", str(dest)]
        run(cmd)
        pieces.append(dest)
    joined = root / "work" / "joined.mp4"
    join_edited_clips(pieces, selected_project["shots"], joined, fps)
    current = joined
    voices = []
    for line in lines_with_offsets(selected_project):
        file = selected_asset(root, index, "voice", line["id"])
        if mix_voice and file and file.is_file():
            voices.append((line["absolute_start"], file, 1.0))
    effects = []
    selected_timeline = {entry["id"]: entry for entry in timeline(selected_project)}
    for shot in selected_project["shots"]:
        entry = selected_timeline[shot["id"]]
        for cue in shot.get("sound_events", []):
            asset = (root / cue["path"]).resolve()
            if not asset.is_relative_to(root.resolve()) or not asset.is_file():
                raise StudioError(f"Missing or unsafe sound effect for shot {shot['id']}: {cue['path']}")
            if entry["source_in"] <= cue["time"] < entry["source_out"]:
                effects.append((entry["timeline_in"] + cue["time"] - entry["source_in"], asset, float(cue.get("gain", 1.0))))
    if voices or effects:
        voiced = root / "work" / "voiced.mp4"
        cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(current)]
        bed_gain = float(post.get("original_audio_gain", 0.35 if voices else 1.0))
        if not 0 <= bed_gain <= 2:
            raise StudioError("postproduction.original_audio_gain must be 0..2")
        filter_parts = [f"[0:a]volume={bed_gain}[bed]"]
        mix = ["[bed]"]
        for i, (when, asset, gain) in enumerate(voices + effects, start=1):
            cmd += ["-i", str(asset)]
            delay = round(when * 1000)
            filter_parts.append(f"[{i}:a]aresample=48000,adelay={delay}:all=1,volume={gain}[a{i}]")
            mix.append(f"[a{i}]")
        filter_parts.append("".join(mix) + f"amix=inputs={len(mix)}:duration=first:dropout_transition=0[a]")
        cmd += ["-filter_complex", ";".join(filter_parts), "-map", "0:v", "-map", "[a]", "-c:v", "copy",
                "-c:a", "aac", "-b:a", "192k", str(voiced)]
        run(cmd)
        current = voiced
    if burn_subtitles:
        captions = lines_with_offsets(selected_project)
        if not captions:
            raise StudioError("No dialogue to burn; use captions only for projects with dialogue")
        subtitle = root / "work" / "render_subtitles.srt"
        subtitle.write_text("\n\n".join(
            f"{n}\n{srt_time(d['absolute_start'])} --> {srt_time(d['absolute_end'])}\n{d['speaker']}：{d['text']}"
            for n, d in enumerate(captions, start=1)) + "\n", encoding="utf-8")
        # FFmpeg subtitle filter interprets colons/backslashes specially, especially on Windows.
        safe_path = subtitle.as_posix().replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
        run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(current),
             "-vf", f"subtitles='{safe_path}'", "-c:v", "libx264", "-crf", "19", "-preset", "medium",
             "-c:a", "copy", str(output)])
    else:
        shutil.copy2(current, output)
    return output


def qa(root: Path, project: dict) -> dict:
    from .quality import audit_plan
    plan = audit_plan(project)
    index = asset_index(root)
    checks = list(plan["findings"])
    voice_policy = project.get("postproduction", {}).get("voice", "auto")
    for shot in project["shots"]:
        src = selected_asset(root, index, "shots", shot["id"])
        if not src or not src.is_file():
            checks.append({"shot": shot["id"], "level": "ERROR", "message": "missing video"})
            continue
        try:
            info = probe(src)
            duration = float(info.get("format", {}).get("duration", 0))
            videos = [stream for stream in info.get("streams", []) if stream.get("codec_type") == "video"]
            if not videos:
                checks.append({"shot": shot["id"], "level": "ERROR", "message": "no video stream"})
            from .narrative import edit_range
            required_source_end = edit_range(shot)[1]
            if duration < required_source_end - 0.2:
                checks.append({"shot": shot["id"], "level": "WARN", "message": f"raw clip {duration:.2f}s shorter than editorial source_out {required_source_end:g}s; render will freeze-pad"})
            if not any(stream.get("codec_type") == "audio" for stream in info.get("streams", [])):
                checks.append({"shot": shot["id"], "level": "INFO", "message": "no source audio; a silent track will be generated"})
        except (StudioError, subprocess.CalledProcessError, ValueError) as err:
            checks.append({"shot": shot["id"], "level": "ERROR", "message": str(err)})
        for cue in shot.get("sound_events", []):
            sound = (root / cue["path"]).resolve()
            if not sound.is_relative_to(root.resolve()) or not sound.is_file():
                checks.append({"shot": shot["id"], "level": "ERROR", "message": f"missing sound cue: {cue['path']}"})
    for line in lines_with_offsets(project):
        file = selected_asset(root, index, "voice", line["id"])
        if not file:
            checks.append({"shot": line["shot"], "level": "ERROR" if voice_policy == "on" else "WARN",
                           "message": f"no replacement voice for {line['id']}; source speech may still be used"})
        else:
            try:
                duration = float(probe(file).get("format", {}).get("duration", 0))
                window = line["end"] - line["start"]
                if duration > window + .15:
                    checks.append({"shot": line["shot"], "level": "WARN", "message": f"voice {line['id']} {duration:.2f}s exceeds scheduled {window:.2f}s; manually retime speech/subtitles"})
            except Exception:
                checks.append({"shot": line["shot"], "level": "WARN", "message": f"cannot inspect audio timing for {line['id']}"})
    return {"project": project["title"], "checks": checks,
            "ready": not any(item["level"] == "ERROR" for item in checks),
            "limitations": "Metadata and planned-time QA only: actual events, lips, consonants, contact sync and visible end-state need human/vision verification."}
