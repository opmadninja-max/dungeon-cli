# dungeon-cli — Bug Audit (2026-09-08)

Adversarial audit per the 8-pass protocol. Read-only: no source files were modified.
Environment: Windows, Python 3.14, cp1252 console. Test suite result: **149 passed, 0 failed, 0 skipped/xfail** (pytest, 8.58s).

Severity counts: 2 CRITICAL, 5 MAJOR, 3 MINOR.

---

BUG-001 | CRITICAL | cli.py:184 + cli.py:258-262 (**FIXED 2026-09-08**: game_loop now mutates state in place via `GameState.update_from`; exit-path saves wrapped in try/except OSError; regression test `test_interrupt_saves_current_state`)
WHAT: An interrupt (Ctrl-C / EOF) anywhere outside the input prompt saves the *pre-session* state, silently wiping all progress of the current game.
TRIGGER: Start a new game, play any number of turns, then press Ctrl-C while the DM is thinking (spinner/bridge call), during parse/repair, or during narration rendering. The save file written on exit contains turn 0.
TRACE: `game_loop` rebinds its local variable at cli.py:184 (`state = new_state`); `main()`'s `state` (cli.py:252/254/259) still references the original object. The only `try` inside `game_loop` covers the input prompt (cli.py:127-132, which correctly saves the current local `state`). Any `KeyboardInterrupt`/`EOFError` raised during `bridge.ask` (cli.py:162-166), parsing, or rendering propagates to `main()`'s handler (cli.py:258-262), which calls `state.save(save_path)` on the stale object.
CONFIDENCE: **Reproduced** — scripted session with 2 completed turns + KeyboardInterrupt inside the bridge: saved file contains `turn: 0, log: 0`. Secondary observation: if that stale save hits a transient `os.replace` lock (observed once, WinError 5), the exception handler itself crashes, leaving a `game.json.tmp` behind and printing a raw traceback.
FIX DIRECTION: Have `game_loop` persist the current state back to the caller (return it, mutate in place, or use a mutable holder) so `main()`'s interrupt handler saves the live state; optionally wrap the exit-path save in try/except.

BUG-002 | CRITICAL | menu.py:42-50, character_creation.py:33-41 (**FIXED 2026-09-08**: pickers now let EOFError propagate; `main()` catches it once with a clean goodbye; regression tests in test_ui.py + test_campaign.py)
WHAT: EOF at the campaign picker or archetype picker causes an infinite loop (process hang, unbounded output).
TRIGGER: Pipe closed stdin / press Ctrl-D at the "Choose a Campaign" or "Choose your archetype" prompt.
TRACE: Both loops are `while True` catching `(ValueError, EOFError): pass` and then printing "Invalid choice. Enter a number." — EOF raises `EOFError` on every `input()` forever. (`menu.main_menu` handles this correctly by returning "quit" on EOF, menu.py:19-20; these two loops do not.)
CONFIDENCE: **Reproduced** — with a permanently-raising `input()`, `pick_campaign` emitted 2,000,000+ chars of "Invalid choice." in 15s before being killed by timeout.
FIX DIRECTION: Catch EOFError separately and exit cleanly (return/sentinel), mirroring `main_menu`'s behavior.

