# Installing and running the copilot on your own laptop

This guide takes a teammate from nothing to a working app in about 20 minutes. The app runs fully offline; the course
model and the embedding server are optional extras that switch on model-written answers and search by meaning.

## 1. What you need

| Item | Where to get it | Needed for |
|---|---|---|
| Python 3.10 or 3.11 on the PATH | python.org (tick "Add to PATH" on Windows) | Everything |
| Git | git-scm.com | Cloning the repo |
| This repository, `main` branch | GitHub | Everything |
| `vm05-ca.crt` (LLM server) and `vm02-ca.crt` (embedding server) | Team Drive / course coordinator | Course model and embeddings |
| `LLM_API_KEY` and `EMBED_API_KEY` | Team Drive / course coordinator. They are two different keys | Course model and embeddings |
| `corpus_v1.jsonl` (12 MB) **or** `Procurement_dataset_complete.zip` (~260 MB) | Team Drive | Real regulation and policy texts (DPDP, GFR, NIST ...) |

Without the last three rows the app still runs: full reviews, comparisons, refusals and approvals work on the
synthetic documents that are in Git.

## 2. Clone and start (offline demo)

```powershell
git clone https://github.com/<owner>/Procurement-Vendor-Risk-Assessment-Copilot.git
cd Procurement-Vendor-Risk-Assessment-Copilot
git checkout main
```

| You are on | Start command | Open |
|---|---|---|
| Windows | double-click `run_app.bat` | http://localhost:8501 |
| macOS / Linux | `./run_app.sh` | http://localhost:8501 |

The first start creates `.venv`, installs the app packages (a few minutes), copies `.env.example` to `.env` and loads
the local SQLite database. Later starts take seconds. Stop the app with Ctrl+C in the window.

## 3. Configuration file (`.env`)

`.env.example` in the repo is the template and lists every setting the code reads. `.env` is your private copy; it is
git-ignored. **Never commit `.env`, a key or a certificate.**

1. Put the two certificate files in the `certs/` folder of the repo (create it if missing; it is git-ignored):
   `certs/vm05-ca.crt` and `certs/vm02-ca.crt`.
2. Open `.env` and fill in the two keys:
   ```
   LLM_API_KEY=<course LLM key>
   EMBED_API_KEY=<course embedding key>
   ```
3. To let the model write answers to open questions, set `COPILOT_LLM=endpoint` (default `none` = no model calls).
4. If you have the full corpus (section 4), keep `CORPUS_PATH=data/processed/corpus_v1.jsonl`.

Do not paste another team's `.env` over yours: it carries their own variables and can switch the app to a database or
API URL that does not exist on your laptop. Start from `.env.example`.

Check the two servers (from the repo folder):
```powershell
.\.venv\Scripts\python -m scripts.check_endpoint          # course LLM: should print OK
.\.venv\Scripts\python -m scripts.rag_check_embeddings    # should print: OK: 2 vectors of 384 numbers
```
On macOS / Linux use `.venv/bin/python` instead of `.\.venv\Scripts\python`.

## 4. The full document library (recommended)

**Option A, quickest:** copy the shared `corpus_v1.jsonl` from the team Drive to `data/processed/corpus_v1.jsonl`.

**Option B, rebuild it:** unzip `Procurement_dataset_complete.zip` so the folder `data/raw/procurement_dataset/`
exists, install poppler (`pdftotext`: Windows - poppler for Windows, add its `bin` folder to PATH; macOS
`brew install poppler`; Linux `sudo apt install poppler-utils`), then run
```powershell
.\.venv\Scripts\python -m scripts.ingest
```
It must report 1,053 documents; the result is identical to the frozen manifest in `data/manifests/`.

## 5. Search by meaning (hybrid index, optional)

Needs the embedding key and certificate. Run once, in this order (the first one takes 15-30 minutes; embeddings are
cached in `data/processed/rag/embed_cache/`, so a rerun after an interruption continues where it stopped):
```powershell
.\.venv\Scripts\python -m scripts.rag_chunking_experiments
.\.venv\Scripts\python -m scripts.rag_build_index --chunking heading
.\.venv\Scripts\python -m scripts.rag_retrieval_eval --chunking heading
```
Without this index the copilot uses keyword (BM25) search, which works but misses some regulation questions.

## 6. Check that everything works

```powershell
run_app.bat -Mode test                                              # all tests, offline (Windows)
.\.venv\Scripts\python -m scripts.run_copilot --llm endpoint        # dev split, 30 questions, graded
```
`./run_app.sh test` on macOS / Linux. The dev run prints accuracy by category; on 2026-11-20 it scored 27/30.
**Do not run the test split** (`--split test`): it is kept for the team's gate runs only (decision D12).

## 7. A five-minute demo

See `RUN_APP.md`, section "A five-minute demo" (full review of V011, approval routing for V023, comparisons,
a forged-approval question and a refused system-prompt request).

## 8. Troubleshooting

| Message | Cause | Fix |
|---|---|---|
| `run_app.bat` not found | Wrong branch or folder | `git checkout main`, then `cd` into the repo folder |
| `CA certificate not found at ...` | Certificate not where `.env` points | Put it in `certs/` or fix `LLM_CA_BUNDLE` / `EMBED_CA_BUNDLE` |
| `APIConnectionError: Connection error` | Course server not reachable from your network | Check internet / VPN, then rerun the checks in section 3 |
| `HTTP 401` or `403` | Wrong key, or the two keys swapped | `LLM_API_KEY` for the model, `EMBED_API_KEY` for embeddings |
| `No saved index at data\processed\rag\heading` | Hybrid index not built | Run section 5, or ignore (keyword search is used) |
| `HTTP 422 ... must have less than 512 tokens` | Old code | `git pull` (fixed on 2026-11-20) |
| UI opens but finds no vendors | Database not loaded | `.\.venv\Scripts\python -m scripts.load_db` |
| Port 8501 already in use | App already running | Close the other window, or `streamlit run app\ui\streamlit_app.py --server.port 8502` |

PowerShell logs are written as UTF-16 by `Tee-Object`; open them in VS Code or Notepad, not in tools that expect UTF-8.
