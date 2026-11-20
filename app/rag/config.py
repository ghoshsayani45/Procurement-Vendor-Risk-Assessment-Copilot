"""RAG settings, read from environment variables (see .env.rag.example). Nothing here touches the Week 1 settings."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parents[2]
_cp = Path((os.getenv("CORPUS_PATH") or "").strip() or ROOT / "data" / "processed" / "corpus_v1.jsonl")
CORPUS_PATH = _cp if _cp.is_absolute() else ROOT / _cp   # CORPUS_PATH in .env selects another corpus file (default: frozen v1)
RAG_DIR = ROOT / "data" / "processed" / "rag"
REPORTS = ROOT / "reports"


def _f(name: str, default: str) -> str:
    """A variable that is unset OR blank in .env (e.g. `EMBED_BASE_URL=` copied from .env.example) takes the default."""
    return (os.getenv(name) or default).strip()


@dataclass
class RagSettings:
    # --- embeddings endpoint (shared capstone server) ---
    embed_backend: str = field(default_factory=lambda: _f("EMBED_BACKEND", "endpoint"))        # endpoint | local
    embed_base_url: str = field(default_factory=lambda: _f("EMBED_BASE_URL", "https://103.42.50.41:1035/v1"))
    embed_model: str = field(default_factory=lambda: _f("EMBED_MODEL", "bge-small-en-v1.5"))
    embed_api_key: str = field(default_factory=lambda: _f("EMBED_API_KEY", ""))
    embed_ca_bundle: str = field(default_factory=lambda: _f("EMBED_CA_BUNDLE", str(Path.home() / "Downloads" / "vm02-ca.crt")))
    embed_batch: int = field(default_factory=lambda: min(16, int(_f("EMBED_BATCH", "16"))))    # server limit is 16 texts
    embed_max_words: int = field(default_factory=lambda: int(_f("EMBED_MAX_WORDS", "300")))    # keeps a chunk under 512 model tokens
    embed_local_model: str = field(default_factory=lambda: _f("EMBED_LOCAL_MODEL", "BAAI/bge-small-en-v1.5"))
    # bge models work best when the *query* (not the documents) carries this instruction
    query_prefix: str = field(default_factory=lambda: os.getenv("EMBED_QUERY_PREFIX", "Represent this sentence for searching relevant passages: "))

    # --- retrieval ---
    chunking: str = field(default_factory=lambda: _f("RAG_CHUNKING", "heading"))               # fixed | heading | clause | window
    top_bm25: int = field(default_factory=lambda: int(_f("RAG_TOP_BM25", "20")))
    top_dense: int = field(default_factory=lambda: int(_f("RAG_TOP_DENSE", "20")))
    rrf_k: int = field(default_factory=lambda: int(_f("RAG_RRF_K", "60")))
    final_k: int = field(default_factory=lambda: int(_f("RAG_FINAL_K", "6")))
    reranker: str = field(default_factory=lambda: _f("RAG_RERANKER", "cross-encoder"))         # cross-encoder | lexical | none
    reranker_model: str = field(default_factory=lambda: _f("RAG_RERANKER_MODEL", "BAAI/bge-reranker-base"))
    vendor_filter: bool = field(default_factory=lambda: _f("RAG_VENDOR_FILTER", "1") == "1")
    demote_superseded: bool = field(default_factory=lambda: _f("RAG_DEMOTE_SUPERSEDED", "1") == "1")

    # --- generation (the course endpoint has an 8,192 token window and 1,024 token answer cap) ---
    context_words: int = field(default_factory=lambda: int(_f("RAG_CONTEXT_WORDS", "2200")))
    max_answer_tokens: int = field(default_factory=lambda: int(_f("RAG_MAX_ANSWER_TOKENS", "700")))


def settings() -> RagSettings:
    return RagSettings()
