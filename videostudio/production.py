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
          gemini_config: Path | None = None, gemini_browser=None,
          director_first: bool = False, delivery_mode: str | None = None) -> dict:
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
            raise StudioError("Template only supports its preset shot count; choose 6 handcraft, 5 story, or 4 general")
    else:
        raise StudioError("provider must be gemini-web, gemini or template")
    if delivery_mode is not None:
        if delivery_mode not in ("flow_dynamic", "animatic", "mixed_media"):
            raise StudioError("Invalid requested delivery mode")
        project["delivery"] = {"kind": delivery_mode, "require_performance_review": delivery_mode == "flow_dynamic",
                               "voice_review_required": False}
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
             "phase": ("gemini_story_ready" if director_first else "gemini_ready") if provider == "gemini-web" else "awaiting_storyboard_approval",
             "director_first": bool(director_first and provider == "gemini-web"),
             "director_review_rounds": 0, "requested_delivery": delivery_mode,
             "approved_story_digest": None, "director_review_digest": None, "director_review_pass": False,
             "gemini_step": "story" if director_first and provider == "gemini-web" else "plan",
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
    if state.get("director_first"):
        from .narrative import continuity_audit
        story_path = root / "production" / "story_bible.json"
        if (not story_path.is_file() or
                digest(story_path) != state.get("approved_story_digest") or
                project.get("story_bible") != json.loads(story_path.read_text(encoding="utf-8")) or
                not project.get("continuity_required")):
            raise StudioError("Storyboard must preserve approved story bible and enable strict continuity")
        audit = continuity_audit(project)
        if not audit["ready"]:
            raise StudioError(f"Storyboard has {audit['errors']} blocking continuity issues")
    if state.get("requested_delivery"):
        requested = state["requested_delivery"]
        spec = dict(project.get("delivery", {}))
        spec["kind"] = requested  # User-selected deliverable cannot be weakened by Gemini.
        spec["require_performance_review"] = requested == "flow_dynamic"
        narrator = any(str(line.get("speaker", "")).lower() in ("旁白", "narrator", "voiceover", "解说")
                       for shot in project["shots"] for line in shot.get("dialogue", []))
        spec["voice_review_required"] = bool(spec.get("voice_review_required", False) or narrator)
        project["delivery"] = spec
        if narrator:
            project.setdefault("postproduction", {})["voice"] = "on"
        from .delivery import validate_policy
        validate_policy(project)
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
    state["director_review_digest"] = None
    state["director_review_pass"] = False
    event(state, "received_gemini_storyboard", shots=len(project["shots"]))
    save_state(root, state)
    return state


def _accept_gemini_story(root: Path, state: dict, story: dict) -> dict:
    from .narrative import validate_story
    validate_story(story)
    path = root / "production" / "story_bible.json"
    write_json(path, story)
    # Deliberately not a storyboard: no Flow prompt is emitted until the
    # user approves the screenplay and Gemini generates stage 2.
    state["phase"] = "awaiting_story_approval"
    state["approved_story_digest"] = None
    event(state, "received_story_bible", beats=len(story["beats"]))
    save_state(root, state)
    return state


