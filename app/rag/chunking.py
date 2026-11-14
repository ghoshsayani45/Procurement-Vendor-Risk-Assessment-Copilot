"""Step 2.2 chunking strategies for the chunking experiments.

Every strategy returns RagChunk objects that carry metadata (vendor, doc type, status, date, access class) so retrieval can
filter and citations can show the document date and evidence type. Every chunk text starts with a short context header
("[Title | doc_id]") because look-alike synthetic documents differ mainly in the vendor name, and the Week 1 baseline showed
that dropping the title loses it.

Strategies
  fixed   : fixed-size word windows with overlap (the Week 1 baseline, for comparison)
  heading : split at markdown headings / numbered sections, then pack small sections up to max_words
  clause  : like heading, but also splits tables per row group and numbered clauses ("3.2", "CS-3", "DP-2"), one clause per chunk
  window  : sentence windows (N sentences, stride M); small chunks that are precise, expanded to a parent at answer time
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from app.rag.config import CORPUS_PATH

STRATEGIES = ("fixed", "heading", "clause", "window")

_FRONT = re.compile(r"\A---\n.*?\n---\n", re.S)
_HEADING = re.compile(r"^(#{1,4}\s+.+|(?:Section|Article|Part|Chapter)\s+\d+[.:]?\s.*|\d{1,2}(?:\.\d{1,2})*\.?\s+[A-Z][^\n]{2,80})$", re.M)
_CLAUSE = re.compile(r"^(?:\|?\s*)?(?:\d{1,2}\.\d{1,2}\b|[A-Z]{1,4}-\d{1,2}\b|\(\w\)\s)", re.M)
_SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])")


@dataclass
class RagChunk:
    chunk_id: str
    doc_id: str
    seq: int
    text: str                 # what is indexed and shown (header + body)
    vendor_id: str | None = None
    slice: str = ""
    doc_type: str = ""
    title: str = ""
    document_date: str | None = None
    status: str = "CURRENT"
    access_class: str = "public"
    section: str = ""
    parent_text: str | None = None   # window strategy only: the wider passage handed to the generator

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @property
    def words(self) -> int:
        return len(self.text.split())


def load_corpus(path: Path = CORPUS_PATH) -> list[dict]:
    if not path.exists():
        raise FileNotFoundError(f"{path} not found. Rebuild corpus v1 first: put data/raw/ in place and run `make ingest`.")
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def strip_front_matter(text: str) -> str:
    return _FRONT.sub("", text, count=1).strip()


def _header(doc: dict, section: str = "") -> str:
    h = f"[{doc.get('title', '')} | {doc['doc_id']}"
    if doc.get("document_date"):
        h += f" | {doc['document_date']}"
    if doc.get("status") and doc["status"] != "CURRENT":
        h += f" | {doc['status']}"
    h += "]"
    return h + (f" {section}" if section else "")


def _mk(doc: dict, seq: int, body: str, section: str = "", parent: str | None = None, header: bool = True) -> RagChunk:
    text = (_header(doc, section) + "\n" + body.strip()) if header else body.strip()
    return RagChunk(chunk_id=f"{doc['doc_id']}#r{seq:03d}", doc_id=doc["doc_id"], seq=seq, text=text, vendor_id=doc.get("vendor_id"),
                    slice=doc.get("slice", ""), doc_type=doc.get("doc_type", ""), title=doc.get("title", ""),
                    document_date=doc.get("document_date"), status=doc.get("status", "CURRENT") or "CURRENT",
                    access_class=doc.get("access_class", "public") or "public", section=section, parent_text=parent)


def _split_long(text: str, max_words: int, overlap: int = 40) -> list[str]:
    words = text.split()
    if len(words) <= max_words:
        return [text]
    out, i = [], 0
    step = max(1, max_words - overlap)
    while i < len(words):
        out.append(" ".join(words[i:i + max_words]))
        if i + max_words >= len(words):
            break
        i += step
    return out


# ------------------------------------------------------------------ strategies
def fixed_chunks(doc: dict, max_words: int = 300, overlap: int = 40, **_) -> list[RagChunk]:
    body = strip_front_matter(doc["text"])
    return [_mk(doc, i, p) for i, p in enumerate(_split_long(body, max_words, overlap))]


def _sections(body: str) -> list[tuple[str, str]]:
    """Split into (heading, text) sections; text before the first heading gets an empty heading."""
    marks = [m.start() for m in _HEADING.finditer(body)]
    if not marks:
        return [("", body)]
    if marks[0] != 0:
        marks = [0] + marks
    out = []
    for a, b in zip(marks, marks[1:] + [len(body)]):
        piece = body[a:b].strip()
        if not piece:
            continue
        first, _, rest = piece.partition("\n")
        if _HEADING.match(first.strip()) and rest.strip():
            out.append((first.strip().lstrip("# ").strip(), rest.strip()))
        else:
            out.append(("", piece))
    return out


def heading_chunks(doc: dict, max_words: int = 300, min_words: int = 60, **_) -> list[RagChunk]:
    body = strip_front_matter(doc["text"])
    chunks: list[RagChunk] = []
    buf_head, buf = "", []

    def flush():
        nonlocal buf_head, buf
        if buf:
            chunks.append(_mk(doc, len(chunks), "\n\n".join(buf), buf_head))
        buf_head, buf = "", []

    for head, text in _sections(body):
        piece = (f"## {head}\n" if head else "") + text
        for part in _split_long(piece, max_words):
            if buf and sum(len(x.split()) for x in buf) + len(part.split()) > max_words:
                flush()
            if not buf:
                buf_head = head
            buf.append(part)
            if sum(len(x.split()) for x in buf) >= min_words and len(part.split()) >= max_words * 0.8:
                flush()
    flush()
    return chunks


def clause_chunks(doc: dict, max_words: int = 180, **_) -> list[RagChunk]:
    """One clause or table row-group per chunk. Good for contracts and policy rules; produces more, smaller chunks."""
    body = strip_front_matter(doc["text"])
    chunks: list[RagChunk] = []
    for head, text in _sections(body):
        lines = text.split("\n")
        table_head = [l for l in lines[:2] if l.strip().startswith("|")] if len(lines) > 2 and lines[0].strip().startswith("|") else []
        units, cur = [], []
        for ln in lines:
            if _CLAUSE.match(ln) and cur and not ln.strip().startswith("|"):
                units.append("\n".join(cur))
                cur = []
            cur.append(ln)
            if ln.strip().startswith("|") and len(cur) >= 6:        # long tables: group rows
                units.append("\n".join(cur))
                cur = []
        if cur:
            units.append("\n".join(cur))
        packed, buf = [], ""
        for u in units:
            if buf and len((buf + "\n" + u).split()) > max_words:
                packed.append(buf)
                buf = ""
            buf = (buf + "\n" + u).strip() if buf else u
        if buf:
            packed.append(buf)
        for u in packed:
            for part in _split_long(u, max_words):
                body_txt = ("\n".join(table_head) + "\n" + part) if table_head and not part.lstrip().startswith("|---") and not part.startswith(table_head[0]) else part
                if len(part.split()) >= 4:
                    chunks.append(_mk(doc, len(chunks), body_txt, head))
    return chunks or fixed_chunks(doc)


def window_chunks(doc: dict, sentences: int = 4, stride: int = 2, parent_words: int = 260, **_) -> list[RagChunk]:
    body = strip_front_matter(doc["text"])
    sents = [s.strip() for s in _SENT.split(re.sub(r"\s*\n\s*", " \n ", body)) if s.strip()]
    chunks = []
    i = 0
    while i < len(sents):
        win = sents[i:i + sentences]
        ctx = sents[max(0, i - 2):i + sentences + 2]
        chunks.append(_mk(doc, len(chunks), " ".join(win), parent=" ".join(" ".join(ctx).split()[:parent_words])))
        if i + sentences >= len(sents):
            break
        i += stride
    return chunks


_FN = {"fixed": fixed_chunks, "heading": heading_chunks, "clause": clause_chunks, "window": window_chunks}


def chunk_document(doc: dict, strategy: str = "heading", **kw) -> list[RagChunk]:
    if strategy not in _FN:
        raise ValueError(f"unknown chunking strategy {strategy!r}; choose from {STRATEGIES}")
    return _FN[strategy](doc, **kw)


def chunk_corpus(docs: list[dict], strategy: str = "heading", **kw) -> list[RagChunk]:
    return [c for d in docs for c in chunk_document(d, strategy, **kw)]


def describe(chunks: list[RagChunk]) -> dict:
    w = sorted(c.words for c in chunks) or [0]
    return dict(chunks=len(chunks), docs=len({c.doc_id for c in chunks}), median_words=w[len(w) // 2], p95_words=w[int(len(w) * .95)], max_words=w[-1])


def load_markdown_corpus(root: Path | None = None) -> list[dict]:
    """Offline fallback: read the synthetic documents (data/synthetic/**/*.md with YAML front matter) as corpus records.
    Lets you test the RAG code before data/raw/ is available. The real evaluation must use corpus_v1.jsonl."""
    import yaml
    from app.rag.config import ROOT
    root = root or ROOT / "data" / "synthetic"
    docs = []
    for p in sorted(root.rglob("*.md")):
        raw = p.read_text(encoding="utf-8")
        m = _FRONT.match(raw)
        if not m:
            continue
        meta = yaml.safe_load(m.group(0).strip().strip("-")) or {}
        if "doc_id" not in meta:
            continue
        meta.setdefault("slice", p.parent.name)
        meta.setdefault("status", "CURRENT")
        meta["text"] = raw
        docs.append(meta)
    return docs
