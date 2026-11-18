"""Checkpointed, human-approved film production workflow.

No browser action is attempted without an explicit saved credits authorization.
Once a submission is attempted, that attempt is never repeated automatically.
"""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Any

from .core import (StudioError, asset_index, digest, export, ingest, load_project,
                   qa, render, selected_asset, write_json, probe)
from .handoff import flow_pack, gemini_brief
from .llm import draft
from .templates import preset

STATE_NAME = "production/run_state.json"


def state_file(root: Path) -> Path:
    return root / STATE_NAME


def get_state(root: Path) -> dict:
    path = state_file(root)
    if not path.is_file():
        raise StudioError("This is not an automated production. Run 'video-studio start' first.")
    return json.loads(path.read_text(encoding="utf-8"))


def save_state(root: Path, state: dict) -> None:
    """Atomic file replace, preserving previous state if write fails."""
    dest = state_file(root)
    dest.parent.mkdir(parents=True, exist_ok=True)
    temp = dest.with_suffix(".tmp")
    temp.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(dest)


def event(state: dict, kind: str, **detail: Any) -> None:
    state.setdefault("events", []).append({"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                          "type": kind, **detail})


def start(root: Path, idea: str, mode: str, title: str, shots: int,
          reference_files: list[Path] | None = None, provider: str = "gemini-web",
          gemini_config: Path | None = None, gemini_browser=None) -> dict:
    """Generate a Gemini shot plan then stop at first human review gate."""
    root = root.expanduser().resolve()
    if state_file(root).exists() or (root / "project.json").exists():
        raise StudioError("Project already exists. Refusing to overwrite. Use a new project directory.")
    if shots not in range(1, 21):
        raise StudioError("--shots must be 1..20")
    references = [Path(p).expanduser().resolve() for p in (reference_files or [])]
    for image in references:
        if not image.is_file() or image.suffix.lower() not in (".jpg", ".jpeg", ".png", ".webp"):
            raise StudioError(f"Reference must be an existing JPG/PNG/WebP: {image}")
    if provider == "gemini":
        project = draft(idea, mode, title, shots, provider="gemini", images=references)
    elif provider == "gemini-web":
        # Placeholder only; storyboard is NOT approved until validated Gemini web response.
        project = preset(mode, title)
    elif provider == "template":
        project = preset(mode, title)
        if len(project["shots"]) != shots:
            raise StudioError("Template only supports preset shot count; choose 6 for handcraft or 5 for story")
    else:
        raise StudioError("provider must be gemini-web, gemini or template")
    # Do not start a browser or consume Flow credits here.
    root.mkdir(parents=True, exist_ok=True)
    write_json(root / "project.json", project)
    saved_refs = []
    for n, original in enumerate(references, 1):
        dest = root / "assets" / "references" / f"reference_{n:02d}{original.suffix.lower()}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(original, dest)
        saved_refs.append(dest.relative_to(root).as_posix())
    if provider != "gemini-web":
        export(root, project)
        flow_pack(root, project)
        gemini_brief(root, project, idea)
    state = {"schema": 2, "title": project["title"],
             "phase": "gemini_ready" if provider == "gemini-web" else "awaiting_storyboard_approval",
             "idea": idea, "provider": provider, "references": saved_refs,
             "requested_mode": mode, "requested_shots": shots, "gemini_attempts": 0,
             "approved_plan_digest": None, "credits_remaining": 0,
             "shots": {shot["id"]: {"status": "pending", "attempts": 0, "candidates": [], "approved_file": None}
                       for shot in project["shots"]}, "events": []}
    event(state, "created", provider=provider)
    save_state(root, state)
    if provider == "gemini-web":
        # One command starts the browser operation. Preflight errors leave an
        # untouched gemini_ready state; submissions become uncertain on timeout.
        return generate_gemini(root, browser=gemini_browser, config=gemini_config)
    return state


def _accept_gemini_plan(root: Path, state: dict, project: dict) -> dict:
    from .core import validate
    validate(project)
    if project["mode"] != state["requested_mode"] or len(project["shots"]) != state["requested_shots"]:
        raise StudioError("Gemini storyboard does not match requested mode or shot count")
    # Save validated JSON, then export files. A crashed handoff remains in
    # gemini_submission_uncertain; never automatically submit another prompt.
    write_json(root / "project.json", project)
    export(root, project)
    flow_pack(root, project)
    gemini_brief(root, project, state["idea"])
    state["title"] = project["title"]
    state["shots"] = {shot["id"]: {"status": "pending", "attempts": 0,
                        "candidates": [], "approved_file": None} for shot in project["shots"]}
    state["phase"] = "awaiting_storyboard_approval"
    event(state, "received_gemini_storyboard", shots=len(project["shots"]))
    save_state(root, state)
    return state


def generate_gemini(root: Path, browser=None, config: Path | None = None) -> dict:
    """One Gemini chat submission max; if response unclear never auto retry."""
    root = Path(root).expanduser().resolve()
    state = get_state(root)
    if state["provider"] != "gemini-web" or state["phase"] != "gemini_ready":
        raise StudioError("Gemini web submission not authorized in current phase")
    if browser is None:
        from .gemini_browser import GeminiBrowser
        browser = GeminiBrowser(config)
    references = [root / path for path in state["references"]]
    # All non-mutating checks happen before reserving the attempt.
    browser.preflight(references)
    state["gemini_attempts"] += 1
    state["phase"] = "gemini_submission_uncertain"
    event(state, "gemini_submission_reserved", attempt=state["gemini_attempts"])
    save_state(root, state)
    try:
        result = browser.generate_plan(state["idea"], state["requested_mode"], state["title"],
                                       state["requested_shots"], references)
        return _accept_gemini_plan(root, state, result)
    except Exception as exc:
        event(state, "gemini_error", error=f"{type(exc).__name__}: {str(exc)[:300]}")
        save_state(root, state)
        raise StudioError("Gemini web submission uncertain: inspect Gemini chat before retrying. "
                          "Use receive-gemini for a valid saved JSON, or resolve-gemini --action retry "
                          "after explicit human confirmation. " + str(exc)) from exc


def receive_gemini(root: Path, response_file: Path) -> dict:
    """Manually recover valid Gemini JSON from a visible web response."""
    root = Path(root).expanduser().resolve()
    state = get_state(root)
    if state["provider"] != "gemini-web" or state["phase"] not in ("gemini_ready", "gemini_submission_uncertain"):
        raise StudioError("Not expecting a Gemini web response")
    from .gemini_browser import extract_project
    text = Path(response_file).expanduser().resolve().read_text(encoding="utf-8")
    project = extract_project(text, state["requested_mode"], state["requested_shots"])
    return _accept_gemini_plan(root, state, project)


def resolve_gemini(root: Path, action: str) -> dict:
    root = Path(root).expanduser().resolve()
    state = get_state(root)
    if state["provider"] != "gemini-web" or state["phase"] != "gemini_submission_uncertain":
        raise StudioError("No uncertain Gemini submission to resolve")
    if action != "retry":
        raise StudioError("Only explicit retry is allowed; use receive-gemini for manual recovery")
    state["phase"] = "gemini_ready"
    event(state, "gemini_retry_authorized_by_operator")
    save_state(root, state)
    return state


def assert_plan_unchanged(root: Path, state: dict) -> None:
    if not state.get("approved_plan_digest") or digest(root / "project.json") != state["approved_plan_digest"]:
        raise StudioError("project.json changed after approval. Run 'video-studio replan' before continuing.")


def replan(root: Path) -> dict:
    """Allow editing plan before spending credits, then return to storyboard review."""
    root, project = load_project(root)
    state = get_state(root)
    if any(s["attempts"] for s in state["shots"].values()):
        raise StudioError("Cannot replan a project with Flow submissions; create a new project to preserve traceability")
    export(root, project)
    flow_pack(root, project)
    state["shots"] = {shot["id"]: {"status": "pending", "attempts": 0, "candidates": [], "approved_file": None}
                      for shot in project["shots"]}
    state["phase"] = "awaiting_storyboard_approval"
    state["approved_plan_digest"] = None
    state["credits_remaining"] = 0
    event(state, "replanned")
    save_state(root, state)
    return state


def approve(root: Path, stage: str, shot_id: str | None = None, max_generations: int | None = None) -> dict:
    root, project = load_project(root)
    state = get_state(root)
    if stage == "storyboard":
        if state["phase"] != "awaiting_storyboard_approval":
            raise StudioError("Not awaiting storyboard review")
        export(root, project)
        flow_pack(root, project)
        state["approved_plan_digest"] = digest(root / "project.json")
        state["phase"] = "awaiting_credit_approval"
        event(state, "approved_storyboard", sha256=state["approved_plan_digest"])
    elif stage == "credits":
        if state["phase"] not in ("awaiting_credit_approval", "awaiting_extra_credit_approval"):
            raise StudioError("Not awaiting a Flow credit authorization")
        assert_plan_unchanged(root, state)
        if max_generations is None or not (1 <= max_generations <= 20):
            raise StudioError("Explicit --max-generations 1..20 is required")
        state["credits_remaining"] += max_generations
        state["phase"] = "ready_to_generate"
        event(state, "approved_credits", additional_generations=max_generations)
    elif stage == "shot":
        assert_plan_unchanged(root, state)
        if not shot_id or shot_id not in state["shots"]:
            raise StudioError("Specify a valid --shot")
        item = state["shots"][shot_id]
        if state["phase"] != "awaiting_shot_approval" or item["status"] != "awaiting_review":
            raise StudioError("Shot has no downloaded candidate awaiting approval")
        if not item["candidates"]:
            raise StudioError("Cannot approve without a real imported file")
        chosen = Path(item["candidates"][-1])
        if not (root / chosen).is_file():
            raise StudioError("Imported candidate is missing from disk")
        item["approved_file"] = chosen.as_posix()
        item["status"] = "approved"
        # Rendering must use the explicitly approved version, never latest rejected clip.
        selection_file = root / "assets" / "selection.json"
        selection = json.loads(selection_file.read_text(encoding="utf-8")) if selection_file.exists() else {"shots": {}}
        selection.setdefault("shots", {})[shot_id] = chosen.as_posix()
        write_json(selection_file, selection)
        state["phase"] = "ready_to_generate"
        event(state, "approved_shot", shot=shot_id, asset=chosen.as_posix())
    elif stage == "final":
        if state["phase"] != "awaiting_final_approval":
            raise StudioError("No final video awaiting approval")
        master = state.get("master")
        if not master or not (root / master).is_file():
            raise StudioError("Final video is missing")
        state["phase"] = "completed"
        event(state, "approved_final", master=master)
    else:
        raise StudioError("stage must be storyboard, credits, shot or final")
    save_state(root, state)
    return state


def receive(root: Path, shot_id: str, media: Path) -> dict:
    root, project = load_project(root)
    state = get_state(root)
    assert_plan_unchanged(root, state)
    if state["phase"] not in ("awaiting_download", "generation_uncertain"):
        raise StudioError("No generation awaiting download. Use 'advance' or resolve its status first")
    item = state["shots"].get(shot_id)
    if not item or item["status"] not in ("awaiting_download", "submission_uncertain"):
        raise StudioError("This shot is not awaiting an external file")
    # Verify the actual media stream before allowing human approval.
    try:
        info = probe(Path(media).expanduser().resolve())
    except Exception as exc:
        raise StudioError(f"Unreadable downloaded video: {media}") from exc
    if not any(stream.get("codec_type") == "video" for stream in info.get("streams", [])):
        raise StudioError("Downloaded media has no video stream")
    dest = ingest(root, project, shot_id, media, "video")
    _record_candidate(root, state, shot_id, dest)
    return state


def _record_candidate(root: Path, state: dict, shot_id: str, dest: Path) -> None:
    item = state["shots"][shot_id]
    relative = dest.relative_to(root).as_posix()
    item["candidates"].append(relative)
    item["status"] = "awaiting_review"
    state["phase"] = "awaiting_shot_approval"
    event(state, "received_media", shot=shot_id, file=relative, sha256=digest(dest))
    _make_preview(root, shot_id, dest)
    save_state(root, state)


def _make_preview(root: Path, shot_id: str, src: Path) -> None:
    """Best-effort contact sheet; metadata QA is still not visual QA."""
    from .core import need_binary
    import subprocess
    dest = root / "production" / "review" / f"shot_{shot_id}_{src.stem}.jpg"
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run([need_binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y", "-i", str(src),
                        "-vf", "fps=1/2,scale=320:-2,tile=3x2:nb_frames=6", "-frames:v", "1", str(dest)],
                       check=True, capture_output=True, timeout=30)
    except (StudioError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        pass


def reject_shot(root: Path, shot_id: str, reason: str) -> dict:
    root, _ = load_project(root)
    state = get_state(root)
    if state["phase"] != "awaiting_shot_approval" or state["shots"].get(shot_id, {}).get("status") != "awaiting_review":
        raise StudioError("No clip is currently awaiting approval for this shot")
    item = state["shots"][shot_id]
    item["status"] = "pending"
    state["phase"] = "ready_to_generate" if state["credits_remaining"] else "awaiting_extra_credit_approval"
    event(state, "rejected_shot", shot=shot_id, reason=reason)
    save_state(root, state)
    return state


def resolve_uncertain(root: Path, shot_id: str, action: str) -> dict:
    root, _ = load_project(root)
    state = get_state(root)
    if state["phase"] != "generation_uncertain" or state["shots"].get(shot_id, {}).get("status") != "submission_uncertain":
        raise StudioError("This shot is not in uncertain state")
    if action == "download":
        state["phase"] = "awaiting_download"
        state["shots"][shot_id]["status"] = "awaiting_download"
        event(state, "manual_download_selected", shot=shot_id)
    elif action == "retry":
        # Operator must have inspected the site and explicitly decided to retry.
        state["shots"][shot_id]["status"] = "pending"
        state["phase"] = "ready_to_generate" if state["credits_remaining"] else "awaiting_extra_credit_approval"
        event(state, "manual_retry_authorized", shot=shot_id)
    else:
        raise StudioError("action must be retry or download")
    save_state(root, state)
    return state


def mark_manual_download(root: Path, shot_id: str) -> dict:
    root, _ = load_project(root)
    state = get_state(root)
    if state["phase"] != "generation_uncertain" or state["shots"].get(shot_id, {}).get("status") != "submission_uncertain":
        raise StudioError("This shot is not in uncertain state")
    state["phase"] = "awaiting_download"
    state["shots"][shot_id]["status"] = "awaiting_download"
    event(state, "manual_download_selected", shot=shot_id)
    save_state(root, state)
    return state


def advance(root: Path, browser=None, config: Path | None = None) -> dict:
    """Progress one reversible step only. Browser is injectable for tests.

    A crashed invocation leaves submission_uncertain, never auto-clicks again.
    """
    root, project = load_project(root)
    state = get_state(root)
    if state["phase"] == "gemini_ready":
        return generate_gemini(root, config=config)
    assert_plan_unchanged(root, state)
    if state["phase"] != "ready_to_generate":
        raise StudioError(f"Paused: {state['phase']}. Check status and complete the human review gate.")
    next_shot = next((s for s in project["shots"] if state["shots"][s["id"]]["status"] == "pending"), None)
    if next_shot is None:
        report = qa(root, project)
        write_json(root / "production" / "qa_report.json", report)
        if not report["ready"]:
            raise StudioError("QA failed, cannot render. Inspect production/qa_report.json")
        master = render(root, project)
        state["master"] = master.relative_to(root).as_posix()
        state["phase"] = "awaiting_final_approval"
        event(state, "rendered", master=state["master"])
        save_state(root, state)
        return state
    if state["credits_remaining"] < 1:
        state["phase"] = "awaiting_extra_credit_approval"
        save_state(root, state)
        return state
    shot_id = next_shot["id"]
    if browser is None:
        from .flow_browser import FlowBrowser
        browser = FlowBrowser(config)
    # Fail fast for non-submission errors, before reserving any potential credit.
    if hasattr(browser, "preflight"):
        browser.preflight([root / r for r in state["references"]])
    # Reserve one potential paid generation BEFORE touching the web UI.
    state["credits_remaining"] -= 1
    item = state["shots"][shot_id]
    item["attempts"] += 1
    item["status"] = "submission_uncertain"
    state["phase"] = "generation_uncertain"
    event(state, "generation_attempt_reserved", shot=shot_id, attempt=item["attempts"])
    save_state(root, state)
    try:
        output = browser.generate(root, project, next_shot, [root / r for r in state["references"]])
    except Exception as exc:
        # Do not retry automatically: web request may have consumed credits.
        event(state, "flow_error", shot=shot_id, error=f"{type(exc).__name__}: {str(exc)[:300]}")
        save_state(root, state)
        raise StudioError(f"Flow uncertain for shot {shot_id}; no automatic retry. Check browser and run 'resolve --shot {shot_id}' before import/retry. {exc}") from exc
    if output is None:
        state["phase"] = "awaiting_download"
        item["status"] = "awaiting_download"
        event(state, "needs_manual_download", shot=shot_id)
        save_state(root, state)
    else:
        try:
            info = probe(Path(output))
            if not any(stream.get("codec_type") == "video" for stream in info.get("streams", [])):
                raise StudioError("Flow download has no video stream")
        except Exception as exc:
            event(state, "invalid_flow_download", shot=shot_id, error=str(exc)[:200])
            save_state(root, state)
            raise StudioError("Flow download could not be verified; manual recovery required") from exc
        dest = ingest(root, project, shot_id, Path(output), "video")
        _record_candidate(root, state, shot_id, dest)
    return state


def summary(state: dict) -> str:
    phase = state["phase"]
    instructions = {
        "gemini_ready": "Gemini web is ready: run advance (after verifying UI config).",
        "gemini_submission_uncertain": "Inspect Gemini chat, then receive-gemini PROJECT --file JSON, or explicitly resolve-gemini --action retry. No automatic retry.",
        "awaiting_storyboard_approval": "Review production/storyboard.md, prompts, project.json; then approve --stage storyboard (or edit and replan).",
        "awaiting_credit_approval": "Verify your logged-in Flow session, model, aspect, costs and selectors, then approve --stage credits --max-generations N.",
        "ready_to_generate": "Run advance to generate one pending shot (or render if all approved).",
        "generation_uncertain": "Inspect Flow: submission may have consumed credits. Use resolve --shot ID, then receive the file. Never auto-retry.",
        "awaiting_download": "Download video in Flow and use receive --shot ID --file PATH.",
        "awaiting_shot_approval": "Watch the clip and contact sheet. Use approve --stage shot --shot ID, or reject --shot ID --reason ...",
        "awaiting_extra_credit_approval": "More paid generations require approve --stage credits --max-generations N.",
        "awaiting_final_approval": "Watch exports/final_master*.mp4, then approve --stage final.",
        "completed": "Completed. All assets and historical versions were retained.",
    }
    rows = [f"Phase: {phase}", f"Director: {state.get('provider', 'unknown')}",
            f"Credits authorized but unattempted: {state['credits_remaining']}", "Shots:"]
    rows += [f"  {sid}: {item['status']}, attempts={item['attempts']}, approved={item.get('approved_file') or '-'}"
             for sid, item in state["shots"].items()]
    rows.append("Next: " + instructions.get(phase, "Inspect run_state.json"))
    return "\n".join(rows)