def generate_gemini(root: Path, browser=None, config: Path | None = None) -> dict:
    """One non-retried website turn per stage, with distinct story and plan gates."""
    root = Path(root).expanduser().resolve()
    state = get_state(root)
    phase = state["phase"]
    allowed = ("gemini_story_ready", "gemini_plan_ready", "gemini_ready")
    if state["provider"] != "gemini-web" or phase not in allowed:
        raise StudioError("Gemini web submission not authorized in current phase")
    if browser is None:
        from .gemini_browser import GeminiBrowser
        browser = GeminiBrowser(config)
    references = [root / path for path in state["references"]]
    browser.preflight(references)
    step = "story" if phase == "gemini_story_ready" else "plan"
    state["gemini_step"] = step
    state["gemini_attempts"] += 1
    state["phase"] = "gemini_submission_uncertain"
    event(state, "gemini_submission_reserved", step=step, attempt=state["gemini_attempts"])
    save_state(root, state)
    try:
        if step == "story":
            result = browser.generate_story(state["idea"], state["requested_mode"], state["title"],
                                            state["requested_shots"], references)
            return _accept_gemini_story(root, state, result)
        if state.get("director_first"):
            story_file = root / "production" / "story_bible.json"
            if digest(story_file) != state.get("approved_story_digest"):
                raise StudioError("Approved story changed; return to story review")
            story = json.loads(story_file.read_text(encoding="utf-8"))
            result = browser.generate_plan_from_story(state["idea"], state["requested_mode"], state["title"],
                                                      state["requested_shots"], references, story)
        else:
            result = browser.generate_plan(state["idea"], state["requested_mode"], state["title"],
                                           state["requested_shots"], references)
        return _accept_gemini_plan(root, state, result)
    except Exception as exc:
        event(state, "gemini_error", step=step, error=f"{type(exc).__name__}: {str(exc)[:300]}")
        save_state(root, state)
        raise StudioError(f"Gemini {step} submission uncertain: inspect visible chat before retrying. "
                          "Use receive-gemini for a saved JSON, or resolve-gemini --action retry "
                          "after explicit operator confirmation. " + str(exc)) from exc


def receive_gemini(root: Path, response_file: Path) -> dict:
    """Recover only the expected type of JSON for the current Gemini stage."""
    root = Path(root).expanduser().resolve()
    state = get_state(root)
    if state["provider"] != "gemini-web" or state["phase"] not in (
            "gemini_ready", "gemini_story_ready", "gemini_plan_ready", "gemini_submission_uncertain"):
        raise StudioError("Not expecting a Gemini web response")
    content = Path(response_file).expanduser().resolve().read_text(encoding="utf-8")
    if state.get("gemini_step") == "story":
        from .narrative import parse_story_response
        return _accept_gemini_story(root, state, parse_story_response(content))
    from .gemini_browser import extract_project
    return _accept_gemini_plan(root, state, extract_project(content, state["requested_mode"], state["requested_shots"]))


def resolve_gemini(root: Path, action: str) -> dict:
    root = Path(root).expanduser().resolve()
    state = get_state(root)
    if state["provider"] != "gemini-web" or state["phase"] != "gemini_submission_uncertain":
        raise StudioError("No uncertain Gemini submission to resolve")
    if action != "retry":
        raise StudioError("Only explicit retry is allowed; use receive-gemini for manual recovery")
    state["phase"] = ("gemini_story_ready" if state.get("gemini_step") == "story" else
                      "gemini_plan_ready" if state.get("director_first") else "gemini_ready")
    event(state, "gemini_retry_authorized_by_operator", step=state.get("gemini_step"))
    save_state(root, state)
    return state



def _accept_director_review(root: Path, state: dict, review: dict) -> dict:
    from .narrative import parse_director_review
    checked = parse_director_review(json.dumps(review, ensure_ascii=False))
    write_json(root / "production" / "director_review.json", checked)
    state["phase"] = "awaiting_storyboard_approval"
    state["director_review_digest"] = digest(root / "project.json")
    state["director_review_pass"] = checked["pass"]
    event(state, "director_review_received", passed=checked["pass"], problems=len(checked["hard_problems"]))
    save_state(root, state)
    return state


