"""Client for the shared capstone embedding API (bge-small-en-v1.5, 384 dims).

Why a separate client: the existing app.llm_client.embed() sends the *LLM* key (LLM_API_KEY) to the embeddings server. The shared
embedding server has its own key (EMBED_API_KEY) and its own CA certificate (vm02-ca.crt), so it gets its own client here.

Rules from the API quickstart that are enforced:
  * POST {base}/embeddings, model bge-small-en-v1.5, Authorization: Bearer <EMBED_API_KEY>
  * at most 16 texts per request, each within 512 model tokens (we cut at EMBED_MAX_WORDS words and retry shorter on a 400)
  * capacity errors (429 / 5xx / timeouts): wait briefly and retry the same batch
  * use the same model for indexing and search; TLS verified against vm02-ca.crt, never disabled
Vectors are cached on disk by SHA-1 of (model, text), so the corpus is embedded once.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

import numpy as np

from app.rag.config import RAG_DIR, RagSettings, settings

DIM = 384


class EmbeddingError(RuntimeError):
    pass


def _truncate(text: str, max_words: int) -> str:
    w = text.split()
    return text if len(w) <= max_words else " ".join(w[:max_words])


class EmbeddingClient:
    def __init__(self, cfg: RagSettings | None = None, cache: bool = True):
        self.cfg = cfg or settings()
        self.backend = self.cfg.embed_backend
        self.model_id = (f"local_{self.cfg.embed_local_model}" if self.backend == "local" else f"endpoint_{self.cfg.embed_model}").replace("/", "_")
        self.cache_path = RAG_DIR / "embed_cache" / f"{self.model_id}.jsonl"
        self._cache: dict[str, list[float]] = {}
        self._cache_on = cache
        self._http = None
        self._local = None
        self.calls = 0
        self.retries = 0
        if cache:
            self._load_cache()

    # ---------------------------------------------------------------- cache
    @staticmethod
    def _key(model: str, text: str) -> str:
        return hashlib.sha1((model + "\x00" + text).encode("utf-8")).hexdigest()

    def _load_cache(self):
        if self.cache_path.exists():
            with open(self.cache_path, encoding="utf-8") as fh:
                for line in fh:
                    if line.strip():
                        k, v = json.loads(line)
                        self._cache[k] = v

    def _append_cache(self, items: list[tuple[str, list[float]]]):
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.cache_path, "a", encoding="utf-8") as fh:
            for k, v in items:
                fh.write(json.dumps([k, [round(x, 6) for x in v]]) + "\n")

    # ---------------------------------------------------------------- transport
    def _client(self):
        if self._http is None:
            import httpx
            ca = self.cfg.embed_ca_bundle
            if ca and Path(ca).exists():
                verify: object = ca
            elif ca:
                raise EmbeddingError(f"CA certificate not found at {ca}. Save vm02-ca.crt there or set EMBED_CA_BUNDLE to its real path. "
                                     "Do not disable certificate checking.")
            else:
                verify = True
            if not self.cfg.embed_api_key:
                raise EmbeddingError("EMBED_API_KEY is empty. Put the shared embedding key from your coordinator in .env (never commit it).")
            self._http = httpx.Client(verify=verify, timeout=httpx.Timeout(60.0, connect=15.0),
                                      headers={"Authorization": f"Bearer {self.cfg.embed_api_key}", "Content-Type": "application/json"})
        return self._http

    def _post(self, texts: list[str], max_words: int) -> list[list[float]]:
        import httpx
        url = self.cfg.embed_base_url.rstrip("/") + "/embeddings"
        body = {"model": self.cfg.embed_model, "input": [_truncate(t, max_words) for t in texts]}
        delay = 1.0
        for attempt in range(1, 7):
            try:
                r = self._client().post(url, json=body)
            except (httpx.TimeoutException, httpx.TransportError) as e:
                if "CERTIFICATE_VERIFY_FAILED" in str(e):
                    raise EmbeddingError("TLS verification failed. Point EMBED_CA_BUNDLE at vm02-ca.crt (do not turn verification off).") from e
                err = f"{type(e).__name__}: {e}"
            else:
                self.calls += 1
                if r.status_code == 200:
                    data = sorted(r.json()["data"], key=lambda d: d["index"])
                    if len(data) != len(texts):
                        raise EmbeddingError(f"server returned {len(data)} vectors for {len(texts)} texts")
                    return [d["embedding"] for d in data]
                if r.status_code in (401, 403):
                    raise EmbeddingError(f"HTTP {r.status_code}: the embedding key was rejected. Check EMBED_API_KEY.")
                if r.status_code == 400 and max_words > 60:       # input too long for 512 tokens: shrink and retry
                    max_words = int(max_words * 0.7)
                    body["input"] = [_truncate(t, max_words) for t in texts]
                    err = f"HTTP 400 (shrinking to {max_words} words): {r.text[:150]}"
                elif r.status_code in (408, 409, 425, 429) or r.status_code >= 500:
                    err = f"HTTP {r.status_code} capacity/server error: {r.text[:150]}"
                else:
                    raise EmbeddingError(f"HTTP {r.status_code}: {r.text[:300]}")
            self.retries += 1
            time.sleep(delay)
            delay = min(delay * 2, 20)
        raise EmbeddingError(f"embedding request failed after retries: {err}")

    # ---------------------------------------------------------------- public API
    def _encode_local(self, texts: list[str]) -> np.ndarray:
        if self._local is None:
            from sentence_transformers import SentenceTransformer
            self._local = SentenceTransformer(self.cfg.embed_local_model)
        return np.asarray(self._local.encode(texts, batch_size=32, normalize_embeddings=True, show_progress_bar=False), dtype=np.float32)

    def embed_texts(self, texts: list[str], progress: bool = False) -> np.ndarray:
        """Embed documents / chunks. Returns an (n, 384) float32 array of L2-normalised vectors."""
        if not texts:
            return np.zeros((0, DIM), dtype=np.float32)
        if self.backend == "local":
            return self._encode_local(texts)
        keys = [self._key(self.cfg.embed_model, _truncate(t, self.cfg.embed_max_words)) for t in texts]
        todo = [i for i, k in enumerate(keys) if k not in self._cache]
        done = 0
        for s in range(0, len(todo), self.cfg.embed_batch):
            idx = todo[s:s + self.cfg.embed_batch]
            vecs = self._post([texts[i] for i in idx], self.cfg.embed_max_words)
            new = []
            for i, v in zip(idx, vecs):
                self._cache[keys[i]] = v
                new.append((keys[i], v))
            if self._cache_on:
                self._append_cache(new)
            done += len(idx)
            if progress and (done % (self.cfg.embed_batch * 20) == 0 or done == len(todo)):
                print(f"  embedded {done}/{len(todo)} new texts", flush=True)
        m = np.asarray([self._cache[k] for k in keys], dtype=np.float32)
        return m / (np.linalg.norm(m, axis=1, keepdims=True) + 1e-12)

    def embed_query(self, query: str) -> np.ndarray:
        """Embed a search query (bge instruction prefix added). Returns a normalised (384,) vector."""
        q = self.cfg.query_prefix + query
        if self.backend == "local":
            return self._encode_local([q])[0]
        return self.embed_texts([q])[0]


class FakeEmbeddingClient:
    """Deterministic offline embedder (hashed bag-of-words) for tests and CI. NOT for real evaluation."""
    backend = "fake"
    model_id = "fake_hash384"

    def __init__(self, *_, **__):
        self.calls = self.retries = 0

    def _vec(self, text: str) -> np.ndarray:
        from app.retrieval.chunking import tokenize
        v = np.zeros(DIM, dtype=np.float32)
        for t in tokenize(text):
            h = int(hashlib.md5(t.encode()).hexdigest(), 16)
            v[h % DIM] += 1.0 if (h >> 8) % 2 else -1.0
        n = np.linalg.norm(v)
        return v / n if n else v

    def embed_texts(self, texts, progress=False):
        return np.vstack([self._vec(t) for t in texts]) if texts else np.zeros((0, DIM), dtype=np.float32)

    def embed_query(self, query):
        return self._vec(query)


def get_embedder(cfg: RagSettings | None = None):
    if os.getenv("EMBED_BACKEND") == "fake":
        return FakeEmbeddingClient()
    return EmbeddingClient(cfg)
