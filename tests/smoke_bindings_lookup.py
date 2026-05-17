"""Pre-release smoke test for bindings_lookup → bindings_db end-to-end.

Why this exists: v0.1.5 shipped its headline feature (in-GUI bindings
suggestions) with 0% functionality because the bindings_lookup key
normaliser didn't match real ROM filenames. The DB bundled fine, the
API endpoint responded, but every lookup returned ``None``. v0.1.5.1
fixed the bug; this test ensures we never regress.

Run before every release:

    py tests/smoke_bindings_lookup.py

Exit code 0 = pass, non-zero = fail. Wired into ``build.ps1`` as a
pre-package step.

Why no pytest: project keeps dev deps minimal. A handful of asserts
with a small fixture list is enough; framework is overkill.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Run from anywhere — resolve project root from this file's location.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bindings_lookup import lookup  # noqa: E402

# (system_id, rom_filename, minimum_expected_bindings)
#
# Cases chosen so that:
#   - Each represents a different system family (c64, nes, snes, psx).
#   - ROM filenames are realistic, mixing punctuation that the
#     normaliser has to handle (apostrophes, "vs", "The" prefix, etc.).
#   - Minimum binding counts are conservative — set BELOW the
#     actual count at v0.1.6 ship so future small DB pruning doesn't
#     trip the test, but high enough that a "lookup returns None"
#     bug fails the assert.
CASES: list[tuple[str, str, int]] = [
    ('c64', 'Bruce Lee.crt', 3),
    ('c64', 'Turrican.crt', 3),
    ('c64', 'Wizball.crt', 3),
    ('c64', 'Shadow of the Beast.crt', 3),
    ('nes', 'Metroid.nes', 1),
    ('nes', 'Mega Man.nes', 1),
    ('snes', 'Super Mario World.smc', 1),
    ('snes', 'Earthbound.sfc', 1),
    ('psx', 'Crash Bandicoot.cue', 1),
]


def main() -> int:
    failures: list[str] = []
    for sys_id, rom, min_bindings in CASES:
        hit = lookup(sys_id, rom, include_online=False)
        if hit is None:
            failures.append(f"  {sys_id}/{rom}: lookup returned None")
            continue
        bindings = hit.get('bindings') or []
        if len(bindings) < min_bindings:
            failures.append(
                f"  {sys_id}/{rom}: got {len(bindings)} bindings, "
                f"expected >= {min_bindings}"
            )
            continue

    n = len(CASES)
    if failures:
        print(f"FAIL: {len(failures)} of {n} smoke cases regressed:")
        for f in failures:
            print(f)
        print()
        print("Recent suspect: bindings_lookup._candidate_keys or _match_db_key.")
        print("Run `py -c \"from bindings_lookup import lookup; "
              "print(lookup('c64', 'Bruce Lee.crt'))\"` to inspect live behaviour.")
        return 1

    print(f"OK: {n} of {n} bindings_lookup smoke cases passed.")
    return 0


if __name__ == '__main__':
    sys.exit(main())
