"""Classify news items with a small Claude model instead of a regex.

Items (Wikipedia Current Events leaf items with their parent context; NYT A1
headline + abstract) are sent 25 per request with a fixed rubric and a JSON
schema. Labels are cached by text hash in docs/data/llm_labels.jsonl, so each
item is billed once, ever. Large backlogs go through the Message Batches API
(half price, asynchronous); small daily increments run synchronously.

Usage:
  ai-news-share llm            # ingest any finished batch, then label what is missing
  ai-news-share llm --status   # show batch state and coverage
Needs ANTHROPIC_API_KEY (environment or .env). Model: AI_NEWS_LLM_MODEL or claude-haiku-4-5.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

import anthropic
from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
from anthropic.types.messages.batch_create_params import Request

from . import labels
from .config import env
from .topics import TOPICS

log = logging.getLogger(__name__)

MODEL = env("AI_NEWS_LLM_MODEL") or "claude-haiku-4-5"
PER_REQUEST = 25
SYNC_LIMIT = 500  # more pending items than this -> Batches API
STATE = "llm_batch_state.json"

SYSTEM = """You label short news items by topic. For each item decide, independently, whether the item is substantially ABOUT each topic below. A passing mention does not count; the topic must be a main subject of the item.

ai: artificial intelligence - AI systems, models, chatbots, agents; AI companies and labs and their products, funding, leadership; chips, compute and data centers built for AI; AI policy, regulation, safety, risk; AI-generated media and deepfakes; AI's effects on work, education, science, warfare, culture. Not: ordinary software, social media, robots or automation without an AI angle, self-driving cars unless AI itself is the focus.

covid: the COVID-19 pandemic - cases, deaths, variants, testing, lockdowns and restrictions, covid vaccines, and economic or political consequences explicitly attributed to the pandemic. Not other diseases.

climate: climate change and global warming - emissions and climate policy, climate negotiations, climate protests, decarbonisation, and extreme weather or disasters explicitly linked to climate change. Not weather or disasters with no climate framing.

