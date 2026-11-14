"""Check the shared embedding endpoint before building anything.

    python -m scripts.rag_check_embeddings

Needs EMBED_API_KEY (and EMBED_BASE_URL / EMBED_CA_BUNDLE if you changed them) in .env. Sends one tiny request and prints the vector size.
"""
from app.rag.config import settings
from app.rag.embeddings import EmbeddingClient, EmbeddingError


def main():
    cfg = settings()
    print(f"base_url={cfg.embed_base_url} model={cfg.embed_model} ca={cfg.embed_ca_bundle} key={'set' if cfg.embed_api_key else 'MISSING'}")
    try:
        c = EmbeddingClient(cfg, cache=False)
        v = c.embed_texts(["Example document chunk", "Example search query"])
    except EmbeddingError as e:
        raise SystemExit(f"FAILED: {e}")
    print(f"OK: {v.shape[0]} vectors of {v.shape[1]} numbers (expected 384). requests={c.calls} retries={c.retries}")


if __name__ == "__main__":
    main()
