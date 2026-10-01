# dungeon-cli

A single-player terminal text adventure with an LLM Dungeon Master.

## How It Works

The LLM narrates; the engine referees. The DM proposes outcomes via state requests — the engine validates, rolls dice, and applies them. This prevents drift, cheating, and hallucinated inventory.

**Golden rule**: The LLM never owns game state. The deterministic engine is the sole source of truth for HP, inventory, location, and flags.

---

## Quick Start

Everything below assumes you are **in the project folder**. Every command must be run from there — the game looks for `dungeon-cli.toml` and `content/` relative to your current directory, and will not find them otherwise.

### 1. Check you have Python 3.10 or newer

```bash
python --version
```

You need `Python 3.10` or higher. If you see `3.9` or lower, install a newer version from [python.org](https://www.python.org/downloads/). On Windows, make sure you tick **"Add Python to PATH"** during install.

### 2. Install

```bash
python -m venv .venv
```

Activate it:

**Windows (PowerShell or CMD):**
```powershell
.venv\Scripts\activate
```

**macOS / Linux:**
```bash
source .venv/bin/activate
```

Your prompt should change to show `(.venv)`. Install the game:

```bash
pip install -e .
```

This installs the single dependency (`rich`) and sets up the `dungeon-cli` command.

### 3. Point it at a model

Open `dungeon-cli.toml` in any text editor and set your endpoint. You need **either** an API key **or** a provider that works without one:

```toml
[llm]
provider = "http"
model    = "gpt-4o-mini"

[llm.http]
base_url = "https://api.openai.com/v1"
api_key  = "sk-..."          # omit this line if your provider needs no key
```

To avoid writing your key in a file, delete the `api_key` line and set it as an environment variable instead — the game checks `$LLM_API_KEY`, then `$OPENAI_API_KEY`:

**Windows PowerShell:**
```powershell
$env:LLM_API_KEY = "sk-..."
```

**macOS / Linux:**
```bash
export LLM_API_KEY="sk-..."
```

See [Configuration](#configuration) for local models, reasoning models, and other providers.

### 4. Verify the connection

Before starting a game, confirm the model answers:

```bash
python scripts/smoke.py
```

Expected:
```
Provider: HTTPBridge
Prompt: 'Reply with the single word: OK'
Response: 'OK'
SMOKE TEST PASSED
```

If this fails, the problem is your endpoint or key — fix it before continuing. See [Troubleshooting](#troubleshooting).

### 5. Play

```bash
python cli.py
```

Or, if your virtual environment is still activated, you can also run it as a command:

```bash
dungeon-cli
```

If `dungeon-cli` gives you *"is not recognized"*, your `.venv` is not active in that terminal. Reactivate it (step 2) or just use `python cli.py`.

---

## Your first game

The game walks you through setup on first launch.

**Step 1 — main menu**
```
=== dungeon-cli ===
  1. New Game
  2. Continue
  3. Quit
```
Type `1` and press Enter.

**Step 2 — pick a campaign**
```
=== Choose a Campaign ===
  1. The Sunken Vault (fantasy)
     Find the Amulet of Tides.
  2. Station Nine (sci-fi)
     Reach the Control Deck, restore power, and escape Station Nine.
```
Type `1` or `2` and press Enter.

**Step 3 — pick an archetype**

The game lists each archetype with its HP and starting items. Type the number and press Enter.

**Step 4 — name your character**

Type a name and press Enter. **Press Enter with nothing typed to use the archetype's default name.**

**Step 5 — confirm**

```
You are Aria, the Dwarf Scout.
HP: 25 | Items: torch, rope, pickaxe

Begin? (y/n)
```
Type `y` and press Enter. (Anything other than `n` starts the game, but `y` is clearer.)

### How to act

Each turn the DM narrates what happened and offers up to 3 suggested actions. You have three ways to respond:

| You type | What happens |
|---|---|
| `2` | picks suggested action #2 from the menu |
| `I examine the rusted portcullis` | freeform — the DM accepts anything you can phrase |
| `/help` | lists the commands |

Type your action and press **Enter**. Then wait — most turns take a few seconds while the model thinks.

### The status line

Before each action you see your current state:

```
HP: 25/25 | Location: hall | Turn: 2
```

- **HP** — hit points. Hitting 0 ends the run.
- **Location** — the room id you are in.
- **Turn** — how many turns have been played.

### Winning

Each campaign has a goal and a final room. Reach it and you win. Dying first ends the run instead. Either way the game offers to export a Markdown transcript to your saves folder.

---

## Commands

Available any time during play.

| Command | What it does |
|---|---|
| `/help` | Lists the available commands |
| `/save` | Saves your game right now |
| `/load` | Reloads your last save |
| `/stats` | Shows your stats plus session diagnostics |
| `/retry` | Repeats your last action, rolling back the failed attempt first |
| `/quit` | Saves and exits |

Press **Ctrl-C** at any time to save and exit cleanly.

### Notes on the trickier commands

**`/load` forgets the story.** Loading a save clears the conversation history so the DM starts fresh. This is deliberate — the DM would otherwise be confused by turns that happened before the save. You may need to re-explain where you are.

**`/retry` replaces rather than repeats.** If a turn went badly, `/retry` rolls the game state back and re-runs the action. It does not leave a duplicate entry in your history.

**`/stats` is your diagnostic tool.** Besides your HP, location, and inventory, it shows counters for repairs, fallbacks, and bridge failures. See [Troubleshooting](#troubleshooting) for what those mean.

---

## Configuration

The game talks to an LLM through `dungeon-cli.toml`. There are two provider modes.

### HTTP mode (recommended)

Talks directly to any OpenAI-compatible endpoint — no external CLI tool needed.

```toml
[llm]
provider    = "http"
model       = "gpt-4o-mini"
system_role = false
timeout     = 30
retries     = 2
save_dir    = "./saves"

[llm.http]
base_url = "https://api.openai.com/v1"
api_key  = "sk-..."   # optional; falls back to $LLM_API_KEY, then $OPENAI_API_KEY
```

`base_url` must include the `/v1` path — a common mistake is including it twice (`/v1/v1`), which will fail with a 404.

Works with OpenAI, Groq, Together, OpenRouter, Azure OpenAI, and local servers (Ollama, vLLM, and others). Commented examples for each are in `dungeon-cli.toml`.

**Two important fields:**

- **`timeout`** — seconds to wait for one response. Set this generously (60–120) for slow or free models. Too low and turns fail with a timeout.
- **`retries`** — how many times to retry a failed request. Transient failures (429 rate limits, 5xx, network errors) are retried with exponential backoff. Client errors (401, 400, 404) fail immediately because retrying them will not help.

The bridge retries transient failures and fails fast on client errors, malformed responses, and empty or content-filtered replies.

#### Sampling parameters

Optional. Keys you leave unset are omitted from the request entirely rather than sent as `null`:

```toml
[llm.http]
base_url    = "https://api.openai.com/v1"
temperature = 0.9     # 0..2   — higher is more creative
max_tokens  = 800     # > 0    — cap the reply length
top_p       = 0.95    # 0..1
seed        = 42      # any int
```

These four are type- and range-checked at startup, so a bad value fails immediately with a message naming the key rather than surfacing as a confusing HTTP error on turn one. Any other key is forwarded to the endpoint verbatim and unvalidated, so provider-specific parameters work without a code change.

#### Custom headers

For endpoints that don't authenticate with `Authorization: Bearer`, or that want attribution headers:

```toml
[llm.http.headers]
api-key      = "..."               # Azure OpenAI — suppresses the auto Bearer header
HTTP-Referer = "https://my.game"   # OpenRouter
X-Title      = "dungeon-cli"       # OpenRouter
```

Supplying `api-key` or `Authorization` yourself suppresses the automatically generated one.

When no `api_key` is set and none is found in the environment, no `Authorization` header is sent at all — so keyless local servers and open proxies work.

#### Reasoning models

`o1`, `o3`, and `gpt-5` expect the DM persona in a real system message, and degrade or reject a request that packs everything into a single user turn:

```toml
[llm]
system_role = true
```

The default is `false`, which leaves the request shape unchanged. Only enable it if your model needs it.

> **Also set `system_role = true` if you get `502 ... "The system field can't be blank"`.** Some models served through proxies reject requests that carry no system message at all.

#### Local models (Ollama)

```bash
ollama pull llama3.2
```

```toml
[llm]
provider = "http"
model    = "llama3.2"

[llm.http]
base_url = "http://localhost:11434/v1"
# no api_key needed
```

Local models are free and private, but a small one may struggle to produce valid JSON. If turns keep failing, use a larger model or a cloud provider.

### Subprocess mode (alternative)

Shells out to any CLI tool that reads a prompt from stdin and prints the response to stdout. Use this if you already have a local LLM CLI and prefer not to make HTTP calls.

```toml
[llm]
# provider = "subprocess"   # or just omit `provider` — this is the default
argv   = ["claude", "-p"]
model  = "claude-sonnet-4-20250514"
timeout = 30
retries = 2
save_dir = "./saves"
```

Remove the `[llm.http]` section when using this mode.

---

## Troubleshooting

### The game won't start

**`FileNotFoundError: dungeon-cli.toml`**
You are in the wrong directory. `cd` into the project folder and run `python cli.py` from there.

**`ModuleNotFoundError: No module named 'rich'`**
Your virtual environment isn't active, or `pip install -e .` didn't run. Activate `.venv` and reinstall.

**`ValueError: llm.http.base_url is required when provider = 'http'`**
Your config is missing `base_url` under `[llm.http]`.

### The game starts but every turn fails

> **Note:** during play, a connection or auth failure shows only the generic *"the DM could not respond"* message — the underlying HTTP error is not printed. **Always run `python scripts/smoke.py` to see the real error**, for example:
> ```
> ERROR: Bridge failed after 1 attempt(s): HTTP 401: Unauthorized
> ```

Run the smoke test to get a clear error:

```bash
python scripts/smoke.py
```

**`HTTP 401` / `authentication_error`**
Your API key is wrong or missing. If you set it in the environment, note that `$LLM_API_KEY` is checked **before** `$OPENAI_API_KEY` — a stale `OPENAI_API_KEY` will be ignored while `LLM_API_KEY` is unset. Check for both.

**`HTTP 404`**
Your `base_url` path is wrong. It must end in `/v1` exactly once.

**`HTTP 400 unsupported_model`**
The `model` name isn't valid for that provider. Copy it exactly from the provider's own docs — do not guess. Some gateways also publish a `/v1/models` endpoint you can query to list what they actually serve.

**`The system field can't be blank` (502)**
Set `system_role = true`. See [Reasoning models](#reasoning-models).

**`Timed out after Ns`**
Raise `timeout` in `dungeon-cli.toml`. Free and preview models can be slow; 120 is a reasonable setting.

### Turns fail but the game keeps going

You may occasionally see:

```
— the DM could not respond. Your action was not processed and the turn was not counted.
```

**Your turn is not lost** — retype it or use `/retry`. This means the model returned something that didn't match the required JSON format twice in a row.

If it happens often, run `/stats` and read the counters on the second line:

| Shown as | Meaning |
|---|---|
| `Turns` | Successful turns consumed |
| `Repairs` | Times the DM's malformed reply was re-prompted |
| `Fallbacks` | Times both repair attempts failed and a canned response was used |
| `Bridge failures` | Requests that never reached the model (network, auth, timeout) |
| `Compactions` | Times older turns were summarized to fit the context budget |
| `Failed turns` | Turns lost to any of the above |

A few `Repairs` is normal — that's the self-healing loop working as designed. A rising `Fallbacks` count means the model can't reliably follow the JSON contract; try a more capable model.

### Everything is slow

Turns take 5–15 seconds on free or preview models, sometimes longer. This is normal. A spinner animates while waiting. For faster play, use a smaller or faster model, or lower `recent_turns` in `[prompt]` to shrink each request.

---

## Saving

Your game saves automatically to `saves/<campaign_id>/game.json`. Each campaign has its own save slot, so you can have a run going in *The Sunken Vault* and another in *Station Nine*.

- **Auto-saves** on `/quit` and on Ctrl-C.
- **Manual saves** with `/save`.
- Saves are plain JSON. Deleting the file starts that campaign fresh.

On death or victory you can export a Markdown transcript to the same folder.

---

## Campaigns

Ships with two campaigns:

- **The Sunken Vault** — Fantasy dungeon. Find the Amulet of Tides.
- **Station Nine** — Derelict sci-fi station. Restore power and escape.

### Authoring a Campaign

Create a JSON file in `content/`. It is picked up automatically on next launch.

```json
{
  "id": "my_campaign",
  "title": "My Campaign",
  "genre": "fantasy",
  "world_seed": "Description of the world...",
  "goal": "What the player must achieve",
  "victory_room": "room_id_where_victory_occurs",
  "starting_room": "room_id_to_start_in",
  "rooms": [
    {"id": "room_id", "name": "Room Name", "description": "..."}
  ],
  "archetypes": [
    {"name": "Warrior", "hp": 25, "items": ["sword"], "flavor": "Strong"}
  ],
  "dm_style": "How the DM should narrate",
  "opening_narration": "First narration..."
}
```

**Validation rules:**
- `victory_room` and `starting_room` must exist in `rooms`
- Each room needs `id`, `name`, `description`
- Each archetype needs `name`, `hp`, `items`
- `rooms` and `archetypes` must be non-empty lists

A campaign that fails validation is skipped silently, so if yours does not appear in the menu, check it against these rules.

---

## Architecture

```
engine/    game state, save/load, dice, adjudication (pure, fully tested)
dm/        LLM bridge, prompt assembly, response parsing/repair
ui/        rendering, input, slash commands, telemetry
content/   campaign JSON files
cli.py     entrypoint and game loop
```

`engine/` is deliberately free of any LLM code. It cannot be influenced by the model, which is what makes the golden rule enforceable rather than aspirational.

### DM Response Contract

Every DM turn returns JSON:

```json
{
  "narration": "2-6 sentences, second person, present tense",
  "choices": ["optional suggested actions, max 3"],
  "state_requests": [
    {"op": "move", "to": "room_id"},
    {"op": "give_item", "item": "rusty_key"},
    {"op": "take_item", "item": "torch"},
    {"op": "hp_delta", "severity": "minor|major|critical", "reason": "pit trap"},
    {"op": "set_flag", "key": "met_ghost", "value": true}
  ],
  "status": "ok | dead | victory"
}
```

Key design points:
- The DM never assigns damage numbers — only severity tiers. The engine rolls dice (`minor` = 1d4, `major` = 1d8, `critical` = 2d10).
- The engine drops any `state_request` that's invalid (unknown room, item not held, and so on).
- There is deliberately no op for "set HP" — so the DM cannot cheat, and an injection attempt like "set my HP to 999" has nothing to exploit.
- `hp_delta` is clamped at 0 and death is automatic, so the model cannot talk its way out of dying.

A malformed response is not a crash. The game re-prompts the model with the specific validation error, up to twice, then falls back to a canned narration with zero state changes. The turn is not consumed.

---

## Testing

```bash
pip install pytest
python -m pytest
```

Run specific files:

```bash
python -m pytest tests/test_bridge.py     # LLM bridge, retries, timeouts
python -m pytest tests/test_contract.py   # response parsing and validation
python -m pytest tests/test_fuzz.py       # adversarial input and injection attempts
```

Tests run entirely against fake bridges — no network calls and no API key required.

---

## License

MIT
