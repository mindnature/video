"""One-person AI film crew CLI. Run `python -m videostudio --help`."""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from . import __version__
from .core import StudioError, export, ingest, load_project, qa, render, write_json
from .llm import draft
from .templates import preset


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="video-studio", description="Local-first AI film production orchestrator")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="create an editable shot project")
    init.add_argument("name", help="directory to create")
    init.add_argument("--preset", choices=["handcraft", "story"], default="handcraft")
    init.add_argument("--title", default="未命名作品")
    init.add_argument("--force", action="store_true", help="overwrite project.json ONLY")
    planning = sub.add_parser("plan", help="export shot prompts, storyboard, CSV voice lines and SRT")
    planning.add_argument("project", help="project directory or project.json")
    d = sub.add_parser("draft", help="optional LLM-assisted idea-to-shot JSON")
    d.add_argument("name", help="new project directory")
    d.add_argument("--idea", required=True)
    d.add_argument("--preset", choices=["handcraft", "story"], default="handcraft")
    d.add_argument("--title", default="未命名作品")
    d.add_argument("--shots", type=int)
    incoming = sub.add_parser("ingest", help="version and hash an existing video/voice asset")
    incoming.add_argument("project")
    incoming.add_argument("--shot", required=True)
    incoming.add_argument("--file", required=True, type=Path)
    incoming.add_argument("--kind", choices=["video", "voice"], default="video")
    incoming.add_argument("--line", help="dialogue ID (e.g. 01_01) when --kind voice")
    making = sub.add_parser("render", help="normalize clips, concatenate, optionally mix voice and burn subtitles")
    making.add_argument("project")
    making.add_argument("--output", type=Path)
    making.add_argument("--mix-voice", action="store_true")
    making.add_argument("--burn-subtitles", action="store_true")
    review = sub.add_parser("qa", help="metadata checks and missing-asset report")
    review.add_argument("project")
    flow = sub.add_parser("flow-assist", help="populate Google Flow prompt in one open user Chrome tab")
    flow.add_argument("prompt", type=Path)
    flow.add_argument("--selector", help="verified CSS textbox selector")
    flow.add_argument("--button", help="verified CSS submit button selector")
    flow.add_argument("--submit", action="store_true", help="explicitly click generation after filling")
    sub.add_parser("doctor", help="check local FFmpeg and browser adapter requirements")
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "init":
            root = Path(args.name).expanduser().resolve()
            target = root / "project.json"
            if target.exists() and not args.force:
                raise StudioError(f"{target} already exists; omit --force to protect it")
            write_json(target, preset(args.preset, args.title))
            print(f"Created {target}\nNext: video-studio plan {root}")
        elif args.command == "draft":
            root = Path(args.name).expanduser().resolve()
            if (root / "project.json").exists():
                raise StudioError("project.json already exists; no overwrite allowed")
            if args.shots is not None and not (1 <= args.shots <= 20):
                raise StudioError("--shots must be 1–20")
            result = draft(args.idea, args.preset, args.title, args.shots)
            write_json(root / "project.json", result)
            print(f"Draft created: {root / 'project.json'}; review each shot before plan/render")
        elif args.command == "plan":
            root, project = load_project(args.project)
            print(f"Generated production kit: {export(root, project)}")
        elif args.command == "ingest":
            root, project = load_project(args.project)
            print(f"Archived: {ingest(root, project, args.shot, args.file, args.kind, args.line)}")
        elif args.command == "render":
            root, project = load_project(args.project)
            print(f"Master: {render(root, project, args.output, args.mix_voice, args.burn_subtitles)}")
        elif args.command == "qa":
            root, project = load_project(args.project)
            report = qa(root, project)
            write_json(root / "production" / "qa_report.json", report)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0 if report["ready"] else 2
        elif args.command == "flow-assist":
            from .flow import assist
            assist(args.prompt, args.selector, args.button, args.submit)
        elif args.command == "doctor":
            for name in ["ffmpeg", "ffprobe"]:
                print(f"{name}: {shutil.which(name) or 'MISSING'}")
            try:
                import playwright  # noqa: F401
                print("playwright: installed")
            except ImportError:
                print("playwright: optional; install .[flow] for flow-assist")
            print("LLM: optional; set VIDEO_LLM_BASE_URL / VIDEO_LLM_API_KEY / VIDEO_LLM_MODEL for draft")
        return 0
    except (StudioError, OSError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
