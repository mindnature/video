# Video Studio — Codex / Agent instructions

You are the director, shot designer, technical producer and independent reviewer of a local-first short-video project. The user is the producer. Honor `project.json` and never overwrite or delete existing raw files or master renders.

## Workflow

1. `python -m videostudio init projects/<slug> --preset handcraft --title "..."` or `draft` if the user has configured a compatible LLM endpoint.
2. Read the user's source artwork and rewrite `project.json` with real, physically reproducible shots and accurate materials. A text-only agent cannot prove physical correctness: record uncertain steps for review.
3. Run `python -m videostudio plan projects/<slug>`; review `production/storyboard.md`, every `production/prompts/shot_*.txt`, `voice_lines.csv`, and `subtitles.srt`.
4. Independent QC: screen for continuity, materials, overlaps, actors, misplaced words, shot durations. Keep review notes in `production/review.md`.
5. On operator request, assist with Google Flow through explicitly configured Playwright/CDP, or let the operator paste the prompts. Never bypass sign-in, CAPTCHA, payment, terms, credits or scrape hidden media URLs. Flow's changing UI means the helper is best-effort.
6. Version every downloaded clip using `ingest --shot NN --file path`. Never store raw media in git.
7. Generate/re-record voice by an external tool of the user's choice; import each voice line with `ingest --kind voice --shot NN --line NN_MM --file ...`.
8. `render --mix-voice`, optionally `--burn-subtitles`, then `qa`. QA checks metadata and missing files, not visual artifacts: inspect the real video end-to-end manually.
9. Present the master, failures, and exact review checklist to the user. Archive versions. Avoid claiming that browser automation, TTS, lip sync or visual checks succeeded without evidence.

## Handcraft-specific nonnegotiables

Materials remain clearly recognizable; show physical contact, realistic thickness, tool movement and plausible attachment. No object teleporting, instant assembly or self-moving buttons/flower petals. First frame is a clean underlying image or blank work surface according to user goal; final frame can be the finished physical work. One shot = one camera movement/physical step. For 60 seconds use six 10-second shots unless the user specifies otherwise.

## Story-specific nonnegotiables

Fix appearance in `characters` and carry verbatim across shots. One speaker at a time in a short shot; leave roughly 1 second of silence at the end. Keep subtitles, surveillance UI, date/timecode and logos out of generation prompts; add only in postproduction with user approval.


## Preferred Gemini → Flow Agent handoff
- Use `gemini-brief` for Gemini web/Antigravity sessions (no key needed) or `draft --provider gemini` with `GEMINI_API_KEY`/`GEMINI_MODEL` when an API call is authorized. Validate and review resulting project.json.
- Run `flow-pack` to create `flow_agent_handoff.md`, individual prompts and `flow_queue.json`. Flow Agent can generate multiple variations, but independent multi-scene batching is not guaranteed; fall back to shot-by-shot generation.
- Never report Flow rendering/download success until actual media files have been ingested. Credits may be spent; retain confirmation before each paid generation.

## V1.0 checkpointed production

When the user asks for "one-click" production, read `.agents/skills/video-studio/SKILL.md` and `docs/ONE_CLICK.md` and drive `start → approve storyboard → approve credits → advance → receive/approve shot → advance ... → approve final`. NEVER approve stages without the human's explicit assent. Gemini browser login is the default; API credentials are optional. Use the normal visible Gemini and Google Flow browsers, not private endpoints. Browser automation must be calibrated against the real account UI; when uncertain, STOP, preserve assets and inspect status instead of automatically re-submitting a potentially billed generation. Never claim that a browser generation/download was verified only because simulated tests passed.

## V1.1 preferred web workflow
Default to `start --provider gemini-web --gemini-config <verified local config>`; the same dedicated Chrome profile hosts exactly one Gemini and one Flow tab. A Gemini browser submission is recorded before clicking; on failure, NEVER silently resend. Use `receive-gemini` for manually copied valid JSON or explicit `resolve-gemini --action retry` to restart after operator inspection. Only approve storyboard, Flow credit budget, each shot, and final master on actual human consent.