def director_review(root: Path, browser=None, config: Path | None = None) -> dict:
    """Third Gemini turn: independent critic, with explicit retry rules."""
    root, project = load_project(root)
    state = get_state(root)
    if not state.get("director_first") or state["phase"] != "awaiting_storyboard_approval":
        raise StudioError("Director review is only available at the storyboard gate of a two-stage project")
    if state.get("director_review_rounds", 0) >= 2:
        raise StudioError("Director review capped at two rounds. Fix concrete issues or use director-override with human reasoning; avoid endless contradictions")
    from .quality import audit_plan
    check = audit_plan(project)
    if not check["ready"]:
        raise StudioError(f"Resolve {check['errors']} structural errors before submitting director review")
    if browser is None:
        from .gemini_browser import GeminiBrowser
        browser = GeminiBrowser(config)
    browser.preflight([])
    state["phase"] = "director_review_uncertain"
    state["director_review_rounds"] = state.get("director_review_rounds", 0) + 1
    event(state, "director_review_submitted", round=state["director_review_rounds"])
    save_state(root, state)
    try:
        result = browser.review_plan(project)
        return _accept_director_review(root, state, result)
    except Exception as exc:
        event(state, "director_review_error", error=f"{type(exc).__name__}: {str(exc)[:220]}")
        save_state(root, state)
        raise StudioError("Director review submission uncertain; inspect Gemini chat before manually importing the review. " + str(exc)) from exc


def receive_director_review(root: Path, response_file: Path) -> dict:
    root, project = load_project(root)
    state = get_state(root)
    if not state.get("director_first") or state["phase"] not in ("director_review_uncertain", "awaiting_storyboard_approval"):
        raise StudioError("Not accepting a director review in current phase")
    from .narrative import parse_director_review
    doc = parse_director_review(Path(response_file).expanduser().resolve().read_text(encoding="utf-8"))
    return _accept_director_review(root, state, doc)


def resolve_director_review(root: Path, action: str) -> dict:
    root = Path(root).expanduser().resolve()
    state = get_state(root)
    if state["phase"] != "director_review_uncertain" or action != "retry":
        raise StudioError("Only an explicitly approved retry can resolve an uncertain director review")
    state["phase"] = "awaiting_storyboard_approval"
    event(state, "director_review_retry_authorized")
    save_state(root, state)
    return state


def director_override(root: Path, note: str) -> dict:
    """Human director can resolve model-review stalemates; record explicit responsibility."""
    root, project = load_project(root)
    state = get_state(root)
    if not state.get("director_first") or state["phase"] != "awaiting_storyboard_approval":
        raise StudioError("No director decision awaiting override")
    if state.get("director_review_rounds", 0) < 1 or not (root / "production/director_review.json").is_file():
        raise StudioError("At least one complete director review is required")
    if len(note.strip()) < 12:
        raise StudioError("Explain the creative decision in at least 12 characters")
    from .quality import audit_plan
    if not audit_plan(project)["ready"]:
        raise StudioError("Cannot override structural plan errors")
    state["director_review_pass"] = True
    state["director_review_digest"] = digest(root / "project.json")
    state["director_override_note"] = note.strip()
    event(state, "human_director_decision", reason=note.strip())
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
    from .quality import audit_plan
    check = audit_plan(project)
    if not check["ready"]:
        raise StudioError(f"Plan has {check['errors']} blocking conflict(s); inspect production/plan_audit.json")
    state["shots"] = {shot["id"]: {"status": "pending", "attempts": 0, "candidates": [], "approved_file": None}
                      for shot in project["shots"]}
    state["phase"] = "awaiting_storyboard_approval"
    state["director_review_digest"] = None
    state["director_review_pass"] = False
    state["approved_plan_digest"] = None
    state["credits_remaining"] = 0
    event(state, "replanned")
    save_state(root, state)
    return state


