"""
Hashing Utilities (Section 16)

Deterministic hashing for reproducibility:
- Hash of all prompts
- Hash of all solver inputs
- File content hashing
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def compute_hash(data: Any) -> str:
    """
    Compute deterministic SHA-256 hash of arbitrary data.

    Data is JSON-serialized with sorted keys for determinism.
    """
    if isinstance(data, str):
        payload = data
    elif isinstance(data, bytes):
        return hashlib.sha256(data).hexdigest()
    else:
        payload = json.dumps(data, sort_keys=True, default=str)

    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def hash_file(path: str | Path) -> str:
    """Compute SHA-256 hash of file contents."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()


def short_hash(data: Any, length: int = 16) -> str:
    """Compute a short hash (truncated)."""
    return compute_hash(data)[:length]