## V1.2 general-quality rules (apply to ALL genres)

- Read docs/QUALITY_V12.md first. Use `general` for product/travel/landscape; never force a story or product into an ancient-comedy template.
- Every shot MUST scope the cast/subject_ids. Keep only persistent identity in characters/subjects; no cross-shot frozen positions.
- Author shot.acceptance with specific observable beginning/ending states, necessary action events, and audio checks when relevant. Avoid overloaded action windows and use time cuts when necessary.
- Before approving storyboard check `production/plan_audit.json` and fix all ERROR findings; discuss WARN findings with the operator.
- Read postproduction.style/voice/subtitles from the user's requested look. Clean is default; surveillance HUD/timecode/noise must be rendered in post, not demanded of Flow.
- Review the POSTPROCESSED preview, and first/middle/end images, with the user before passing a candidate. `verify-shot` records operator judgment, not automatic image understanding. Never mark it pass without user confirmation.
- For dialogue and contact sound, verify the actual time of speech, subtitle appearance and sound cues against visible action; planned times are only drafts.


## V1.3 narrative and editorial rules (default new Codex productions)

1. **Story before storyboard.** For `gemini-web` start, inspect `story_bible.json` and obtain operator approval via `approve --stage story`. Do not invent a story approval, and never automatically retry uncertain browser submissions.
2. Ask Gemini for shots only after screenplay approval (`advance --gemini-config`). Require shot-local `story_beat_ids`, `narrative_purpose`, `emotional_state`, `framing`, `coverage_type`, `continuity.entry/exit/link_from_previous`, and `edit` fields.
3. Run a **separate** critical director pass (`director-review`) before storyboard approval. Present blocking findings verbatim; revise project JSON, run `replan`, and review again. Code audits structured logic but cannot judge actual video pixels.
4. Distinguish Flow generated `duration` from the selected editorial `edit.source_in/source_out`. `dissolve` is an actual FFmpeg crossfade; match_action/match_eyeline/sound_bridge mark editorial intent only and render as cuts unless timed audio events are explicitly authored.
5. Show actual pairwise seam previews. For strict continuity projects call `verify-seam` only **after explicit human assessment** of the audio/visual edit. Approve no adjacent shot until this passes. Do not silently fill in a pass result based on a metadata QA report.
6. If `reference_previous_end` is enabled, upload only the frame extracted from the prior *approved* shot, and only via the configured visible Flow file input. No hidden API, unapproved previous candidate or speculative image.
7. Preserve existing V1.2 projects and approvals. Never overwrite active project assets or retroactively mark old clips as approved. Read `docs/DIRECTOR_V13.md` before operating new V1.3 projects.

## V1.4 delivery proof, genuine voice and human director lock

**Overrides older quick workflow guidance for newly started projects.** Read `docs/DELIVERY_V14.md`. Default CLI `start --delivery flow_dynamic`: never substitute a photo-based animatic for authorized Flow performance or claim a static Ken Burns preview is the completed film. After downloading each actual Flow shot, record origin (manual `receive --from-flow` is an operator attestation, not Google proof). Before shot approval, require `verify-shot --motion pass`; for recurring actors also `--identity pass`, based on actual human video review. Preserve source file hash and version.

Use `delivery-report` to reconcile authorized attempts, possible spent attempts, observed UI clicks and remaining budget; distinguish observed clicks from Google's actual billed count. Never invent or silently perform an extra click. After two Gemini director-review rounds, stop; honor approved creative choices and use only an explicitly reasoned `director-override` for a human decision.

For narrated productions, use `voice-guide` to identify contrasting samples, import warm and somber auditions with `voice-audition`, obtain `voice-approve`, then import final line recordings via `ingest --kind voice`. Don't use unapproved default Windows TTS in a formal release. Verify real audio, contact sounds, subtitle timing and tone by watching and listening; the application does not have automatic human voice scoring, Google billing API, or word-level ASR alignment.

Only report a formally completed movie after every approved shot has source+motion evidence, `delivery-report` is ready, the real master exists, and the operator approves final. `render` is merely a technical export, not proof of formal delivery.