def approve(root: Path, stage: str, shot_id: str | None = None, max_generations: int | None = None) -> dict:
    root, project = load_project(root)
    state = get_state(root)
    if stage == "story":
        if not state.get("director_first") or state["phase"] != "awaiting_story_approval":
            raise StudioError("Not awaiting the story bible approval")
        story_file = root / "production" / "story_bible.json"
        from .narrative import validate_story
        validate_story(json.loads(story_file.read_text(encoding="utf-8")))
        state["approved_story_digest"] = digest(story_file)
        state["gemini_step"] = "plan"
        state["phase"] = "gemini_plan_ready"
        event(state, "approved_story", sha256=state["approved_story_digest"])
    elif stage == "storyboard":
        if state["phase"] != "awaiting_storyboard_approval":
            raise StudioError("Not awaiting storyboard review")
        if state.get("director_first"):
            story_file = root / "production" / "story_bible.json"
            if digest(story_file) != state.get("approved_story_digest") or project.get("story_bible") != json.loads(story_file.read_text(encoding="utf-8")):
                raise StudioError("Approved story must match project.story_bible before storyboard approval")
        if state.get("director_first"):
            if (not state.get("director_review_pass") or
                    state.get("director_review_digest") != digest(root / "project.json")):
                raise StudioError("Run an independent Gemini director-review and resolve hard problems before storyboard approval")
        export(root, project)
        flow_pack(root, project)
        from .quality import audit_plan
        check = audit_plan(project)
        if not check["ready"]:
            raise StudioError(f"Plan has {check['errors']} blocking conflict(s); inspect production/plan_audit.json")
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
        selected_shot = next(s for s in project["shots"] if s["id"] == shot_id)
        if project.get("delivery", {}).get("kind") == "flow_dynamic":
            from .delivery import delivery_audit
            evidence = item.get("candidate_evidence", {}).get(item["candidates"][-1], {})
            if evidence.get("origin") not in ("flow_browser", "operator_attested_flow"):
                raise StudioError("Formal Flow dynamic video requires recorded Flow source evidence; use receive --from-flow for an operator-confirmed download")
            if item.get("human_verification", {}).get("motion") != "pass":
                raise StudioError("Human dynamic performance verification required; run verify-shot --motion pass after watching real movement")
            characters = [name for name in selected_shot.get("cast", [])
                          if sum(name in other.get("cast", []) for other in project["shots"]) > 1]
            if characters and item.get("human_verification", {}).get("identity") != "pass":
                raise StudioError("Recurring character identity/age/wardrobe needs human comparison; verify-shot --identity pass")
        requires_check = bool(selected_shot.get("acceptance")) or project.get("postproduction", {}).get("style", "clean") != "clean"
        if requires_check and item.get("human_verification", {}).get("result") != "pass":
            raise StudioError("Run 'verify-shot --shot ID --result pass --note ...' after watching the entire candidate and its end frame")
        if project.get("postproduction", {}).get("style", "clean") != "clean" and not item.get("review_clip"):
            raise StudioError("Styled review clip was not rendered; fix postproduction before approving")
        if project.get("continuity_required"):
            order = [x["id"] for x in project["shots"]]
            idx = order.index(shot_id)
            if idx > 0:
                verified = item.get("seam_verification", {})
                if (not item.get("seam_review") or not (root / item["seam_review"]).is_file()
                        or verified.get("result") != "pass"
                        or verified.get("candidate") != item["candidates"][-1]
                        or verified.get("previous") != order[idx - 1]):
                    raise StudioError("Review actual adjacent-shot join, then verify-seam --left XX --right YY --result pass")
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
        from .delivery import save_delivery_report
        report = save_delivery_report(root, project, state)
        if not report["ready"]:
            raise StudioError("Final delivery contract not satisfied; inspect production/delivery_report.json")
        state["phase"] = "completed"
        event(state, "approved_final", master=master)
    else:
        raise StudioError("stage must be story, storyboard, credits, shot or final")
    save_state(root, state)
    return state


def receive(root: Path, shot_id: str, media: Path, from_flow: bool = False) -> dict:
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
    _record_candidate(root, state, shot_id, dest,
                      origin="operator_attested_flow" if from_flow else "other",
                      attestation="Operator confirmed download from visible Flow UI" if from_flow else "")
    return state


