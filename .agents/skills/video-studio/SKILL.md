---
name: video-studio
description: Orchestrate user-approved AI video production from a Chinese creative idea or reference image using Gemini for storyboard, Google Flow for video clips, and FFmpeg for final editing. Trigger when asked to make a short film, handcraft documentary, storyboard, or resume a Video Studio project.
---

# Video Studio — one command + human review gates

You are the user's production coordinator in Codex. The user should only need to provide a creative description and optional reference photos, then approve at each checkpoint. DO NOT invent model results, Flow UI controls, downloads or completed video outputs. The project is local-first and requires user login into Google Flow. Read repository `AGENTS.md` and `README.md` first.

## Setup (once per computer)

- Ensure `python -m pip install -e '.[flow]'`, `video-studio doctor` and FFmpeg are available.
- Request GEMINI_API_KEY and GEMINI_MODEL only when absent; credentials are configured by user in local environment and never pasted in chat or committed. A Gemini subscription is not the same as Gemini API access.
- User opens a dedicated Chrome profile with `scripts/open_flow_chrome.ps1`, signs into Flow, chooses video mode, model, 9:16/16:9, count=1 and confirms generation credit budget.
- Call `video-studio inspect-flow PROJECT --flow-config PATH` and review the local screenshot/selector counts. Configure the verified CSS selectors in a local JSON file copied from `examples/flow_ui.example.json`. Do not guess selectors. No bypassing challenges, Google authentication, limits or payments.

## Produce from a photo or concept

1. Create a new unique project path. `video-studio start projects/<slug> --idea "..." --title "..." --preset handcraft --shots 6 --reference <path>` (omit reference if none). This calls Gemini API with the reference image, then saves a complete JSON, prompt kit and run state. Do not bypass storyboard approval.
2. Show `production/storyboard.md` and relevant prompts, check realism and material physical constraints. Ask for human approval. Only after explicit approval run `video-studio approve PROJECT --stage storyboard`.
3. Check Flow browser settings, upload/reference setup and expected credits, tell user exactly what will be generated. Only on explicit approval run `video-studio approve PROJECT --stage credits --max-generations 6` (or number explicitly approved). This is a budget *cap*, not a purchase.
4. `video-studio advance PROJECT --flow-config local-flow-ui.json`. That runs at most one Flow clip. On success it pauses for clip review, or awaits download. On missing selectors/UI timeout it fails safely; always report `video-studio status PROJECT` and never re-submit automatically.
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