Items are given as "[i] text", where text may start with the parent headings the item was filed under (separated by " > "). Return one label object per item, in order, with the same i."""

SCHEMA = {
    "type": "object",
    "properties": {
        "labels": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"i": {"type": "integer"}, "ai": {"type": "boolean"}, "covid": {"type": "boolean"}, "climate": {"type": "boolean"}},
                "required": ["i", "ai", "covid", "climate"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["labels"],
    "additionalProperties": False,
}


def _params(chunk: list[tuple[str, str]]) -> dict:
    body = "\n".join(f"[{i}] {text[:600]}" for i, (_, text) in enumerate(chunk))
    return dict(
        model=MODEL,
        max_tokens=1500,
        system=[{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": body}],
        output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
    )


def _parse(chunk: list[tuple[str, str]], text: str) -> list[dict]:
    out = json.loads(text).get("labels", [])
    rows = []
    for lab in out:
        i = lab.get("i")
        if isinstance(i, int) and 0 <= i < len(chunk):
            key, t = chunk[i]
            rows.append({"key": key, **{k: bool(lab.get(k)) for k in TOPICS}, "model": MODEL, "text": t[:160]})
    return rows


# ------------------------------------------------------------ item texts ---
def wiki_text(it: dict) -> str:
    return " > ".join(x for x in (it.get("context"), it.get("text")) if x)


def nyt_text(it: dict) -> str:
    return f"{it.get('headline', '')} {it.get('abstract', '')}".strip()


def collect_texts(data_dir: Path) -> dict[str, str]:
    texts: dict[str, str] = {}
    p = data_dir / "wiki_items.jsonl"
    if p.exists():
        for line in p.read_text().splitlines():
            t = wiki_text(json.loads(line))
            if t:
                texts[labels.key_of(t)] = t
    p = data_dir / "nyt_items.jsonl"
    if p.exists():
        from .nyt import is_front_page

        for line in p.read_text().splitlines():
            it = json.loads(line)
            if is_front_page(it):
                t = nyt_text(it)
                if t:
                    texts[labels.key_of(t)] = t
    return texts


def pending(data_dir: Path) -> list[tuple[str, str]]:
    have = labels.load(data_dir)
    return [(k, t) for k, t in collect_texts(data_dir).items() if k not in have]


def _chunks(xs, n):
    for i in range(0, len(xs), n):
        yield xs[i : i + n]


# ------------------------------------------------------------ sync path ---
def classify_sync(client: anthropic.Anthropic, data_dir: Path, items: list[tuple[str, str]]) -> int:
    n = 0
    for chunk in _chunks(items, PER_REQUEST):
        try:
            resp = client.messages.create(**_params(chunk))
        except anthropic.RateLimitError as e:
            wait = int(e.response.headers.get("retry-after", "30"))
            log.warning("rate limited; sleeping %ss", wait)
            time.sleep(wait)
            resp = client.messages.create(**_params(chunk))
        if resp.stop_reason == "refusal":
            log.warning("refusal on a chunk; skipping %d items", len(chunk))
            continue
        text = next((b.text for b in resp.content if b.type == "text"), "")
        rows = _parse(chunk, text)
        labels.append(data_dir, rows)
        n += len(rows)
    return n


# ----------------------------------------------------------- batch path ---
def _state(data_dir: Path) -> dict:
    p = data_dir / STATE
    return json.loads(p.read_text()) if p.exists() else {"batches": []}


def _save_state(data_dir: Path, st: dict) -> None:
    (data_dir / STATE).write_text(json.dumps(st, indent=1))


def submit_batch(client: anthropic.Anthropic, data_dir: Path, items: list[tuple[str, str]]) -> str:
    chunks = list(_chunks(items, PER_REQUEST))
    requests = [Request(custom_id=f"c{i}", params=MessageCreateParamsNonStreaming(**_params(ch))) for i, ch in enumerate(chunks)]
    batch = client.messages.batches.create(requests=requests)
    st = _state(data_dir)
    st["batches"].append({"id": batch.id, "created": datetime.now(timezone.utc).isoformat(timespec="seconds"), "n_items": len(items), "chunks": {f"c{i}": ch for i, ch in enumerate(chunks)}, "done": False})
    _save_state(data_dir, st)
    log.info("submitted batch %s: %d requests, %d items", batch.id, len(requests), len(items))
    return batch.id


def collect_batches(client: anthropic.Anthropic, data_dir: Path) -> int:
    """Ingest results of any finished batch. Returns number of labels added."""
    st = _state(data_dir)
    added = 0
    for b in st["batches"]:
        if b["done"]:
            continue
        info = client.messages.batches.retrieve(b["id"])
        if info.processing_status != "ended":
            log.info("batch %s: %s (%s processing)", b["id"], info.processing_status, info.request_counts.processing)
            continue
        rows = []
        for r in client.messages.batches.results(b["id"]):
            chunk = [tuple(x) for x in b["chunks"].get(r.custom_id, [])]
            if r.result.type == "succeeded" and chunk:
                msg = r.result.message
                text = next((blk.text for blk in msg.content if blk.type == "text"), "")
                try:
                    rows.extend(_parse(chunk, text))
                except json.JSONDecodeError:
                    log.warning("batch %s %s: bad JSON", b["id"], r.custom_id)
            else:
                log.warning("batch %s %s: %s", b["id"], r.custom_id, r.result.type)
        labels.append(data_dir, rows)
        b["done"] = True
        b["chunks"] = {}  # no need to keep the texts around
        added += len(rows)
        log.info("batch %s: ingested %d labels", b["id"], len(rows))
    _save_state(data_dir, st)
    return added


def run(data_dir: Path, *, force_sync: bool = False) -> dict:
    key = env("ANTHROPIC_API_KEY")
    if not key:
        log.info("ANTHROPIC_API_KEY not set; skipping LLM labels")
        return {"skipped": True}
    client = anthropic.Anthropic(api_key=key)
    added = collect_batches(client, data_dir)
    todo = pending(data_dir)
    in_flight = any(not b["done"] for b in _state(data_dir)["batches"])
    result = {"ingested": added, "pending": len(todo), "in_flight": in_flight}
    if not todo or in_flight:
        return result
    if len(todo) <= SYNC_LIMIT or force_sync:
        result["labeled_sync"] = classify_sync(client, data_dir, todo)
    else:
        result["batch"] = submit_batch(client, data_dir, todo)
    return result


def status(data_dir: Path) -> dict:
    texts = collect_texts(data_dir)
    have = labels.load(data_dir)
    return {"items": len(texts), "labeled": sum(1 for k in texts if k in have), "batches": [{k: v for k, v in b.items() if k != "chunks"} for b in _state(data_dir)["batches"]]}