def _record_candidate(root: Path, state: dict, shot_id: str, dest: Path,
                      origin: str = "other", attestation: str = "") -> None:
    item = state["shots"][shot_id]
    relative = dest.relative_to(root).as_posix()
    from .delivery import register_candidate
    register_candidate(root, state, shot_id, dest, origin, attestation=attestation)
    item["candidates"].append(relative)
    item["status"] = "awaiting_review"
    state["phase"] = "awaiting_shot_approval"
    event(state, "received_media", shot=shot_id, file=relative, sha256=digest(dest))
    try:
        item["review_clip"] = _make_preview(root, shot_id, dest)
        item.pop("review_error", None)
    except Exception as exc:
        item["review_clip"] = None
        item["review_error"] = f"{type(exc).__name__}: {str(exc)[:220]}"
        event(state, "preview_failed", shot=shot_id, error=item["review_error"])
    # A replacement candidate invalidates prior seam approvals and previews.
    item.pop("human_verification", None)
    item.pop("seam_verification", None)
    item.pop("seam_review", None)
    if root.joinpath("project.json").is_file():
        try:
            item["seam_review"] = make_seam_review(root, state, shot_id)
        except Exception as exc:
            item["seam_error"] = f"{type(exc).__name__}: {str(exc)[:240]}"
            event(state, "seam_preview_failed", shot=shot_id, error=item["seam_error"])
    save_state(root, state)


def _make_preview(root: Path, shot_id: str, src: Path) -> str | None:
    """Render the actual postproduced shot for review, including a near-final frame.

    A still sampler cannot prove whether a person left the scene or whether lips
    were synchronized. The operator must watch the entire review clip.
    """
    from .core import need_binary
    import subprocess
    root, project = load_project(root)
    dest = root / "production" / "review"
    dest.mkdir(parents=True, exist_ok=True)
    from .core import probe
    info = probe(src)
    duration = float(info.get("format", {}).get("duration", 0))
    if duration <= 0:
        # A mock/malformed test source cannot generate a real review clip.
        return None
    preview = dest / f"shot_{shot_id}_{src.stem}_review.mp4"
    output = render(root, project, preview, shot_ids=[shot_id])
    for tag, when in (("first", 0), ("middle", max(0, duration * .5)),
                      ("end", max(0, min(duration, next(s["duration"] for s in project["shots"] if s["id"] == shot_id)) - 0.15))):
        image = dest / f"shot_{shot_id}_{src.stem}_{tag}.jpg"
        subprocess.run([need_binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y",
                        "-ss", f"{when:.3f}", "-i", str(output), "-frames:v", "1", str(image)],
                       check=True, capture_output=True, timeout=30)
    return output.relative_to(root).as_posix()



def make_seam_review(root: Path, state: dict, right_id: str) -> str | None:
    """Render the actual approved-left + candidate-right join (not a mock image).

    A 3–5 s seam excerpt is also emitted so humans can inspect the action,
    gaze and audio bridge in context, not only an isolated still.
    """
    root, project = load_project(root)
    order = [shot["id"] for shot in project["shots"]]
    position = order.index(right_id)
    if position == 0:
        return None
    left_id = order[position - 1]
    left_state = state["shots"][left_id]
    if left_state["status"] != "approved" or not left_state.get("approved_file"):
        return None
    dest = root / "production" / "review" / "seams"
    dest.mkdir(parents=True, exist_ok=True)
    candidate = Path(state["shots"][right_id]["candidates"][-1])
    label = candidate.stem
    pair = dest / f"pair_{left_id}_{right_id}_{label}.mp4"
    render(root, project, pair, shot_ids=[left_id, right_id])
    from .core import need_binary
    from .narrative import edit_duration, transition_duration
    import subprocess
    left = project["shots"][position - 1]
    right = project["shots"][position]
    cut_point = edit_duration(left) - transition_duration(right)
    source_start = max(0.0, cut_point - 2.0)
    target = dest / f"seam_{left_id}_{right_id}_{label}.mp4"
    subprocess.run([need_binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y",
                    "-ss", f"{source_start:.3f}", "-i", str(pair), "-t", "4.0",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
                    "-c:a", "aac", "-movflags", "+faststart", str(target)],
                   check=True, capture_output=True, timeout=180)
    return target.relative_to(root).as_posix()


