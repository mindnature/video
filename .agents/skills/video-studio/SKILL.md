---
name: video-studio
description: Orchestrate user-approved AI video production from a Chinese creative idea or reference image using Gemini for storyboard, Google Flow for video clips, and FFmpeg for final editing. Trigger when asked to make a short film, handcraft documentary, storyboard, or resume a Video Studio project.
---

# Video Studio — one command + human review gates

You are the user's production coordinator in Codex. The user should only need to provide a creative description and optional reference photos, then approve at each checkpoint. DO NOT invent model results, Flow UI controls, downloads or completed video outputs. The project is local-first and requires user login into Google Flow. Read repository `AGENTS.md` and `README.md` first.

## Setup (once per computer)

- Ensure `python -m pip install -e '.[flow]'`, `video-studio doctor` and FFmpeg are available.
- Default to Chrome Gemini (no API key). Only request GEMINI_API_KEY/GEMINI_MODEL if the user explicitly opts for `start --provider gemini` API fallback; never ask for a password or store credentials.
- User opens a dedicated Chrome profile with `scripts/open_flow_chrome.ps1`, signs into Gemini AND Flow (both tabs), chooses video mode, model, 9:16/16:9, count=1 and confirms generation credit budget.
- First call `video-studio inspect-gemini PROJECT --gemini-config PATH` and calibrate Gemini prompt/send/response selectors using `examples/gemini_ui.example.json`. Separately call `inspect-flow` and calibrate Flow selectors using `examples/flow_ui.example.json`. Use local gitignored config files. Do not guess selectors. No bypassing challenges, Google authentication, limits or payments.

## Produce from a photo or concept

1. Create a new unique project path. `video-studio start projects/<slug> --idea "..." --title "..." --preset handcraft --shots 6 --reference <path>` (omit reference if none). This defaults to `--provider gemini-web` and submits ONE Gemini browser chat via the dedicated Chrome window, then validates visible response JSON, saves the prompt kit and run state. Add `--gemini-config projects/gemini-ui.local.json`. No API key required. Do not bypass storyboard approval.
2. Show `production/storyboard.md` and relevant prompts, check realism and material physical constraints. Ask for human approval. Only after explicit approval run `video-studio approve PROJECT --stage storyboard`.
3. Check Flow browser settings, upload/reference setup and expected credits, tell user exactly what will be generated. Only on explicit approval run `video-studio approve PROJECT --stage credits --max-generations 6` (or number explicitly approved). This is a budget *cap*, not a purchase.
4. `video-studio advance PROJECT --flow-config local-flow-ui.json`. That runs at most one Flow clip. On success it pauses for clip review, or awaits download. On missing selectors/UI timeout it fails safely; always report `video-studio status PROJECT` and never re-submit automatically.
    - If Gemini times out after submitting, STOP: inspect the chat; use `receive-gemini` with manually copied valid JSON, or explicit `resolve-gemini --action retry` followed by `advance --gemini-config ...`. Never automatically retry.
5. If Flow produced a clip but did not download automatically, user saves via the visible Flow download menu; call `video-studio receive PROJECT --shot ID --file PATH`. Show clip and contact sheet in `production/review`. If approved, `video-studio approve PROJECT --stage shot --shot ID`; if rejected, `video-studio reject ... --reason ...`. Repeat `advance` after each review.
6. After all clips are individually approved, `advance` runs metadata QA and renders a master. Show final output. Only after the user watches and approves execute `video-studio approve PROJECT --stage final`.
7. `video-studio status PROJECT` can be run at any time. After a crashed/uncertain paid submission, inspect the Flow page **before** `video-studio resolve PROJECT --shot ID --action download` or `--action retry`. Never retry automatically; retrying may consume more credits.

## Non-negotiable review behavior

- Storyboard edits: before any generation, edit `project.json` then `video-studio replan PROJECT`, re-present the plan, seek new approval.
- For handcraft, prioritize authentic materials, visible hands/tools/contact shadows/adhesive steps, physically plausible motions, no teleporting/popping/automatic attachment, one dominant action per 10-second shot.
- For video-model output durations, reconcile actual Flow clip duration with plan; short clips may freeze-pad and require artistic review.
- Human approval is required for each paid-generation budget, each candidate shot, and final master; do not approve on the user's behalf.
- If browser download automation cannot find a new result tile, stop and use a user-visible manual download. Flow UI selectors and model settings are not stable APIs.
- Do not upload the user's media to GitHub or another service beyond the explicitly requested Gemini and Flow workflows.

## V1.2 Cross-genre production-quality checkpoint

- Prefer `--preset general` for products and non-character-led videos. Do NOT treat any test story as a global filming rule.
- Gemini must emit scoped `shot.cast` / `shot.subject_ids` and a concrete `acceptance` for each shot, while `characters`/`subjects` contain identities only.
- `video-studio plan` writes `production/plan_audit.json`. Do not approve the storyboard while it contains ERROR findings, including permanent motion states in identity descriptions or contradictory end-state requirements.
- Respect optional `postproduction.style` (`clean`, `surveillance`, `vintage`, `cinematic`) and `voice`/`subtitles` (`auto`, `on`, `off`). Surveillance UI must be visible in the FIRST clip handed to the user, not only in the final render.
- When a candidate arrives, show the **actual** styled review clip and near-final frame. Ask the user whether the observable acceptance conditions and sound/subtitles are correct. Do not assume a file duration check proves the shot is correct.
- After explicit review confirmation: `video-studio verify-shot PROJECT --shot NN --result pass --note "..."`, then `video-studio approve PROJECT --stage shot --shot NN`. Otherwise reject and keep all history.
- Actual audio phoneme and on-screen contact sync requires manual inspection; software only compares planned timing and basic track lengths.
