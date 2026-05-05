"""Hand-rolled XXE / billion-laughs guard for XML parsing.

Python's stdlib ``xml.etree.ElementTree`` honours internal DTD entity
expansion, which exposes us to billion-laughs DoS when parsing
externally-sourced XML (``es_systems.cfg``, ``es_input.cfg``,
``gamelist.xml``). This module wraps ``ET.parse`` with a pre-flight
check that rejects any document containing a DOCTYPE or ENTITY
declaration in its prolog.

RetroBat / EmulationStation XML files do not contain DTDs in normal
operation; refusing to parse them when one is present is a strict
security posture rather than a feature loss. If a real RetroBat
release ever ships a DTD-bearing config, the rejection surfaces a
clear error rather than silently expanding 2^28 entity references.

Audit reference: M4 (XXE/billion-laughs DoS) from the v0.1.1 audit.
The user opted for a hand-rolled guard rather than the ``defusedxml``
dep — this module is the entire implementation.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

# Inspect this many bytes from the file head when sniffing for DTDs.
# DOCTYPE / ENTITY declarations live in the prolog before the root
# element, which is always near the file start. 64 KiB is generous —
# real ES XML prologs are <1 KiB.
_PROLOG_SNIFF_BYTES = 64 * 1024


class XMLSecurityError(ValueError):
    """Raised when XML contains constructs that could be used for DoS."""


def safe_parse(path: Path | str) -> ET.ElementTree:
    """``ET.parse(path)`` with a pre-flight DTD/ENTITY guard.

    Raises :class:`XMLSecurityError` if the file contains DOCTYPE or
    ENTITY declarations. Otherwise behaves exactly like ``ET.parse`` —
    same return type, same exceptions on malformed XML / missing file.
    """
    p = Path(path)
    try:
        with p.open("rb") as f:
            head = f.read(_PROLOG_SNIFF_BYTES)
    except OSError:
        # File missing or unreadable — let ET.parse surface the
        # canonical error (FileNotFoundError, PermissionError, etc.).
        return ET.parse(p)
    # Case-insensitive DTD check on the prolog. The lowercase + bytes
    # match keeps this allocation-light and Unicode-safe.
    head_lower = head.lower()
    if b"<!doctype" in head_lower or b"<!entity" in head_lower:
        raise XMLSecurityError(
            f"refusing XML with DTD/ENTITY declaration in {p}: "
            f"could be a billion-laughs DoS attack"
        )
    return ET.parse(p)


__all__ = ["safe_parse", "XMLSecurityError"]
