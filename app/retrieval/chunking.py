"""Chunking strategies. Week 1 baseline = fixed-size chunks; Week 2 (step 2.2) adds clause/heading-aware variants."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "data" / "processed" / "corpus_v1.jsonl"
WORDS_PER_TOKEN = 0.75   # rough English average; 512 tokens ~ 384 words


@dataclass
class Chunk:
    chunk_id: str
    doc_id: str
    seq: int
    text: str
    vendor_id: str | None
    slice: str
    title: str


def load_corpus(path: Path = CORPUS) -> list[dict]:
    return [json.loads(l) for l in open(path)]


def fixed_chunks(doc: dict, size_tokens: int = 512, overlap_tokens: int = 64) -> list[Chunk]:
    """Naive baseline: split on whitespace into ~size_tokens windows with overlap. No title, no structure."""
    words = doc["text"].split()
    size = max(1, int(size_tokens * WORDS_PER_TOKEN))
    step = max(1, size - int(overlap_tokens * WORDS_PER_TOKEN))
    out, i, seq = [], 0, 0
    while True:
        piece = words[i:i + size]
        if not piece:
            break
        out.append(Chunk(f"{doc['doc_id']}#c{seq:03d}", doc["doc_id"], seq, " ".join(piece), doc.get("vendor_id"), doc["slice"], doc["title"]))
        seq += 1
        if i + size >= len(words):
            break
        i += step
    return out


def chunk_corpus(docs: list[dict], strategy: str = "fixed512") -> list[Chunk]:
    if strategy == "fixed512":
        return [c for d in docs for c in fixed_chunks(d)]
    raise ValueError(f"unknown chunking strategy {strategy} (Week 2 adds more)")


def save_chunks(chunks: list[Chunk], path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as fh:
        for c in chunks:
            fh.write(json.dumps(asdict(c), ensure_ascii=False) + "\n")


TOKEN_RE = re.compile(r"[a-z0-9]+(?:[.\-/][a-z0-9]+)*")
STOP = set("""a an the of to in and or for on by with is are was were be been as at this that these those from any all its it
shall may will can not no our we you your their they them he she his her i me my do does did has have had what which who whom
when where how why than then there here into onto over under about above below up down out off""".split())


def tokenize(text: str) -> list[str]:
    return [t for t in TOKEN_RE.findall(text.lower()) if t not in STOP]
