# LLM Extraction Protocol

A contract between **the orchestrator** (Python code running on the
dev/build machine) and **the local LLM** (Qwen 2.5 3B via Ollama on
a separate LAN box). Designed for repeatable, high-precision
button-binding extraction from game manual OCR text.

This document is the source of truth. The implementation (`llm_extract.py`)
must match it. The LLM's system prompt is generated from it.

---

## Design tenets

1. **Verbatim or nothing.** Every binding MUST be backed by a `source_quote`
   pulled directly from the input. Hallucinations get filtered out at
   validation time.

2. **Closed-vocabulary buttons.** The orchestrator passes a per-system
   list of valid button names. The LLM MAY NOT invent new ones. Outputs
   referencing invalid buttons are rejected.

3. **Section-scoped input.** The orchestrator feeds ONLY the controls
   section (typically 300–1500 chars), never the whole manual. Smaller
   prompt = faster + higher precision.

4. **Self-grading.** The LLM declares confidence per binding
   (high/medium/low). The orchestrator can show medium/low results to
   users marked as suggestions.

5. **No prose responses.** JSON only. The orchestrator parses, validates,
   and rejects malformed responses with a single retry.

6. **Learnable.** Every rejection is logged with the failure mode. Over
   time we accumulate few-shot examples and refine the system prompt
   from those rejections.

---

## The system passport

Every call to the LLM includes a structured context bundle:

```json
{
  "system_id":     "snes",
  "system_name":   "Super Nintendo Entertainment System",
  "buttons":       ["a", "b", "x", "y", "l", "r", "start", "select",
                    "dpad_up", "dpad_down", "dpad_left", "dpad_right"],
  "era_hint":      "1991",
  "game_title":    "Super Mario World",
  "genre_hint":    "platformer"
}
```

`buttons` is the closed vocabulary. Anything outside this list is
rejected post-hoc.

---

## Canonical button namespace (per system)

The orchestrator owns this. The LLM only ever sees the subset relevant
to one extraction.

| System family | Buttons |
|---|---|
| **NES** | `a` `b` `start` `select` `dpad_{up,down,left,right}` |
| **SNES** | `a` `b` `x` `y` `l` `r` `start` `select` `dpad_*` |
| **N64** | `a` `b` `cup` `cdown` `cleft` `cright` `z` `l` `r` `start` `dpad_*` |
| **GameCube** | `a` `b` `x` `y` `z` `l` `r` `start` `cstick_*` `dpad_*` |
| **Genesis / Megadrive** | `a` `b` `c` `x` `y` `z` `start` `mode` `dpad_*` |
| **Saturn** | `a` `b` `c` `x` `y` `z` `l` `r` `start` `dpad_*` |
| **PSX** | `triangle` `circle` `cross` `square` `l1` `l2` `r1` `r2` `start` `select` `dpad_*` |
| **PS2** | PSX + `l3` `r3` `lstick_*` `rstick_*` |
| **Dreamcast** | `a` `b` `x` `y` `l_trig` `r_trig` `start` `dpad_*` `stick_*` |
| **Xbox / 360** | `a` `b` `x` `y` `lb` `rb` `lt` `rt` `start` `back` `dpad_*` `lstick_*` `rstick_*` |
| **Single-button (Atari/C64/Amiga/Amstrad/ZX)** | `fire` `dpad_*` |
| **Keyboard add-ons** | `key:f1` … `key:f12` `key:space` `key:enter` `key:esc` `key:tab` |

Direction tokens always resolve to `dpad_up/down/left/right` (not
`dpad_up_left` diagonals — those are emitted as TWO bindings sharing
the same action, matching DE-9 joystick electrical reality).

---

## The output schema (strict)

```json
{
  "bindings": [
    {
      "button":       "<one of the system's allowed buttons>",
      "action":       "<2-80 char concise action description>",
      "confidence":   "high | medium | low",
      "source_quote": "<verbatim substring of the input section text>"
    }
  ],
  "notes": "<optional one-line uncertainty flag, or empty>"
}
```

**Field rules:**

- `button` — MUST be in the passport's `buttons` array. Case-sensitive.
- `action` — title-cased verb phrase. 2-80 chars. No trailing punctuation.
- `confidence` — high if button:action is explicit in source; medium
  if inferred from "press X to Y" prose; low if uncertain.
- `source_quote` — verbatim substring of the input. Validator checks
  this exists in the section text. If absent, binding rejected.
- `notes` — free text, used for "OCR garbled on page 4, ignoring" style
  flags. Optional.

---

## The system prompt template

(Filled in by `llm_extract.build_prompt`.)

```
You are a video game manual control extractor. Read the controls
section below and output JSON mapping physical buttons to actions.

GAME:    {game_title}
SYSTEM:  {system_name} ({era_hint})
GENRE:   {genre_hint}

VALID BUTTONS (you MUST use only these names — no others):
{buttons_list}

RULES:
1. Output ONLY a JSON object. No prose before or after.
2. For each binding, copy a verbatim substring of the input text into
   "source_quote". If you cannot find a verbatim quote, do NOT include
   the binding.
3. Use button names exactly as written in VALID BUTTONS.
4. Single-button-joystick systems: "joystick button" = `fire`.
   Diagonal moves like "up and left" produce TWO bindings (dpad_up
   AND dpad_left) sharing the same action.
5. Combo / special-move descriptions (e.g. "down, down-forward, forward +
   Punch") are GAME MECHANICS, not bindings. Skip them.
6. Empty/garbage OCR text → return {"bindings": [], "notes": "..."}.
   Never fabricate.

OUTPUT SCHEMA:
{"bindings": [
   {"button": "<name>", "action": "<phrase>",
    "confidence": "high|medium|low",
    "source_quote": "<verbatim from input>"}],
 "notes": "<optional>"}

CONTROLS SECTION TEXT:
"""
{section_text}
"""

OUTPUT (JSON only):
```