BUG-003 | MAJOR | dm/prompt.py:144-175, cli.py (absence) (**FIXED 2026-09-08**: `compact(context, bridge, keep)` now keeps the last K turns verbatim per spec; `game_loop` triggers it every `compact_after` turns (new `[prompt] compact_after = 10`), mutating the caller's context in place; telemetry counts compactions; regression tests in test_prompt.py + test_ui.py)
WHAT: `compact()` is dead code — compaction is never triggered, so `story_so_far` is never updated, early story is permanently invisible to the DM, and `context.recent_turns` grows without bound.
TRIGGER: Any game longer than `recent_turns` (5) turns; effects compound over a long session.
TRACE: `grep compact cli.py` → not imported or called; `game_loop` only appends to `context.recent_turns` (cli.py:191) and never calls `compact(context, bridge)`. Spec Phase 4 requires: "when the char char budget is exceeded, make one bridge call with a summarizer prompt to fold old turns into a story_so_far paragraph". docs/STATUS.md Phase 4 claims "compact(): summarizer prompt via bridge, graceful failure" as done — it exists but is unreachable. Consequences: (a) the DM sees only the last 5 turns verbatim forever, with `story_so_far` permanently empty; (b) `context.recent_turns` and `history` are unbounded lists (slow memory growth in long sessions); (c) prompt trimming silently discards history the spec says should be compacted.
CONFIDENCE: **Traced** (static, conclusive; unit tests only exercise `compact` directly, never through the loop).
FIX DIRECTION: Trigger compaction from `game_loop` (e.g., when `len(context.recent_turns)` exceeds a threshold or the assembled prompt nears budget), folding old turns into `story_so_far`.

BUG-004 | MAJOR | cli.py:169-181, engine/adjudicate.py:22 (**FIXED 2026-09-08**: FALLBACK now short-circuits at the call site in cli.py — render-only, no `apply_requests`, no TurnRecord, turn not counted; `telemetry.record_turn()` moved to real turns; new `failed_turns` counter in /stats; TDD regression tests T1-T5 in test_ui.py. adjudicate.py and repair.py untouched by design.)
WHAT: When the bridge fails or the response can't be repaired, the player's action is consumed: the FALLBACK narration renders as a normal turn and the turn counter advances, so the DM never processes what the player actually did.
TRIGGER: Any bridge failure (timeout, exit 1, empty output) or a response that fails parse + 2 repair attempts.
TRACE: cli.py:174-176 sets `dm_resp = FALLBACK` (or repair returns FALLBACK); the normal pipeline then runs `apply_requests`, which unconditionally does `s.turn += 1` (adjudicate.py:22) and appends the turn record (cli.py:185-192) as if the DM had responded. The player's typed action is gone from the queue — they must retype it, and the status line shows an inflated turn number.
CONFIDENCE: **Reproduced** — scripted game with a failing bridge: fallback panel rendered, status line advanced "Turn: 1" → "Turn: 2", action "open the heavy door" logged as a completed turn.
FIX DIRECTION: On fallback, either replay the same action next turn (don't consume it / don't advance the turn) or keep the action in the prompt history explicitly flagged so the DM can address it.

BUG-005 | MAJOR | cli.py:144-157, cli.py:191-192 (**FIXED 2026-09-08**: `game_loop` tracks the last attempt's TurnRecord; `/retry` now pops it — identity-guarded so a retry after a failed attempt can't delete an earlier record — from both `context.recent_turns` and `history`, with `telemetry.retract_turn()` keeping total_turns == len(history); TDD tests T-A..T-D in test_ui.py)
WHAT: `/retry` appends a second TurnRecord with the same turn number to both `context.recent_turns` and `history`, corrupting the DM's context, the exported transcript, and telemetry.
TRIGGER: Play a turn, then `/retry`.
TRACE: cli.py:145-148 restores `state = last_state` (turn counter correctly preserved — adjudicate.py:22 re-increments from the pre-turn value), but the original attempt's TurnRecord (appended at cli.py:191-192 during the first run) is never removed. The retry appends a second record with the same `turn` number. Effects: transcript shows duplicate "### Turn N" sections; the next prompt's RECENT TURNS section shows both the failed attempt and the retry (stale, contradictory context for the DM); `telemetry.record_turn()` double-counts.
CONFIDENCE: **Reproduced** — transcript headings were `['1', '2', '2']` after one `/retry`.
FIX DIRECTION: On retry, pop the last TurnRecord from `context.recent_turns` and `history` (or mark the retry as replacing the record) before appending the new one.

BUG-006 | MAJOR | cli.py:60-69, cli.py:141-143 (**FIXED 2026-09-08**: the `/load` branch in `game_loop` now performs a narrative hard reset — clears `context.recent_turns`, `context.story_so_far`, `history`, and the `last_state`/`last_action`/`last_record` retry trackers — so `/retry` after `/load` prints "Nothing to retry." instead of reverting the load, and exports contain only post-load turns; TDD tests T1-T3 in test_ui.py. Telemetry intentionally left session-cumulative.)
WHAT: `/load` restores game state but not session context: `context.recent_turns`, `history`, `last_state`, and `last_action` are left stale, and a later `/retry` silently reverts to the pre-load timeline.
TRIGGER: Play several turns, `/save`, play more turns, `/load`, then `/retry` (or `/save` again).
TRACE: `handle_command` "/load" copies fields onto the in-place state (cli.py:63-67) and returns "load"; the loop's handler only resets `choices = []` (cli.py:141-143). It never clears `context.recent_turns` (next prompt narrates turns from the discarded timeline), never clears `history` (export mixes two timelines), and never resets `last_state`/`last_action` — so `/retry` assigns `state = last_state` (cli.py:146), the pre-load clone, discarding the just-loaded state in memory; a subsequent save then persists the reverted timeline over the loaded file.
CONFIDENCE: **Traced** (code path is unambiguous; the load branch is 3 lines with no context reset).
FIX DIRECTION: On `/load`, rebuild/clear `context.recent_turns`, `history`, `last_state`, and `last_action` alongside the state swap.

BUG-007 | MAJOR | cli.py:249 (**FIXED 2026-09-08**: `Player` now persists `archetype` (name) through the save; `build_initial_state` stamps it; the Continue path resolves the saved archetype against `campaign.archetypes` with fallback to `archetypes[0]` if the campaign no longer has it; `GameState.from_dict` loads player dicts tolerantly so pre-existing saves work; TDD tests T1-T3 in test_state.py / test_campaign.py / test_ui.py)
WHAT: The "Continue" menu path builds the DM's system prompt from `campaign.archetypes[0]` regardless of the archetype the saved character actually is.
TRIGGER: Create a character with archetype 2 (e.g., Marine), save, quit, then "Continue".
TRACE: cli.py:249: `context = character_creation._build_context(campaign, state.player.name, campaign.archetypes[0])` — hardcoded index 0. The system prompt then asserts "The player is {name}, the Engineer" (character_creation.py:79) for a Marine. The CHARACTER section carries the true HP/inventory, but the persona instruction contradicts it every turn. The archetype is not saved in the save file, so it cannot be recovered from state.
CONFIDENCE: **Traced** (deterministic code path; no archetype field in `GameState.to_dict`).
FIX DIRECTION: Persist the archetype (or at least its name) in the save and use it when rebuilding context on continue.

BUG-008 | MINOR | ui/spinner.py:27-33 (**FIXED 2026-09-08**: encoding-aware frame set — braille on UTF-8 streams, ASCII `|/-\` on legacy codepages via `_frames_for(sys.stdout)`; the animation thread also guards against `UnicodeEncodeError`/`OSError` so it can never spew tracebacks; tests T1-T4 in test_ui.py)
WHAT: The spinner's animation thread dies with `UnicodeEncodeError` on legacy cp1252 Windows consoles (braille characters are unencodable), spewing thread tracebacks every bridge call.
TRIGGER: Run the game with `spinner = true` (default) on a Windows console with a legacy codepage (no UTF-8).
TRACE: `_animate` prints braille chars (spinner.py:28-31) through `rich`; on a cp1252 `LegacyWindowsTerm` the encode fails inside the thread. The process survives (thread is daemon) and `stop()` still joins, but the spinner is dead and tracebacks print per turn.
CONFIDENCE: **Reproduced** — observed on this machine in every scripted headless run (`UnicodeEncodeError: 'charmap' codec can't encode character '\u280b'`).
FIX DIRECTION: Use ASCII spinner frames, or configure the rich Console/file with `errors="replace"` / force UTF-8 for the spinner console.

BUG-009 | MINOR | cli.py:246-249, engine/state.py:52-62 (**FIXED 2026-09-08**: both `GameState.load` call sites in cli.py are guarded — the Continue path falls back to "Starting new game" and in-game `/load` shows an error and continues, catching `OSError`/`ValueError`/`KeyError`/`TypeError`. The unknown-player-keys half was already fixed by BUG-007's tolerant `from_dict`. `GameState.load` itself still raises by contract; tests T1-T3 in test_ui.py)
WHAT: A corrupt or version-skewed save file crashes the "Continue" path with a raw traceback (JSONDecodeError, or TypeError from unknown/missing keys in `Player(**data["player"])`).
TRIGGER: Truncate or hand-edit `saves/<campaign>/game.json`, then choose Continue.
TRACE: cli.py:248 `GameState.load(save_path)` has no error handling in `main()`; `from_dict` (state.py:53) does strict `Player(**data["player"])` — extra/missing keys raise TypeError. The atomic save (temp + `os.replace`) means normal crashes can't produce partial saves, so this requires external corruption or a schema change between versions.
CONFIDENCE: **Traced** (test_state.py already documents the raising behavior; cli never catches it).
FIX DIRECTION: Catch load errors on the Continue path and fall back to "No save file found. Starting new game."

BUG-010 | MINOR | character_creation.py:33-41, menu.py:42-50, cli.py:236-243 (**FIXED 2026-09-08**: `main()`'s two pre-game guards now catch `(EOFError, KeyboardInterrupt)` and exit with the clean "Goodbye!" message — same pattern as BUG-002; mid-game Ctrl-C was already handled by BUG-001's autosave path; tests T1-T4 in test_ui.py)
WHAT: Ctrl-C during character creation or campaign picking escapes as an uncaught `KeyboardInterrupt` with a raw traceback (no autosave, no clean exit).
TRIGGER: Press Ctrl-C at the archetype/name/confirm or campaign-number prompt.
TRACE: Those `input()` calls catch only `(ValueError, EOFError)`; `main()`'s `try` (cli.py:258) wraps only `game_loop`, so the interrupt propagates out of `main()` unhandled. (Inside `game_loop` the prompt-level handler saves correctly — this gap is only in the pre-game menus.)
CONFIDENCE: **Traced** (EOFError variant of the same loops is reproduced in BUG-002; KeyboardInterrupt path is the identical except-clause).
FIX DIRECTION: Catch KeyboardInterrupt at the menu/creation level and return to the main menu or exit cleanly.

---

## Summary

| Bug | Severity | Location | One-liner | Confidence |
|-----|----------|----------|-----------|------------|
| BUG-001 | CRITICAL | cli.py:184, 258-262 | Interrupt outside input prompt saves stale (turn-0) state — progress wiped | reproduced |
| BUG-002 | CRITICAL | menu.py:42-50, character_creation.py:33-41 | EOF at campaign/archetype picker = infinite loop (hang) | reproduced |
| BUG-003 | MAJOR | dm/prompt.py:144, cli.py | `compact()` never called — story_so_far dead, recent_turns unbounded | traced |
| BUG-004 | MAJOR | cli.py:169-181, adjudicate.py:22 | Bridge failure consumes the player's action and advances the turn | reproduced |
| BUG-005 | MAJOR | cli.py:144-157, 191-192 | `/retry` duplicates turn records in context, history, transcript, telemetry | reproduced |
| BUG-006 | MAJOR | cli.py:60-69, 141-143 | `/load` leaves stale context; `/retry` after `/load` reverts the load | traced |
| BUG-007 | MAJOR | cli.py:249 | Continue path hardcodes archetypes[0] in the DM system prompt | traced |
| BUG-008 | MINOR | ui/spinner.py:27-33 | Spinner thread crashes (UnicodeEncodeError) on cp1252 consoles | reproduced |
| BUG-009 | MINOR | cli.py:246-249, state.py:52-62 | Corrupt/incompatible save crashes Continue with raw traceback | traced |
| BUG-010 | MINOR | character_creation.py, menu.py, cli.py:236-243 | Ctrl-C in menus/character creation = unhandled traceback | traced |

Test suite: 149 passed, 0 failed, 0 skipped, 0 xfail.

## DISMISSED

Investigated and ruled out, with reasons (so the next auditor doesn't redo these):

- **Golden rule violations (PASS 1)**: every gameplay mutation flows through `apply_requests` (engine/adjudicate.py) — `cli.py:180` is the single adjudication site per turn. The FALLBACK path renders through the *normal* pipeline (adjudicate + render + history, cli.py:174-181), it does not bypass adjudication. `/save`, `/load`, `/quit` are user-initiated and legitimate. DM narration, prompt text, and player input never write state directly. No violation found.
- **Save atomicity (PASS 2)**: `state.py:64-70` genuinely implements temp file + `os.replace`; a crash between write and rename leaves only a `.tmp` sibling and the loader reads only the final path, so no partial-save load path exists. `.tmp` naming via `with_suffix` is correct for the actual filenames.
- **Save/load roundtrip lossiness (PASS 2)**: `to_dict`/`from_dict` handle only primitives (strings, ints, lists, dicts of JSON values — flag values originate from `json.loads` and are always serializable). No tuples, sets, enums, or float precision issues. Roundtrip is lossless.
- **Cross-campaign save loading (PASS 2)**: saves are stored under `saves/<campaign_id>/game.json` (cli.py:242-244), so a save can't be loaded for the wrong campaign.
- **Bridge zombies/orphans (PASS 3)**: on timeout the process group is signalled (CTRL_BREAK_EVENT on Windows with CREATE_NEW_PROCESS_GROUP; killpg on POSIX with `start_new_session`) and `proc.wait(timeout=5)` → `proc.kill()` → `proc.wait()` guarantees reaping (bridge.py:95-107). Covered by `TestBridgeTimeout`.
- **Bridge retry loop (PASS 3)**: attempts bounded at `retries + 1`; exponential backoff implemented and capped at 30s (bridge.py:30-33); `FileNotFoundError` fails fast without retry. No infinite or non-retryable retry path.
- **Shell injection (PASS 3)**: no `shell=True` anywhere; argv comes from the trusted config file; player text travels via stdin only.
- **Bridge blocking forever (PASS 3)**: worst case per call is bounded (retries × (timeout + backoff)); every `communicate` has a timeout.
- **Parser adversarial inputs (PASS 4)**: truncated JSON, trailing text, nulls, wrong types, duplicate keys (last-wins) all raise `ContractError` → repair → FALLBACK. Markdown fence stripping is single-pass as spec'd. Repair is capped at 2 attempts (repair.py:39) and the repair prompt is rebuilt fresh from only the current bad output — no unbounded growth across turns. Covered by test_contract.py, test_repair.py, test_fuzz.py.
- **HP rules (PASS 5)**: clamp `max(0, hp - dmg)` happens before the death log and `check_status` re-checks `hp <= 0` independent of the DM's proposed status (death cannot be talked out of). `damage_for` always returns ≥ 1 (dice `randint(1, sides)`), so no negative-damage heal; there is no op that can raise HP, so `max_hp` holds.
- **Ops validation (PASS 5)**: `give_item` blocks duplicates, `take_item` requires the item, `move` requires a known room, each with a logged drop reason. `set_flag` accepts arbitrary keys — this is by design (an adjudicated op; the contract only requires a non-empty string key).
- **Severity→damage mapping (PASS 5)**: matches the spec exactly (minor 1d4, major 1d8, critical 2d10). It's hardcoded in rules.py rather than read from dungeon-cli.toml (spec said "from config") — cosmetic deviation, values correct, invalid severities are rejected at the contract layer.
- **Seeded RNG / reload divergence (PASS 5)**: `Dice` supports seed injection but `game_loop` always creates an unseeded `Dice()` per turn (cli.py:179) and no RNG state is saved. Since nothing is deterministic to begin with, there is no uninterrupted-vs-reloaded divergence bug to corrupt; `/retry` re-rolls dice with a fresh `Dice`, which is consistent with "re-runs the last action".
- **`/retry` turn counter (PASS 5)**: correctly preserved — `last_state` is cloned pre-turn (cli.py:156), adjudication re-increments from that value. (The record duplication is BUG-005.)
- **Prompt budget measurement (PASS 6)**: enforced by actual `len()` measurement, not estimation; "last K turns verbatim" uses `[-recent_limit:]` with no off-by-one; trimming order matches spec (story_so_far → oldest recent turns → world_seed). One soft spot: PLAYER ACTION is protected and never truncated, so a ~10k-char paste yields a prompt over budget — but the spec only mandates never dropping SYSTEM/STATE, the game doesn't crash (fuzz-verified), and the alternative (dropping the player's own action) would be worse. Not filed.
- **Player injection into SYSTEM section (PASS 6)**: player action always lands in its own `=== PLAYER ACTION ===` section; no path injects it into SYSTEM.
- **Prompt built from stale state (PASS 6)**: `build_turn` is called with the post-adjudication `state` each iteration (cli.py:161 uses the reassigned local).
- **EOF/Ctrl-C at the in-game input prompt (PASS 7)**: handled by cli.py:127-132 with a correct autosave of the *current* local state (this is the path that works, unlike BUG-001).
- **Empty input / out-of-range number (PASS 7)**: empty re-prompts; a digit with no matching choice falls through to freeform action.
- **Death/victory epilogue (PASS 7)**: export offer handles EOF/Ctrl-C cleanly (cli.py:212-216); death cannot be suppressed by the DM (`check_status` overrides).
- **Unseeded-dice tests, fuzz suite, campaign validation, victory conditions, telemetry**: all covered by the existing 149-test suite, which passes cleanly.
