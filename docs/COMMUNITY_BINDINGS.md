# Community bindings — submission contract (v0.1.5 MVP)

This document describes the JSON schema and submission flow for
community-contributed bindings in RetroControlMapper v0.1.5. The
**v0.1.5 ship is the MVP**: GUI builds a pre-filled GitHub Issue,
user submits, project owner triages into the shipped bindings_db.
v0.1.6 will add the full OAuth-backed PR flow against a dedicated
companion repo (`RetroControlMapper-community-bindings`) with
GitHub device-code authentication and CI-validated automerge.

This file is the **stability contract** — what fields contributors
should expect to be honored across versions vs internal-only fields
we may rename.

## How submission works in v0.1.5

1. User loads a game profile in the GUI.
2. Either:
   - The bundled bindings_db has suggestions → user reviews / applies / edits
   - User drops a PDF of the manual → backend pypdf extraction surfaces bindings
   - User maps controls manually
3. User ticks **"Submit my approved bindings to the community DB on Save Profile"**
   in the Suggestions popover footer.
4. On Save Profile, the GUI:
   - Saves the profile to disk normally (`profiles/<system>/<rom>.yaml`)
   - Mirrors the bindings to `data/bindings_user/<system>.json`
   - Queues a local submission record at
     `data/bindings_user_submission_queue/<ts>_<sys>_<rom>.json`
   - Opens a pre-filled **GitHub Issue** in the user's browser with the
     binding JSON in the body and labels `community-binding,bindings-submission`
5. The user submits the issue (no GitHub auth needed beyond signing in).
6. The project maintainer triages: if the bindings look reasonable, they
   merge them into the next release's `data/bindings_db/<system>.json`.

In v0.1.6 this gets replaced with a true PR flow:
companion repo `RetroControlMapper-community-bindings`, GitHub OAuth
device-code flow for auth, automated merge + CI validation, and a
periodic merged-DB release asset for live updates.

## Submission JSON schema

The JSON inside the submission Issue body looks like:

```json
{
  "system_id": "snes",
  "rom_name":  "Earthbound",
  "bindings": [
    {
      "button":     "a",
      "action":     "RETROK_RETURN",
      "confidence": "high",
      "matched_by": "user",
      "extractor":  "rbcf-gui-v0.1.5"
    }
  ]
}
```

### Field stability contract

**Contract fields** — guaranteed stable across v0.1.x. We will never
rename or repurpose these. Contributors should rely on them.

| Field | Type | Meaning |
|---|---|---|
| `system_id` | string (lowercase) | RetroBat system identifier — `snes`, `c64`, `psx`, etc. Must match a system in `data/bindings_db/`. |
| `rom_name` | string | Game title. Best-effort match against the user's ROM stem; normalised by `bindings_lookup._normalise()` for lookup. |
| `bindings` | array of binding objects | Required, may be empty. |
| `bindings[].button` | string (lowercase) | Pad button. One of: `a`, `b`, `x`, `y`, `l1`, `r1`, `l2`, `r2`, `l3`, `r3`, `select`, `start`, `up`, `down`, `left`, `right`, `home`. |
| `bindings[].action` | string | Description of what the button does. For keystroke mappings, the `RETROK_*` constant. For action descriptions (controls.dat-style), free text like `"Light Punch"`. |
| `bindings[].confidence` | enum: `high`, `medium`, `low` | Submitter's confidence. Defaults to `medium`. |
| `bindings[].matched_by` | string | One of: `user`, `manual_extract`, `llm`, `controls.dat`. v0.1.5 GUI submissions emit `matched_by: "user"` exclusively (the other values come from records that originate in the bundled DB extractors and aren't surfaced as submissions yet — but consumers may encounter them in merged community contributions of legacy data, so the vocabulary is fixed). |

**Internal fields** — we may rename or restructure these without
warning. Contributors should not rely on them.

| Field | Why internal |
|---|---|
| `bindings[].extractor` | Provenance tag for analytics (e.g. `llm-qwen2.5-7b`, `rbcf-gui-v0.1.5`, `manual-pass-2`). Format may change as new extractors land. |
| `bindings[].source_quote` | The verbatim quote from the manual that supports the binding. Validators check it; format may evolve. |
| `bindings[].protocol_version` | LLM-protocol versioning for migration tooling. Likely getting stripped (BW-7). |
| `extra.*` | All metadata under `extra` is best-effort diagnostic info, not part of the contract. |

## Validation rules applied on triage

The project maintainer triaging a submission applies these checks
(automated in v0.1.6 via CI):

1. **`system_id` is one of the 62 systems** in `data/bindings_db/`.
2. **`button` is in the pad-button vocabulary** for the system.
3. **`action` is non-empty + not obviously bogus** (length 2-80,
   ≥50% alphabetic characters, no script-injection characters).
4. **No duplicates** — `(button, action.lower())` is unique per game.
5. **No conflicting same-button bindings** — if `A → RETROK_X` is
   already in the bundled DB and the submission says `A → RETROK_Y`,
   the submission is queued for manual review with the conflict
   flagged in the Issue.

Submissions that fail (1) or (2) get a templated reply pointing the
contributor at the system/button vocabulary docs. Submissions that
fail (3)-(5) may still be accepted after the maintainer cleans them up.

## Per-system file format

The `data/bindings_db/<system>.json` files merged from submissions
follow this shape:

```json
{
  "system_id": "snes",
  "schema_version": 1,
  "extracted_at": "2026-05-16T08:00:00Z",
  "extractor_version": "0.1.5",
  "stats": {
    "total_games": 339,
    "with_bindings": 234,
    "total_bindings": 526
  },
  "games": {
    "earthbound": {
      "title": "Earthbound",
      "bindings": [
        { "button": "a", "action": "RETROK_RETURN", ... }
      ]
    }
  }
}
```

The `games` keys are normalised forms produced by
`bindings_lookup._candidate_keys()` — generally `lower-case + strip
punctuation + condense whitespace`. The `title` field inside each
game record preserves the original casing for display.

## Honored attribution

Bindings submitted via the community flow carry the contributor's
GitHub handle into the `contributors` field once merged:

```json
"games": {
  "earthbound": {
    "title": "Earthbound",
    "contributors": ["@username"],
    "bindings": [...]
  }
}
```

The GUI shows a small "by @username" annotation on bindings sourced
from community contributions, when available.

## Privacy

No telemetry is collected from submitters beyond what GitHub itself
captures from the Issue creation. The local queue file at
`data/bindings_user_submission_queue/` lives on the user's machine
only. Nothing is uploaded automatically — the user always reviews
and submits the GitHub Issue manually.
