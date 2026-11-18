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
    if project.get("mode") not in ("handcraft", "story"):
        raise StudioError("mode must be 'handcraft' or 'story'")
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
    used = set()
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
        previous_end = 0.0
        for beat in shot.get("beats", []):
            start, end = beat.get("start"), beat.get("end")
            if not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in (start, end)) or not (previous_end <= start < end <= duration):
                raise StudioError(f"shot {sid}: invalid/overlapping beats")
            if not isinstance(beat.get("visual"), str):
                raise StudioError(f"shot {sid}: beat must have visual text")
            previous_end = end
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
    mode = project["mode"]
    ratio = project["aspect_ratio"]
    duration = shot["duration"]
    chars = project.get("characters", {})
    listed_chars = "\n".join(f"- {name}: {description}" for name, description in chars.items()) or "- 无人物表演"
    materials = "、".join(shot.get("materials", [])) or "依照场景描述"
    beats = "\n".join(
        f"[{b['start']:05.2f}-{b['end']:05.2f}秒] {b['visual']}"
        for b in shot.get("beats", [])
    ) or f"[00.00-{duration:.2f}秒] {shot['action']}"
    lines = "\n".join(
        f"[{l['start']:.2f}-{l['end']:.2f}秒] 仅{l['speaker']}说：{l['text']}；其他人保持闭嘴。"
        for l in shot.get("dialogue", [])
    ) or "无人物台词，只保留真实环境音、材料摩擦声。"
    constraints = (
        "真实桌面手工制作纪录片。材料必须保留其真实物性、厚度、叶脉/纽扣孔洞和自然遮挡；"
        "每一步必须由人的手和工具完成，不得凭空变形、自动出现、悬浮或跳过工序；"
        "避免跨镜头工具/材料位置跳变。" if mode == "handcraft" else
        "真人影视质感，角色外貌与服饰跨镜头保持一致；不超过三名主要演员，"
        "避免复杂肢体交缠、混乱群戏和镜头外突然新增角色。"
    )
    return (
        f"# 镜头 {shot['id']}｜{shot['scene']}\n"
        f"画幅 {ratio}，时长 {duration} 秒，{project.get('style', '自然真实影视风格')}。\n"
        f"场景：{shot['scene']}。镜头：{shot['camera']}。\n"
        f"本镜目标/动作：{shot['action']}\n"
        f"固定人物设定（跨镜头逐字沿用）：\n{listed_chars}\n"
        f"真实材料：{materials}\n"
        f"动作时间轴：\n{beats}\n"
        f"台词和声音：\n{lines}\n"
        f"制作约束：{constraints}\n"
        "最后约 1 秒停止新动作，留下自然反应与剪辑余量。"
        "无字幕、无水印、无时间码、无UI图层、无背景音乐。"
        "镜头内部时间轴仅为生成指令，生成后需人工核查实际动作与音轨。\n"
    )


def srt_time(seconds: float) -> str:
    milliseconds = round(seconds * 1000)
    hrs, remainder = divmod(milliseconds, 3600 * 1000)
    mins, remainder = divmod(remainder, 60 * 1000)
    sec, ms = divmod(remainder, 1000)
    return f"{hrs:02d}:{mins:02d}:{sec:02d},{ms:03d}"


def lines_with_offsets(project: dict) -> list[dict]:
    result: list[dict] = []
    offset = 0.0
    for shot in project["shots"]:
        for i, dialogue in enumerate(shot.get("dialogue", []), start=1):
            item = dict(dialogue)
            item.update(id=f"{shot['id']}_{i:02d}", shot=shot["id"],
                        absolute_start=offset + dialogue["start"],
                        absolute_end=offset + dialogue["end"])
            result.append(item)
        offset += shot["duration"]
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


