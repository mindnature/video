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

When the user asks for "one-click" production, read `.agents/skills/video-studio/SKILL.md` and `docs/ONE_CLICK.md` and drive `start → approve storyboard → approve credits → advance → receive/approve shot → advance ... → approve final`. NEVER approve stages without the human's explicit assent. Gemini API requires the user's credential; use the normal visible Google Flow browser, not private endpoints. Browser automation must be calibrated against the real account UI; when uncertain, STOP, preserve assets and inspect status instead of automatically re-submitting a potentially billed generation. Never claim that a browser generation/download was verified only because simulated tests passed.
