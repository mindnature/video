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
from .handoff import gemini_brief, flow_pack
from . import production
from .templates import preset


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="video-studio", description="Local-first AI film production orchestrator")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="create an editable shot project")
    init.add_argument("name", help="directory to create")
    init.add_argument("--preset", choices=["handcraft", "story", "general"], default="handcraft")
    init.add_argument("--title", default="未命名作品")
    init.add_argument("--force", action="store_true", help="overwrite project.json ONLY")
    planning = sub.add_parser("plan", help="export shot prompts, storyboard, CSV voice lines and SRT")
    planning.add_argument("project", help="project directory or project.json")
    d = sub.add_parser("draft", help="optional LLM-assisted idea-to-shot JSON")
    d.add_argument("name", help="new project directory")
    d.add_argument("--idea", required=True)
    d.add_argument("--preset", choices=["handcraft", "story", "general"], default="handcraft")
    d.add_argument("--title", default="未命名作品")
    d.add_argument("--shots", type=int)
    d.add_argument("--provider", choices=["compatible", "gemini"], default="compatible", help="Gemini API or OpenAI-compatible API")
    g = sub.add_parser("gemini-brief", help="export a paste-ready Gemini director prompt (no API key)")
    g.add_argument("project")
    g.add_argument("--idea", required=True)
    pack = sub.add_parser("flow-pack", help="export a Flow Agent instruction pack and individual shot queue")
    pack.add_argument("project")
    incoming = sub.add_parser("ingest", help="version and hash an existing video/voice asset")
    incoming.add_argument("project")
    incoming.add_argument("--shot", required=True)
    incoming.add_argument("--file", required=True, type=Path)
    incoming.add_argument("--kind", choices=["video", "voice"], default="video")
    incoming.add_argument("--line", help="dialogue ID (e.g. 01_01) when --kind voice")
    making = sub.add_parser("render", help="normalize clips, concatenate, optionally mix voice and burn subtitles")
    making.add_argument("project")
    making.add_argument("--output", type=Path)
    making.add_argument("--mix-voice", action="store_const", const=True, default=None, help="force voice mixing instead of project auto setting")
    making.add_argument("--no-voice", action="store_const", dest="mix_voice", const=False)
    making.add_argument("--burn-subtitles", action="store_const", const=True, default=None)
    making.add_argument("--no-subtitles", action="store_const", dest="burn_subtitles", const=False)
    review = sub.add_parser("qa", help="metadata checks and missing-asset report")
    review.add_argument("project")
    flow = sub.add_parser("flow-assist", help="populate Google Flow prompt in one open user Chrome tab")
    flow.add_argument("prompt", type=Path)
    flow.add_argument("--selector", help="verified CSS textbox selector")
    flow.add_argument("--button", help="verified CSS submit button selector")
    flow.add_argument("--submit", action="store_true", help="explicitly click generation after filling")
    a = sub.add_parser("start", help="one command: idea + reference images -> Gemini storyboard -> review gate")
    a.add_argument("name", help="new project directory")
    a.add_argument("--idea", required=True)
    a.add_argument("--reference", type=Path, action="append", default=[], help="reference image; repeat as needed")
    a.add_argument("--preset", choices=["handcraft", "story", "general"], default="handcraft")
    a.add_argument("--title", default="未命名作品")
    a.add_argument("--shots", type=int, default=0)
    a.add_argument("--provider", choices=["gemini-web", "gemini", "template"], default="gemini-web",
                   help="Chrome Gemini by default; API and template optional")
    a.add_argument("--gemini-config", type=Path, help="local verified Gemini web CSS selectors")
    a.add_argument("--quick-storyboard", action="store_true", help="legacy single Gemini plan; skip script-first review (not recommended)")
    a.add_argument("--delivery", choices=["flow_dynamic", "animatic", "mixed_media"], default="flow_dynamic",
                   help="declared deliverable: formal Flow performance vs labeled preview")
    status = sub.add_parser("status", help="show saved workflow and exact next action")
    status.add_argument("project")
    app = sub.add_parser("approve", help="human review gates: story, storyboard, credits, shot, final")
    app.add_argument("project")
    app.add_argument("--stage", choices=["story", "storyboard", "credits", "shot", "final"], required=True)
    app.add_argument("--shot")
    app.add_argument("--max-generations", type=int)
    adv = sub.add_parser("advance", help="run one Flow generation or produce final render; resumable")
    adv.add_argument("project")
    adv.add_argument("--flow-config", type=Path, help="local verified Playwright CSS selectors JSON")
    adv.add_argument("--gemini-config", type=Path, help="local verified Gemini UI selectors JSON for pending Gemini plan")
    recv = sub.add_parser("receive", help="import browser-downloaded clip and pause for human review")
    recv.add_argument("project")
    recv.add_argument("--shot", required=True)
    recv.add_argument("--file", required=True, type=Path)
    recv.add_argument("--from-flow", action="store_true", help="operator attests this downloaded asset came from visible Google Flow")
    verify = sub.add_parser("verify-shot", help="record human visual end-state/style/audio review before approval")
    verify.add_argument("project")
    verify.add_argument("--shot", required=True)
    verify.add_argument("--result", choices=["pass", "fail"], required=True)
    verify.add_argument("--note", required=True)
    verify.add_argument("--motion", choices=["pass", "fail", "not_applicable"],
                        help="explicitly attest visible on-screen subject movement, not a Ken Burns still")
    verify.add_argument("--identity", choices=["pass", "fail", "not_applicable"],
                        help="human comparison of recurring character identity/age/wardrobe with approved shots")
    seam = sub.add_parser("verify-seam", help="human approval of an actual adjacent-shot edit preview")
    seam.add_argument("project")
    seam.add_argument("--left", required=True)
    seam.add_argument("--right", required=True)
    seam.add_argument("--result", choices=["pass", "fail"], required=True)
    seam.add_argument("--note", required=True)
    rej = sub.add_parser("reject", help="reject a candidate, keep original, require authorized retry")
    rej.add_argument("project")
    rej.add_argument("--shot", required=True)
    rej.add_argument("--reason", required=True)
    resol = sub.add_parser("resolve", help="recover ambiguous Flow submission without automatic retry")
    resol.add_argument("project")
    resol.add_argument("--shot", required=True)
    resol.add_argument("--action", choices=["download", "retry"], default="download")
    repl = sub.add_parser("replan", help="revalidate edited project.json before first Flow submission")
    repl.add_argument("project")
    inspect = sub.add_parser("inspect-flow", help="save local screenshot and CSS selector counts for Flow UI")
    inspect.add_argument("project")
    inspect.add_argument("--flow-config", type=Path)
    gem_inspect = sub.add_parser("inspect-gemini", help="Gemini visible UI screenshot and selector counts")
    gem_inspect.add_argument("project")
    gem_inspect.add_argument("--gemini-config", type=Path)
    critic = sub.add_parser("director-review", help="independent Gemini screenplay/storyboard/continuity critic before Flow")
    critic.add_argument("project")
    critic.add_argument("--gemini-config", type=Path)
    critic_recv = sub.add_parser("receive-director-review", help="recover checked director review JSON from Gemini")
    critic_recv.add_argument("project")
    critic_recv.add_argument("--file", type=Path, required=True)
    critic_retry = sub.add_parser("resolve-director-review", help="explicitly retry an uncertain reviewer turn")
    critic_retry.add_argument("project")
    critic_retry.add_argument("--action", choices=["retry"], required=True)
    over = sub.add_parser("director-override", help="operator resolves contradictory director reviews with reason")
    over.add_argument("project")
    over.add_argument("--reason", required=True)
    guide = sub.add_parser("voice-guide", help="write contrasting warm/somber narration audition guide")
    guide.add_argument("project")
    audition = sub.add_parser("voice-audition", help="register two real audio auditions before approving narration voice")
    audition.add_argument("project")
    audition.add_argument("--warm", type=Path, required=True)
    audition.add_argument("--somber", type=Path, required=True)
    audition.add_argument("--source", required=True)
    voice_pass = sub.add_parser("voice-approve", help="operator signoff on audition naturalness")
    voice_pass.add_argument("project")
    voice_pass.add_argument("--note", required=True)
    report = sub.add_parser("delivery-report", help="reconcile source evidence, allowed Flow attempts, voice and dynamic movement")
    report.add_argument("project")
    gem_receive = sub.add_parser("receive-gemini", help="recover checked storyboard JSON from Gemini web response")
    gem_receive.add_argument("project")
    gem_receive.add_argument("--file", type=Path, required=True)
    gem_resolve = sub.add_parser("resolve-gemini", help="operator authorizes retry after inspecting uncertain Gemini chat")
    gem_resolve.add_argument("project")
    gem_resolve.add_argument("--action", choices=["retry"], required=True)
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
            result = draft(args.idea, args.preset, args.title, args.shots, provider=args.provider)
            write_json(root / "project.json", result)
            print(f"Draft created: {root / 'project.json'}; review each shot before plan/render")
        elif args.command == "gemini-brief":
            root, project = load_project(args.project)
            print(f"Gemini brief: {gemini_brief(root, project, args.idea)}")
        elif args.command == "flow-pack":
            root, project = load_project(args.project)
            handoff, manifest = flow_pack(root, project)
            print(f"Flow Agent handoff: {handoff}\nQueue manifest: {manifest}")
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
        elif args.command == "start":
            count = args.shots or (6 if args.preset == "handcraft" else 4 if args.preset == "general" else 5)
            state = production.start(Path(args.name), args.idea, args.preset, args.title, count,
                                     args.reference, args.provider, gemini_config=args.gemini_config,
                                     director_first=not args.quick_storyboard, delivery_mode=args.delivery)
            print(production.summary(state))
        elif args.command == "status":
            print(production.summary(production.get_state(Path(args.project).resolve())))
        elif args.command == "approve":
            state = production.approve(Path(args.project), args.stage, args.shot, args.max_generations)
            print(production.summary(state))
        elif args.command == "advance":
            # Pass the config so the browser can adapt to the user's actual Flow UI.
            state = production.advance(Path(args.project), config=args.gemini_config or args.flow_config)
            print(production.summary(state))
        elif args.command == "receive":
            state = production.receive(Path(args.project), args.shot, args.file, from_flow=args.from_flow)
            print(production.summary(state))
        elif args.command == "verify-shot":
            state = production.verify_shot(Path(args.project), args.shot, args.result, args.note, args.motion, args.identity)
            print(production.summary(state))
        elif args.command == "verify-seam":
            state = production.verify_seam(Path(args.project), args.left, args.right, args.result, args.note)
            print(production.summary(state))
        elif args.command == "reject":
            state = production.reject_shot(Path(args.project), args.shot, args.reason)
            print(production.summary(state))
        elif args.command == "resolve":
            state = production.resolve_uncertain(Path(args.project), args.shot, args.action)
            print(production.summary(state))
        elif args.command == "replan":
            state = production.replan(Path(args.project))
            print(production.summary(state))
        elif args.command == "inspect-flow":
            from .flow_browser import FlowBrowser
            output = FlowBrowser(args.flow_config).inspect(Path(args.project).resolve())
            print(f"Flow UI probe saved locally: {output}")
        elif args.command == "inspect-gemini":
            from .gemini_browser import GeminiBrowser
            output = GeminiBrowser(args.gemini_config).inspect(Path(args.project).resolve())
            print(f"Gemini UI probe saved locally: {output}")
        elif args.command == "director-review":
            state = production.director_review(Path(args.project), config=args.gemini_config)
            print(production.summary(state))
        elif args.command == "receive-director-review":
            state = production.receive_director_review(Path(args.project), args.file)
            print(production.summary(state))
        elif args.command == "resolve-director-review":
            state = production.resolve_director_review(Path(args.project), args.action)
            print(production.summary(state))
        elif args.command == "director-override":
            print(production.summary(production.director_override(Path(args.project), args.reason)))
        elif args.command == "voice-guide":
            from .delivery import voice_guide
            root, project = load_project(args.project)
            print(f"Voice audition script: {voice_guide(root, project)}")
        elif args.command == "voice-audition":
            from .delivery import register_voice_audition
            root, project = load_project(args.project)
            print(json.dumps(register_voice_audition(root, args.warm, args.somber, args.source), ensure_ascii=False, indent=2))
        elif args.command == "voice-approve":
            from .delivery import approve_voice
            root, project = load_project(args.project)
            print(json.dumps(approve_voice(root, args.note), ensure_ascii=False, indent=2))
        elif args.command == "delivery-report":
            from .delivery import save_delivery_report
            root, project = load_project(args.project)
            print(json.dumps(save_delivery_report(root, project, production.get_state(root)), ensure_ascii=False, indent=2))
        elif args.command == "receive-gemini":
            state = production.receive_gemini(Path(args.project), args.file)
            print(production.summary(state))
        elif args.command == "resolve-gemini":
            state = production.resolve_gemini(Path(args.project), args.action)
            print(production.summary(state))
        elif args.command == "doctor":
            for name in ["ffmpeg", "ffprobe"]:
                print(f"{name}: {shutil.which(name) or 'MISSING'}")
            try:
                import playwright  # noqa: F401
                print("playwright: installed")
            except ImportError:
                print("playwright: optional; install .[flow] for flow-assist")
            print("Gemini: default Chrome web login, no API key; configure local UI selectors. Gemini API is an optional fallback.")
        return 0
    except (StudioError, OSError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