def verify_seam(root: Path, left_id: str, right_id: str, result: str, note: str) -> dict:
    """Human checks one actual adjacent edit; no automatic visual claims."""
    root, project = load_project(root)
    state = get_state(root)
    ids = [shot["id"] for shot in project["shots"]]
    if left_id not in ids or right_id not in ids or ids.index(right_id) != ids.index(left_id) + 1:
        raise StudioError("Seam verification requires adjacent ordered shot IDs")
    item = state["shots"][right_id]
    if state["phase"] != "awaiting_shot_approval" or item["status"] != "awaiting_review":
        raise StudioError("No pending right-shot candidate for seam review")
    if state["shots"][left_id]["status"] != "approved":
        raise StudioError("Previous shot must be approved before seam verification")
    if result not in ("pass", "fail") or not note.strip():
        raise StudioError("Provide human --result pass/fail and nonempty --note")
    if not item.get("seam_review") or not (root / item["seam_review"]).is_file():
        raise StudioError("No actual seam clip was rendered; inspect seam_error and repair before approval")
    record = {"left": left_id, "right": right_id, "result": result, "note": note,
              "candidate": item["candidates"][-1], "previous": left_id,
              "seam_clip": item["seam_review"], "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
              "limitations": "The operator confirmed an actual video; code did not semantically inspect pixels"}
    item["seam_verification"] = record
    write_json(root / "production" / "review" / f"seam_{left_id}_{right_id}_human.json", record)
    event(state, "seam_verified", left=left_id, right=right_id, result=result)
    save_state(root, state)
    return state


def prepare_continuity_reference(root: Path, project: dict, state: dict, shot_id: str) -> list[Path]:
    """Optionally extract previous *approved source* frame for next Flow shot.

    Requires shot.continuity.reference_previous_end=True. Never silently
    transmits a previous shot frame if the director didn't opt in.
    """
    order = [shot["id"] for shot in project["shots"]]
    i = order.index(shot_id)
    if i == 0:
        return []
    shot = project["shots"][i]
    if not shot.get("continuity", {}).get("reference_previous_end", False):
        return []
    previous = state["shots"][order[i-1]]
    if previous["status"] != "approved" or not previous.get("approved_file"):
        raise StudioError("Previous shot has not been approved; cannot create continuity reference")
    from .core import need_binary
    from .narrative import edit_range
    import subprocess
    origin = root / previous["approved_file"]
    at = max(0.0, edit_range(project["shots"][i-1])[1] - 0.08)
    destination = root / "production" / "continuity" / f"entry_ref_{shot_id}.png"
    destination.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([need_binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{at:.3f}",
                    "-i", str(origin), "-frames:v", "1", str(destination)],
                   check=True, capture_output=True, timeout=60)
    if not destination.is_file() or destination.stat().st_size < 100:
        raise StudioError("Reference extraction failed: check previous clip and trim point")
    return [destination]


