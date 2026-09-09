"""LLM topic labels: a content-addressed cache shared by every source.

docs/data/llm_labels.jsonl has one line per distinct item text:
  {"key": sha1(text), "ai": bool, "covid": bool, "climate": bool, "model": "...", "text": "<first 160 chars>"}
Sources look labels up by text so a re-fetch or re-parse never re-bills.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .topics import TOPICS

FILE = "llm_labels.jsonl"
_cache: dict[str, dict] | None = None
_cache_path: Path | None = None


def key_of(text: str) -> str:
    return hashlib.sha1(" ".join(text.split()).lower().encode()).hexdigest()[:20]


def load(data_dir: Path) -> dict[str, dict]:
    global _cache, _cache_path
    p = data_dir / FILE
    if _cache is None or _cache_path != p:
        _cache, _cache_path = {}, p
        if p.exists():
            for line in p.read_text().splitlines():
                if line.strip():
                    r = json.loads(line)
                    _cache[r["key"]] = r
    return _cache


def append(data_dir: Path, rows: list[dict]) -> None:
    cache = load(data_dir)
    with (data_dir / FILE).open("a") as f:
        for r in rows:
            cache[r["key"]] = r
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def llm_topics(data_dir: Path, text: str) -> dict[str, bool] | None:
    r = load(data_dir).get(key_of(text))
    return {k: bool(r.get(k)) for k in TOPICS} if r else None


def add_llm_counts(row: dict, topics_llm: dict[str, bool] | None) -> None:
    """Accumulate LLM label counts into a daily row (n_llm = items that have labels)."""
    row.setdefault("n_llm", 0)
    for k in TOPICS:
        row.setdefault(f"{k}_llm", 0)
    if topics_llm:
        row["n_llm"] += 1
        for k in TOPICS:
            row[f"{k}_llm"] += int(topics_llm[k])