---

## Validation pipeline

After receiving the LLM response, the orchestrator runs:

| Check | Failure action |
|---|---|
| Response is valid JSON | Retry once with "OUTPUT MUST BE VALID JSON" prefix; if still fails, reject |
| Top level has `bindings` array | Reject |
| Each `button` ∈ passport buttons | Drop that binding, log rejection |
| Each `action` is 2-80 chars, letter ratio ≥0.6 | Drop, log |
| `source_quote` appears in input section text (case-insensitive) | Drop, log (hallucination indicator) |
| No duplicate (button, action) pairs | Dedupe |
| `confidence` ∈ {high, medium, low} | Default to medium |

Surviving bindings get stamped with `extractor: "llm-qwen2.5-3b"` and
saved to the bindings DB.

---

## Rejection log

Every dropped binding gets appended to `data/llm_rejections.jsonl` (one
JSON record per line, gitignored). Schema:

```json
{
  "timestamp": "2026-05-12T19:00:00Z",
  "system_id": "snes",
  "game_title": "Super Mario World",
  "reason": "button_not_in_passport | source_quote_not_found | invalid_json | action_too_short | …",
  "binding": { /* the rejected output */ },
  "section_text_hash": "abc123…"
}
```

These records feed iterative prompt improvements:
- 100+ `source_quote_not_found` rejections → tighten the "verbatim or nothing" instruction.
- N rejections of the same button-name typo → add to a normalization map.
- High volume of empty extractions on a system → that system's prompts
  may need better few-shot examples.

---

## Learning loop (the few-shot memory)

`llm_memory.py` implements a persistent per-system example pool that
the model "learns" from across runs. We can't fine-tune Qwen 2.5 3B
in-place, so learning here means **prompt enrichment**: every
successful extraction becomes a candidate few-shot example for future
prompts from the same system.

### Storage

`data/llm_few_shot.json` (gitignored). Per-system pool with quality
scores, capped at `MAX_POOL_PER_SYSTEM = 20`. When the pool is full,
the lowest-quality example gets evicted for any new candidate that
outscores it.

### Quality score (0-10 composite)

| Component | Max | Source |
|---|---|---|
| Binding count (plateau at 6) | 4.0 | More patterns covered |
| Confidence-weighted avg | 4.0 | high=1.0, medium=0.6, low=0.3 |
| Validator pass rate | 2.0 | accepted / (accepted + rejected) |

Bindings must hit `MIN_BINDINGS_FOR_EXAMPLE = 3` to be considered at all.

### Selection strategy

The orchestrator pulls `DEFAULT_EXAMPLES_IN_PROMPT = 2` examples
per call. Selection:

1. Sort all examples by quality descending; take top 2×N.
2. Within that set, prefer least-recently-used (`selected_count`).
3. Increment `selected_count` for the chosen examples.

The rotation step is important — without it, the same 2 high-quality
examples would dominate every prompt and the model would overfit to
their phrasing.

### Speed compounding via Ollama prompt-cache

Ollama caches identical prompt prefixes between requests. The prompt
is structured so the SYSTEM-INVARIANT parts come first:

```
[System prompt — same for all SNES]      ← cached
[Generic one-shot example]                ← cached
[2 SNES-specific examples from pool]      ← cached (stable per system)
[NEW SECTION TEXT — varies per game]      ← only this is new
[Output: JSON]
```

During a batch run processing 100 SNES titles, the first call pays
full prompt-eval cost; subsequent calls reuse the cached prefix and
only re-evaluate the new section text. Typical speedup: 2-4× faster
inference per call within the same system batch.

### CLI

```
py llm_memory.py stats              # per-system pool sizes + scores
py llm_memory.py list snes          # show top examples for one system
py llm_memory.py dump-path          # where the JSON file lives
```

---

## Retry / fallback

- One automatic retry on malformed JSON.
- Two retries with progressively more strict prompt prefixes ("YOUR LAST
  RESPONSE WAS INVALID — JSON ONLY") for extreme cases.
- If still failing after retries, log to `llm_rejections.jsonl` with
  reason `persistent_failure` and skip the title. Orchestrator falls
  back to the regex pipeline output (if any).

---

## Versioning

Each LLM run stamps records with:
- `extractor: "llm-qwen2.5-3b"` (or whichever model)
- `protocol_version: "1.0"` (this document's version)
- `extracted_at: "<ISO timestamp>"`

When the protocol changes (new buttons, new rules), bump the version
and re-process via `--upgrade-below-version 1.1` etc., reusing the
existing infrastructure.

---

## Implementation reference

The Python implementation lives at `llm_extract.py`. The two should
move together — any time this protocol changes, the implementation's
prompt template and validators must too.
