"""Optional, rendered FFmpeg looks. Generation remains free of text and HUD.

Styles are opt-in. Surveillance is deliberately CCTV-like, including a moving
clock, REC/camera ID, reduced temporal detail, muted colors and sensor noise.
"""
from __future__ import annotations

import re


def _escape_text(s: str) -> str:
    # drawtext parsing: escape the filter parser's and expression parser's metacharacters.
    return (s.replace("\\", "\\\\").replace("'", "\\'").replace(":", "\\:")
             .replace("%", "\\%").replace("[", "\\[").replace("]", "\\]"))


def _clock_time(clock: str, elapsed: float, fps: int) -> str:
    if not re.fullmatch(r"\d\d:\d\d:\d\d", clock):
        raise ValueError("postproduction.clock_start must be HH:MM:SS")
    h, m, s = map(int, clock.split(":"))
    if h > 23 or m > 59 or s > 59:
        raise ValueError("postproduction.clock_start is not a valid time")
    frames = round(elapsed * fps)
    whole, ff = divmod(frames, fps)
    time = (h * 3600 + m * 60 + s + whole) % 86400
    return f"{time // 3600:02d}:{(time // 60) % 60:02d}:{time % 60:02d}:{ff:02d}"


def style_filters(project: dict, shot: dict, width: int, height: int, fps: int, elapsed: float = 0) -> list[str]:
    settings = project.get("postproduction", {})
    name = settings.get("style", "clean")
    if name == "clean":
        return []
    if name == "cinematic":
        return ["eq=contrast=1.07:saturation=0.94", "vignette=angle=PI/5"]
    if name == "vintage":
        return ["eq=contrast=1.04:saturation=0.70", "noise=alls=5:allf=t"]
    if name != "surveillance":
        raise ValueError(f"Unknown style: {name}")
    effective = int(settings.get("surveillance_fps", min(fps, 15)))
    if not 1 <= effective <= fps:
        raise ValueError("surveillance_fps must be 1..output fps")
    noise = int(settings.get("sensor_noise", 7))
    if not 0 <= noise <= 30:
        raise ValueError("sensor_noise must be 0..30")
    camera = str(shot.get("camera_id", f"{settings.get('camera_prefix', 'CAM')}-{shot['id']}"))[:48]
    location = str(shot.get("location", settings.get("location", "")))[:48]
    label = _escape_text(f"REC  {camera}" + (f"  {location}" if location else ""))
    clock = _clock_time(str(settings.get("clock_start", "00:00:00")), elapsed, fps)
    tc = _escape_text(clock)
    margin = max(12, width // 45)
    font_size = max(16, width // 52)
    filters = [
        f"fps={effective},fps={fps}",
        f"scale={max(2, width//2//2*2)}:{max(2, height//2//2*2)}:flags=bicubic,scale={width}:{height}:flags=neighbor",
        "eq=contrast=1.06:saturation=0.58:brightness=-0.015",
        f"noise=alls={noise}:allf=t",
        "vignette=angle=PI/4",
        f"drawtext=text='{label}':fontcolor=white:fontsize={font_size}:x={margin}:y={margin}:box=1:boxcolor=black@0.42:boxborderw=8",
        # FFmpeg timecode parameter increments per video frame. It is consistent across shots.
        f"drawtext=timecode='{tc}':r={fps}:fontcolor=white:fontsize={font_size}:x=w-tw-{margin}:y={margin}:box=1:boxcolor=black@0.42:boxborderw=8",
    ]
    return filters