def render(root: Path, project: dict, output: Path | None = None, mix_voice: bool = False, burn_subtitles: bool = False) -> Path:
    ffmpeg = need_binary("ffmpeg")
    index = asset_index(root)
    output = (output or root / "exports" / "final_master.mp4").expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output = available_output(output)
    width, height = dimensions(project["aspect_ratio"])
    fps = project.get("fps", 30)
    work = root / "work" / "cuts"
    work.mkdir(parents=True, exist_ok=True)
    pieces = []
    for shot in project["shots"]:
        src = selected_asset(root, index, "shots", shot["id"])
        if not src or not src.is_file():
            raise StudioError(f"Missing video for shot {shot['id']}; run ingest first")
        info = probe(src)
        if not any(s.get("codec_type") == "video" for s in info.get("streams", [])):
            raise StudioError(f"Shot {shot['id']} has no video stream")
        has_audio = any(s.get("codec_type") == "audio" for s in info.get("streams", []))
        duration = shot["duration"]
        dest = work / f"cut_{shot['id']}.mp4"
        # Scale to fit WITHOUT cropping or stretching original artwork.
        video_filter = (f"[0:v]fps={fps},scale={width}:{height}:force_original_aspect_ratio=decrease:flags=lanczos,"
                        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,"
                        f"tpad=stop_mode=clone:stop_duration={duration},trim=duration={duration},"
                        "setpts=PTS-STARTPTS,format=yuv420p[v]")
        cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(src)]
        ainput = "0:a:0"
        if not has_audio:
            cmd += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
            ainput = "1:a:0"
        afilter = f"[{ainput}]aresample=48000,apad,atrim=duration={duration},asetpts=PTS-STARTPTS[a]"
        cmd += ["-filter_complex", video_filter + ";" + afilter, "-map", "[v]", "-map", "[a]",
                "-r", str(fps), "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-ar", "48000", "-b:a", "192k", "-movflags", "+faststart", str(dest)]
        run(cmd)
        pieces.append(dest)
    listing = root / "work" / "concat.txt"
    listing.parent.mkdir(parents=True, exist_ok=True)
    listing.write_text("".join(f"file '{p.as_posix().replace(chr(39), chr(39)+chr(92)+chr(39)+chr(39))}'\n" for p in pieces), encoding="utf-8")
    joined = root / "work" / "joined.mp4"
    run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(listing),
         "-c", "copy", "-movflags", "+faststart", str(joined)])
    current = joined
    if mix_voice:
        voices = []
        for line in lines_with_offsets(project):
            file = selected_asset(root, index, "voice", line["id"])
            if file and file.is_file():
                voices.append((line, file))
        if voices:
            voiced = root / "work" / "voiced.mp4"
            cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(current)]
            filter_parts = ["[0:a]volume=0.35[bed]"]
            mix = ["[bed]"]
            for i, (line, file) in enumerate(voices, start=1):
                cmd += ["-i", str(file)]
                delay = round(line["absolute_start"] * 1000)
                filter_parts.append(f"[{i}:a]aresample=48000,adelay={delay}:all=1,volume=1.0[v{i}]")
                mix.append(f"[v{i}]")
            filter_parts.append("".join(mix) + f"amix=inputs={len(mix)}:duration=first:dropout_transition=0[a]")
            cmd += ["-filter_complex", ";".join(filter_parts), "-map", "0:v", "-map", "[a]", "-c:v", "copy",
                    "-c:a", "aac", "-b:a", "192k", str(voiced)]
            run(cmd)
            current = voiced
    if burn_subtitles:
        if not lines_with_offsets(project):
            raise StudioError("No dialogue to burn; use captions only for projects with dialogue")
        subtitle = export(root, project) / "subtitles.srt"
        # FFmpeg subtitle filter interprets colons/backslashes specially, especially on Windows.
        safe_path = subtitle.as_posix().replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
        run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(current),
             "-vf", f"subtitles='{safe_path}'", "-c:v", "libx264", "-crf", "19", "-preset", "medium",
             "-c:a", "copy", str(output)])
    else:
        shutil.copy2(current, output)
    return output


def qa(root: Path, project: dict) -> dict:
    index = asset_index(root)
    checks = []
    for shot in project["shots"]:
        src = selected_asset(root, index, "shots", shot["id"])
        if not src or not src.is_file():
            checks.append({"shot": shot["id"], "level": "ERROR", "message": "missing video"})
            continue
        try:
            info = probe(src)
            duration = float(info.get("format", {}).get("duration", 0))
            videos = [s for s in info.get("streams", []) if s.get("codec_type") == "video"]
            if not videos:
                checks.append({"shot": shot["id"], "level": "ERROR", "message": "no video stream"})
            if duration < shot["duration"] - 0.2:
                checks.append({"shot": shot["id"], "level": "WARN", "message": f"raw clip {duration:.2f}s shorter than target {shot['duration']}s; render will freeze-pad"})
            if not any(s.get("codec_type") == "audio" for s in info.get("streams", [])):
                checks.append({"shot": shot["id"], "level": "INFO", "message": "no audio stream; silent track will be generated"})
        except (StudioError, subprocess.CalledProcessError, ValueError) as err:
            checks.append({"shot": shot["id"], "level": "ERROR", "message": str(err)})
    for line in lines_with_offsets(project):
        if not selected_asset(root, index, "voice", line["id"]):
            checks.append({"shot": line["shot"], "level": "INFO", "message": f"no replacement voice for {line['id']}"})
    return {"project": project["title"], "checks": checks,
            "ready": not any(item["level"] == "ERROR" for item in checks),
            "limitations": "Metadata-level QA only. Human review is required for faces, finger anatomy, physical process, sync, subtitle readability and sound."}
