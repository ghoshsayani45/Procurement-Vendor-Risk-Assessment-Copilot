# data/processed (not in Git)

Regenerate with `make ingest`. Main outputs:
- `corpus_v1.jsonl`: one JSON object per corpus document (`doc_id`, metadata, `text`)
- `ingest_report.json`: counts, per-source stats, warnings
The frozen manifest (`data/manifests/corpus_v1_manifest.csv`, with a SHA-1 per document) is committed, so any rebuild can be checked against it.
