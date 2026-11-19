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


## V1.3 default: staged story → storyboard → director critique → visual seam QC

**Supersedes the V1.2 direct-to-storyboard quick path for new Gemini web projects.**
Read `docs/DIRECTOR_V13.md`. After `start`, show only `story_bible.json` and obtain explicit user approval via `approve --stage story`. `advance --gemini-config ...` then asks Gemini for the storyboard with causal beat IDs, emotional reaction, visible face/subject framing, continuity entry/exit and source trim points. Next run `director-review --gemini-config ...`; if any hard issues, revise `project.json` + `replan` + fresh director-review. Do not approve storyboard before a clean critic report and user approval. Budget authorization and Flow generation happen **afterward**, never automatically.

For an approved predecessor + new candidate, the project emits `production/review/seams/seam_LEFT_RIGHT_*.mp4`. Ask the user to watch the seam; if continuous, `verify-seam --left ... --right ... --result pass --note ...`, then approve shot. Rejection retains all original versions. If frame reference is opted in, project extracts only an approved previous shot's actual end frame. A shot 8s long might be edited to 3s using `edit`, so review `edit_timeline.json` before reporting final duration.

All Gemini/Flow browser interactions are best effort against the user's current visible UI. No claims of end-to-end video generation without watching actual downloaded video and collecting operator approvals. Do NOT submit more Flow attempts based solely on the user's agreement to edit the script.

## V1.4 delivery proof, genuine voice and human director lock

**Overrides older quick workflow guidance for newly started projects.** Read `docs/DELIVERY_V14.md`. Default CLI `start --delivery flow_dynamic`: never substitute a photo-based animatic for authorized Flow performance or claim a static Ken Burns preview is the completed film. After downloading each actual Flow shot, record origin (manual `receive --from-flow` is an operator attestation, not Google proof). Before shot approval, require `verify-shot --motion pass`; for recurring actors also `--identity pass`, based on actual human video review. Preserve source file hash and version.

Use `delivery-report` to reconcile authorized attempts, possible spent attempts, observed UI clicks and remaining budget; distinguish observed clicks from Google's actual billed count. Never invent or silently perform an extra click. After two Gemini director-review rounds, stop; honor approved creative choices and use only an explicitly reasoned `director-override` for a human decision.

For narrated productions, use `voice-guide` to identify contrasting samples, import warm and somber auditions with `voice-audition`, obtain `voice-approve`, then import final line recordings via `ingest --kind voice`. Don't use unapproved default Windows TTS in a formal release. Verify real audio, contact sounds, subtitle timing and tone by watching and listening; the application does not have automatic human voice scoring, Google billing API, or word-level ASR alignment.

Only report a formally completed movie after every approved shot has source+motion evidence, `delivery-report` is ready, the real master exists, and the operator approves final. `render` is merely a technical export, not proof of formal delivery.


## V1.5 Jianying audio handoff (official-visible desktop UI only)

If the user wants 剪映 (Jianying) voices or natural Chinese narration, read `docs/JIANYING_V15.md`. A planned narration automatically gets `production/jianying` text/CSV/timing templates, or run `video-studio jianying-pack PROJECT`. Ask the user to choose a voice and use Jianying text-to-speech in the visible desktop app, export audio, then call `jianying-import --audio PATH --full-track` for a full-timeline track (or `--line LINE_ID` per utterance). User must check/edit `alignment.json` against actual voice phonemes, approve with `jianying-approve --note ...`, and keep V1.4 warm/somber `voice-audition` / `voice-approve` where required. Only validated, approved tracks may reach the final FFmpeg output; source file hashes and prior versions are retained. Do not invent an official Jianying API or claim automatic TTS, voice naturalness scoring, or forced alignment.
