# dungeon-cli Status

| Phase | Description | Status |
|-------|-------------|--------|
| 0 | Scaffold & smoke test | done |
| 1 | The LLM bridge | done |
| 2 | The DM contract (parsing + repair) | done |
| 3 | The game state engine | done |
| 4 | Prompt assembly & context management | done |
| 5 | UI & the game loop | done |
| 6 | Campaigns & character creation | done |
| 7 | Hardening & polish | done |
| 8 | Stretch goals (optional) | done (story export) |

## Phase 0 Notes

- Scaffold complete: pyproject.toml, config, directory tree, smoke script

## Phase 1 Notes

- LLMBridge with subprocess, timeout, retry, exponential backoff
- Process group killing: Windows CTRL_BREAK_EVENT, Unix SIGTERM to pg
- 8 tests pass covering: happy path, command not found, exit code retry, timeout, empty output, garbage output, retry count, latency

## Phase 2 Notes

- Contract parser validates: JSON structure, status, narration length (2-6 sentences), choices (max 3), per-op field requirements
- Markdown fence stripping as one-time recovery
- Repair loop: max 2 re-prompts, then fallback with zero state requests
- 27 tests pass (14 contract + 4 repair)

## Phase 3 Notes

- GameState with atomic save/load (temp file + os.replace)
- Dice with seeded RNG for deterministic tests
- Adjudicator: apply_requests operates on copy, drops invalid requests
- check_status: death automatic at HP 0, victory requires condition callback
- 33 tests pass (6 state + 10 rules + 17 adjudicate)

## Phase 4 Notes

- build_turn: 6 sections in fixed order, SYSTEM/CHARACTER/PLAYER ACTION never dropped
- Budget enforcement: trim story_so_far → oldest recent_turns → truncate world_seed
- compact(): summarizer prompt via bridge, graceful failure if bridge fails
- 12 tests pass

## Phase 5 Notes

- ui/render.py: status line with colored HP, narration panel, choices menu, typewriter effect
- ui/input.py: parse freeform, number selection, slash commands
- cli.py: game loop with /help, /save, /load, /quit, /stats, /retry commands
- Ctrl-C / EOF: autosave + clean exit
- 14 tests pass (9 input parsing + 5 game loop)

## Phase 6 Notes

- Two campaigns: sunken_vault (fantasy) and station_nine (sci-fi)
- Campaign JSON schema with rooms, archetypes, victory_room, dm_style
- Character creation: pick campaign → archetype → name → confirm
- Victory condition: location-based (reach victory_room)
- Per-campaign save slots: saves/{campaign_id}/game.json
- 17 tests pass (7 validate/load + 2 victory + 2 character + 2 campaign runs + 4 other)

## Phase 7 Notes

- Telemetry system: tracks repairs, fallbacks, turns, bridge failures per session
- Spinner: animated braille chars during bridge calls (threading + rich)
- Fuzz tests: 25+ adversarial tests across 5 categories (input, injection, engine, DM edge cases, stress)
- 20-turn stress run with adversarial inputs passes
- 100-turn session stays under budget
- README complete with install, config, campaign authoring
- All 135 tests pass

## Phase 8 Notes

- Story export: dump completed run to Markdown transcript
- Export prompt on victory/death
- Transcript includes character, all turns, final status, telemetry
- 14 additional tests (149 total)

## OpenAI-compatible bridge pass

- Sampling parameters: `temperature`, `max_tokens`, `top_p`, `seed` in `[llm.http]`,
  type/range checked at startup. Unset keys omitted, not null. Unknown keys forwarded
  unvalidated.
- `system_role` config flag splits the DM persona into a real system message, enabling
  `o1`/`o3`/`gpt-5`. Defaults to `false` to keep the existing wire format.
- `[llm.http.headers]` escape hatch for Azure `api-key`, OpenRouter attribution
  headers, and any other non-Bearer auth. Supplying `api-key`/`Authorization`
  suppresses the auto-generated header.
- Fixed: `Authorization: Bearer` was previously always sent, even with an empty key.
- Fixed: a content-filtered response (`content: null`, HTTP 200) returned
  `BridgeResult(ok=True, raw=None)`, raising `TypeError` downstream instead of taking
  the repair → `FALLBACK` path. Now a non-retryable bridge error.
- `scripts/smoke.py` rewritten to use `make_bridge()`; it previously read
  `config["llm"]["argv"]` and broke for every non-subprocess provider.
- Dead files removed: `undefined/` (a `path.join(x, undefined)` artifact),
  `session.txt` (agent scratch), `dm/prompts/system.txt` (zero references — the real
  system prompt is built inline in `ui/character_creation.py`).
- Original project brief moved from the repo root to `docs/BRIEF.md`.
- `.commandcode/` gitignored. Unused imports removed from `cli.py`, `ui/input.py`,
  `engine/adjudicate.py`, `engine/campaign.py`.
- Fixed tautological assertion in `tests/test_repair.py` that always passed.
- 224 tests pass (193 before this pass, +31 for the new bridge behavior).
