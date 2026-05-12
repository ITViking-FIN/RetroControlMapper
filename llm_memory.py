"""
LLM memory store — accumulates few-shot examples per system.

Since we can't fine-tune Qwen 2.5 3B in-place, "learning" here means
curating a growing library of known-good extractions and injecting
the best ones into future prompts as few-shot demonstrations. Two
mechanisms compound:

1. **Quality-scored example pool** — each successful extraction is a
   candidate for the system's example pool. Quality criteria:
     - 3+ bindings extracted (broader pattern coverage)
     - All bindings high/medium confidence (clean signal)
     - All bindings validator-passed (source_quote verified, button in
       passport, no duplicates)
     - Section text not already represented in the pool (dedupe by hash)

2. **Prompt-cache friendliness** — Ollama caches identical prompt
   prefixes across requests. Putting the system prompt + few-shot
   examples BEFORE the variable section text means subsequent extractions
   for the same system benefit from KV cache reuse → faster latency
   without changing the model.

## Public API

    from llm_memory import LLMMemory
    mem = LLMMemory()                              # loads data/llm_few_shot.json
    examples = mem.get_examples("snes", n=2)       # best 2 SNES examples
    mem.add_example("snes", section_text, output)  # offer for inclusion
    mem.save()                                     # persist to disk

## Storage

``data/llm_few_shot.json`` (gitignored — per-machine state). Structure:

```json
{
  "schema_version": 1,
  "updated_at": "2026-05-12T19:00:00Z",
  "systems": {
    "snes": {
      "examples": [
        {
          "id": "abc123...",            # sha1 of section_text
          "section_text": "...",
          "output": {"bindings": [...]},
          "quality_score": 8.5,         # composite score
          "binding_count": 5,
          "added_at": "...",
          "selected_count": 12          # how often it's been used in prompts
        }
      ],
      "stats": {
        "total_seen": 247,
        "total_added": 18,
        "total_rejected_as_examples": 229
      }
    }
  }
}
```

Pool size is capped per system (default 20). When full, lowest-quality
example gets evicted to make room for a better candidate.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
MEMORY_FILE = DATA_DIR / "llm_few_shot.json"

SCHEMA_VERSION = 1
MAX_POOL_PER_SYSTEM = 20         # cap examples per system
MIN_BINDINGS_FOR_EXAMPLE = 3     # below this, not example-worthy
DEFAULT_EXAMPLES_IN_PROMPT = 2   # how many to inject by default


# ============================================================
# Quality scoring
# ============================================================

def _quality_score(output: dict, validator_rejected: int = 0) -> float:
    """Composite 0-10 score. Higher = better example. Combines:
      - binding count (more diverse pattern coverage)
      - confidence distribution (prefer high > medium > low)
      - validator pass rate (no rejections is ideal)
    """
    bindings = output.get("bindings", []) or []
    n = len(bindings)
    if n == 0: return 0.0

    # Component 1: binding count up to ~6 plateaus
    count_score = min(n, 6) / 6 * 4.0     # max 4.0

    # Component 2: confidence weighting
    conf_weights = {"high": 1.0, "medium": 0.6, "low": 0.3}
    conf_sum = sum(conf_weights.get(b.get("confidence", "medium"), 0.6)
                   for b in bindings)
    conf_score = (conf_sum / n) * 4.0     # max 4.0

    # Component 3: validator pass rate (no rejections is good signal)
    total = n + validator_rejected
    pass_rate = n / total if total > 0 else 1.0
    val_score = pass_rate * 2.0            # max 2.0

    return round(count_score + conf_score + val_score, 2)


# ============================================================
# Example record
# ============================================================

@dataclass
class Example:
    id:              str                  # sha1 of normalised section_text
    section_text:    str
    output:          dict                 # {"bindings": [...]}
    quality_score:   float
    binding_count:   int
    added_at:        str
    selected_count:  int = 0              # incremented each time prompt uses it
    metadata:        dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Example":
        return cls(
            id=d["id"], section_text=d["section_text"],
            output=d["output"], quality_score=float(d.get("quality_score", 0)),
            binding_count=int(d.get("binding_count", 0)),
            added_at=d.get("added_at", ""),
            selected_count=int(d.get("selected_count", 0)),
            metadata=d.get("metadata", {}),
        )


def _section_id(section_text: str) -> str:
    """Stable id from normalised whitespace. So two near-identical
    sections (one with extra spaces) collide as the same example."""
    import re
    norm = re.sub(r"\s+", " ", section_text.strip()).lower()
    return hashlib.sha1(norm.encode("utf-8")).hexdigest()[:16]


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# ============================================================
# Memory store
# ============================================================

class LLMMemory:
    """Persistent few-shot example library, keyed by system_id."""

    def __init__(self, path: Path = MEMORY_FILE):
        self.path = path
        self.data: dict = {
            "schema_version": SCHEMA_VERSION,
            "updated_at": None,
            "systems": {},
        }
        self._load()

    def _load(self):
        if not self.path.exists(): return
        try:
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.data["updated_at"] = _now_iso()
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.data, indent=2, ensure_ascii=False),
                       encoding="utf-8")
        tmp.replace(self.path)

    def _system_block(self, system_id: str) -> dict:
        sys_block = self.data["systems"].get(system_id)
        if sys_block is None:
            sys_block = {
                "examples": [],
                "stats": {
                    "total_seen": 0, "total_added": 0,
                    "total_rejected_as_examples": 0,
                },
            }
            self.data["systems"][system_id] = sys_block
        return sys_block

    # --------------------------------------------------------
    # Lookup
    # --------------------------------------------------------

    def get_examples(self, system_id: str,
                     n: int = DEFAULT_EXAMPLES_IN_PROMPT,
                     rotate: bool = True) -> list[Example]:
        """Return the top N examples for this system. With rotate=True,
        the *least recently used* high-quality examples are returned —
        diversifies what the LLM sees, prevents one example from
        dominating and the model overfitting to it."""
        sys_block = self.data["systems"].get(system_id)
        if not sys_block: return []
        examples = [Example.from_dict(e) for e in sys_block.get("examples", [])]
        if not examples: return []

        # Sort by quality first, then by least-used (rotation)
        if rotate:
            # Take top-quality 2N, then within those pick least-used N
            top = sorted(examples, key=lambda e: -e.quality_score)[:n * 2]
            top.sort(key=lambda e: (e.selected_count, -e.quality_score))
            chosen = top[:n]
        else:
            chosen = sorted(examples, key=lambda e: -e.quality_score)[:n]

        # Mark them as used (in-memory; caller can save)
        used_ids = {e.id for e in chosen}
        for d in sys_block["examples"]:
            if d["id"] in used_ids:
                d["selected_count"] = int(d.get("selected_count", 0)) + 1
        return chosen

    # --------------------------------------------------------
    # Insertion
    # --------------------------------------------------------

    def consider(self, system_id: str, section_text: str,
                 output: dict, validator_rejected: int = 0) -> tuple[bool, str]:
        """Offer an extraction result for inclusion in the example pool.
        Returns (added, reason).

        Quality gate: extraction must clear MIN_BINDINGS_FOR_EXAMPLE,
        must not duplicate an existing example, and if the pool is at
        capacity must outscore the weakest current resident."""
        sys_block = self._system_block(system_id)
        sys_block["stats"]["total_seen"] += 1

        bindings = output.get("bindings", []) or []
        if len(bindings) < MIN_BINDINGS_FOR_EXAMPLE:
            sys_block["stats"]["total_rejected_as_examples"] += 1
            return False, f"too few bindings ({len(bindings)} < {MIN_BINDINGS_FOR_EXAMPLE})"

        eid = _section_id(section_text)
        existing_ids = {e["id"] for e in sys_block["examples"]}
        if eid in existing_ids:
            sys_block["stats"]["total_rejected_as_examples"] += 1
            return False, "duplicate section_text"

        score = _quality_score(output, validator_rejected)
        new_ex = Example(
            id=eid, section_text=section_text, output=output,
            quality_score=score, binding_count=len(bindings),
            added_at=_now_iso(),
        )

        # Pool not full → add directly
        if len(sys_block["examples"]) < MAX_POOL_PER_SYSTEM:
            sys_block["examples"].append(new_ex.to_dict())
            sys_block["stats"]["total_added"] += 1
            return True, f"added (score={score})"

        # Pool full → evict weakest IF new is stronger
        weakest_idx = min(range(len(sys_block["examples"])),
                          key=lambda i: sys_block["examples"][i]
                                       .get("quality_score", 0))
        weakest = sys_block["examples"][weakest_idx]
        if score > float(weakest.get("quality_score", 0)):
            sys_block["examples"][weakest_idx] = new_ex.to_dict()
            sys_block["stats"]["total_added"] += 1
            return True, (f"evicted weaker example (score {weakest.get('quality_score', 0)}) "
                          f"for new (score {score})")
        sys_block["stats"]["total_rejected_as_examples"] += 1
        return False, (f"pool full; score {score} doesn't beat weakest "
                       f"{weakest.get('quality_score', 0)}")

    # --------------------------------------------------------
    # Diagnostics
    # --------------------------------------------------------

    def stats(self) -> dict:
        """Per-system summary. Useful for the CLI."""
        out = {}
        for sid, block in self.data.get("systems", {}).items():
            examples = block.get("examples", [])
            scores = [float(e.get("quality_score", 0)) for e in examples]
            out[sid] = {
                "pool_size":    len(examples),
                "max_score":    round(max(scores), 2) if scores else 0,
                "min_score":    round(min(scores), 2) if scores else 0,
                "avg_score":    round(sum(scores) / len(scores), 2) if scores else 0,
                "stats":        block.get("stats", {}),
            }
        return out


# ============================================================
# Prompt-fragment formatter
# ============================================================

def format_examples_for_prompt(examples: list[Example]) -> str:
    """Render a list of Example records as a prompt fragment.
    Returns empty string for no examples (caller can decide to use
    the generic one-shot in build_prompt instead)."""
    if not examples: return ""
    parts = ["PRIOR SUCCESSFUL EXTRACTIONS FROM THIS SYSTEM (study these "
             "patterns, then apply the same approach to the new input):"]
    for i, ex in enumerate(examples, 1):
        parts.append(f"\nExample {i}:")
        parts.append(f"Input:\n\"\"\"\n{ex.section_text[:600]}\n\"\"\"")
        parts.append(f"Correct output:\n{json.dumps(ex.output, ensure_ascii=False)}")
    return "\n".join(parts) + "\n"


# ============================================================
# CLI
# ============================================================

def _main():
    import argparse
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=False)
    sub.add_parser("stats", help="Per-system pool stats.")
    L = sub.add_parser("list", help="List examples for a system.")
    L.add_argument("system_id")
    L.add_argument("--limit", type=int, default=5)
    sub.add_parser("dump-path", help="Print the memory file path.")
    args = ap.parse_args()

    if args.cmd is None:
        ap.print_help(); return

    mem = LLMMemory()

    if args.cmd == "stats":
        s = mem.stats()
        if not s:
            print("(no examples yet — memory pool is empty)")
            return
        print(f"{'system':<14} {'pool':>5} {'avg':>6} {'min':>6} {'max':>6}  added/seen")
        for sid, info in sorted(s.items()):
            seen = info["stats"]["total_seen"]
            added = info["stats"]["total_added"]
            print(f"{sid:<14} {info['pool_size']:>5} {info['avg_score']:>6} "
                  f"{info['min_score']:>6} {info['max_score']:>6}  {added}/{seen}")
        return

    if args.cmd == "list":
        sys_block = mem.data["systems"].get(args.system_id)
        if not sys_block or not sys_block.get("examples"):
            print(f"(no examples for {args.system_id})")
            return
        examples = sorted(sys_block["examples"],
                          key=lambda e: -e.get("quality_score", 0))
        for i, e in enumerate(examples[:args.limit], 1):
            print(f"\n=== Example {i} (score {e.get('quality_score')}, "
                  f"{e.get('binding_count')} bindings, "
                  f"used {e.get('selected_count', 0)}×) ===")
            print(f"Added: {e.get('added_at')}")
            print(f"Section: {e['section_text'][:200]!r}")
            print(f"Bindings:")
            for b in e["output"].get("bindings", [])[:5]:
                print(f"  {b.get('button'):>10} -> {b.get('action')}  [{b.get('confidence')}]")
        return

    if args.cmd == "dump-path":
        print(mem.path)
        return


if __name__ == "__main__":
    _main()