def verify_shot(root: Path, shot_id: str, result: str, note: str, motion: str | None = None, identity: str | None = None) -> dict:
    """Record a real human's assessment of visible video, not an AI guess."""
    root, project = load_project(root)
    state = get_state(root)
    if state["phase"] != "awaiting_shot_approval" or state["shots"].get(shot_id, {}).get("status") != "awaiting_review":
        raise StudioError("No candidate awaiting shot verification")
    if result not in ("pass", "fail") or not note.strip():
        raise StudioError("Specify --result pass/fail and a human-reviewed --note")
    item = state["shots"][shot_id]
    if motion not in (None, "pass", "fail", "not_applicable"):
        raise StudioError("motion must be pass/fail/not_applicable")
    if identity not in (None, "pass", "fail", "not_applicable"):
        raise StudioError("identity must be pass/fail/not_applicable")
    if result == "pass" and (motion == "fail" or identity == "fail"):
        raise StudioError("Cannot mark shot pass while motion or character identity fails")
    item["human_verification"] = {"result": result, "motion": motion, "identity": identity, "note": note, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    from .quality import acceptance_checks
    candidate = item["candidates"][-1]
    shot = next(s for s in project["shots"] if s["id"] == shot_id)
    write_json(root / "production" / "review" / f"shot_{shot_id}_human_review.json", {
        "shot": shot_id, "candidate": candidate, "review_clip": item.get("review_clip"),
        "review_error": item.get("review_error"), "review": item["human_verification"],
        "checklist": acceptance_checks(shot), "limitations": "Human signoff, not automated visual verification"})
    event(state, "human_verified_shot", shot=shot_id, result=result, note=note[:300])
    save_state(root, state)
    return state


def reject_shot(root: Path, shot_id: str, reason: str) -> dict:
    root, _ = load_project(root)
    state = get_state(root)
    if state["phase"] != "awaiting_shot_approval" or state["shots"].get(shot_id, {}).get("status") != "awaiting_review":
        raise StudioError("No clip is currently awaiting approval for this shot")
    item = state["shots"][shot_id]
    item["status"] = "pending"
    item.pop("human_verification", None)
    item.pop("seam_verification", None)
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
    if state["phase"] in ("gemini_ready", "gemini_story_ready", "gemini_plan_ready"):
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
        from .delivery import save_delivery_report
        deliverable = save_delivery_report(root, project, state)
        if not deliverable["ready"]:
            raise StudioError("Delivery quality gate failed; see production/delivery_report.json")
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
    # Prepare any director-authorized visual continuation frame before reserving
    # a paid attempt; never re-use a guessed image from an unapproved clip.
    references = [root / r for r in state["references"]]
    references += prepare_continuity_reference(root, project, state, shot_id)
    if hasattr(browser, "preflight"):
        browser.preflight(references)
    # The browser reports a *visible click*, not actual Google billing completion.
    # A submission interrupted after click is still counted as possible spend.
    if browser.__class__.__name__ == "FlowBrowser" and hasattr(browser, "on_submit"):
        def observe_click(observed_shot: str) -> None:
            event(state, "flow_button_clicked", shot=observed_shot,
                  attempt=state["shots"][observed_shot]["attempts"])
            save_state(root, state)
        browser.on_submit = observe_click
    # Reserve one potential paid generation BEFORE touching the web UI.
    state["credits_remaining"] -= 1
    item = state["shots"][shot_id]
    item["attempts"] += 1
    item["status"] = "submission_uncertain"
    state["phase"] = "generation_uncertain"
    event(state, "generation_attempt_reserved", shot=shot_id, attempt=item["attempts"])
    save_state(root, state)
    try:
        output = browser.generate(root, project, next_shot, references)
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
        _record_candidate(root, state, shot_id, dest, origin="flow_browser")
    return state


def summary(state: dict) -> str:
    phase = state["phase"]
    instructions = {
        "gemini_ready": "Gemini web is ready: run advance (after verifying UI config).",
        "gemini_story_ready": "Stage 1: run advance for screenplay ONLY; Flow is not touched.",
        "awaiting_story_approval": "Review production/story_bible.json; approve --stage story or revise story JSON. No shots have been sent to Flow.",
        "gemini_plan_ready": "Stage 2: screenplay approved. Run advance to ask Gemini for storyboard + cut points.",
        "gemini_submission_uncertain": "Check which Gemini stage was submitted; recover with receive-gemini --file JSON or operator-approved resolve-gemini. Never auto retry.",
        "awaiting_storyboard_approval": "Review storyboard and continuity audit. For V1.3 director-first projects run director-review, fix reported hard problems, then approve storyboard.",
        "director_review_uncertain": "Review submission uncertain; inspect Gemini chat. Use receive-director-review --file JSON or explicitly resolve-director-review --action retry.",
        "awaiting_credit_approval": "Verify your logged-in Flow session, model, aspect, costs and selectors, then approve --stage credits --max-generations N.",
        "ready_to_generate": "Run advance to generate one pending shot (or render if all approved).",
        "generation_uncertain": "Inspect Flow: submission may have consumed credits. Use resolve --shot ID, then receive the file. Never auto-retry.",
        "awaiting_download": "Download video in Flow and use receive --shot ID --file PATH.",
        "awaiting_shot_approval": "Watch single-shot review and adjacent seam. Run verify-shot; for continuity projects also verify-seam --left ID --right ID; then approve shot.",
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
