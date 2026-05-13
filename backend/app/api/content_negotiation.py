"""Tiny content-negotiation helper for the JSON-LD wrappers.

Each primary read endpoint (entity, edge, episode, ontology, graph)
takes an `Annotated[bool, Depends(accept_jsonld)]` parameter and
branches on the result. False → existing plain JSON; True → JSON-LD.

Two signals trigger JSON-LD:
1. ``Accept`` header lists ``application/ld+json`` (with positive q).
2. The request has ``?format=jsonld`` (lets curl users opt in without
   fiddling with headers, and lets browsers exercise the path).
"""
from __future__ import annotations

import re

from fastapi import Request

_LD_MEDIA = "application/ld+json"
# Match ``application/ld+json`` with optional q-weight; tolerate
# whitespace and trailing parameters.
_LD_RE = re.compile(
    r"application/ld\+json(?:\s*;\s*q\s*=\s*([0-9.]+))?",
    re.IGNORECASE,
)


def accept_jsonld(request: Request) -> bool:
    if request.query_params.get("format", "").lower() == "jsonld":
        return True
    accept = request.headers.get("accept", "")
    if not accept:
        return False
    match = _LD_RE.search(accept)
    if not match:
        return False
    q_raw = match.group(1)
    if q_raw is None:
        return True
    try:
        return float(q_raw) > 0
    except ValueError:
        return False
