"""Step 1.4c: build corpus v1 = real sources (per the source register) + synthetic documents.

    python -m scripts.ingest

Reads   data/manifests/source_register.csv, cuad_selection.csv, nda_selection.csv
        data/raw/procurement_dataset/...   (not in Git)
        data/synthetic/**.md               (scripts.generate_policies / generate_synthetic_docs)
Writes  data/processed/corpus_v1.jsonl     one JSON object per corpus document (not in Git, ~20 MB)
        data/manifests/corpus_v1_manifest.csv  doc_id, metadata, words, sha1 (committed = the frozen snapshot)
        data/processed/ingest_report.json

Corpus "documents" are section-level: long PDFs are split at heading boundaries into ~1,500-3,000-word parts.
Chunking for retrieval (step 1.8 / 2.2) happens later, inside each document.
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import subprocess
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "procurement_dataset"
MAN = ROOT / "data" / "manifests"
PROC = ROOT / "data" / "processed"
SYN = ROOT / "data" / "synthetic"
MIN_WORDS, TARGET_WORDS, MAX_WORDS = 300, 1500, 3000
WARN: list[str] = []

HEADING = re.compile(
    r"^(chapter\s+[\divxlc]+\b.*|appendix\b.*|annex(ure)?\b.*|schedule\b.*|part\s+[\divxlc]+\b.*|rule\s+\d+.*|"
    r"\d{1,2}(\.\d{1,2}){0,2}\.?\s+[A-Z][A-Za-z ,&()/'-]{3,90}|[A-Z][A-Z0-9 ,&()/'-]{6,90})$", re.I)
NOISE = re.compile(r"^(public disclosure authorized|page \d+( of \d+)?|\d{1,4}|[ivxlc]{1,6}|\|?\s*page)$", re.I)


# ------------------------------------------------------------------ extraction
def pdf_text(path: Path, ranges=None) -> str:
    def run(a=None, b=None):
        cmd = ["pdftotext", "-enc", "UTF-8"] + (["-f", str(a), "-l", str(b)] if a else []) + [str(path), "-"]
        return subprocess.run(cmd, capture_output=True, text=True).stdout
    return "\n".join(run(a, b) for a, b in ranges) if ranges else run()


def clean(text: str) -> str:
    text = text.replace("\f", "\n").replace("­", "")
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)                 # de-hyphenate line breaks
    lines = [l.strip() for l in text.splitlines()]
    lines = [l for l in lines if not NOISE.match(l)]
    text = "\n".join(lines)
    text = re.sub(r"(?<![.:;!?\n])\n(?=[a-z(])", " ", text)       # re-join wrapped sentences
    text = re.sub(r"\.{5,}\s*\d*", " ", text)                     # table-of-contents leaders
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def html_text(path: Path) -> str:
    from bs4 import BeautifulSoup
    return BeautifulSoup(path.read_text(errors="ignore"), "html.parser").get_text("\n")


def any_text(path: Path) -> str:
    s = path.suffix.lower()
    if s == ".pdf":
        return pdf_text(path)
    if s in (".htm", ".html"):
        return html_text(path)
    return path.read_text(errors="ignore")


def parse_ranges(scope: str):
    """'pages 24-41 ...' or 'pages 31-37 A&A; 59-84 BCR; ...' -> [(24, 41)] / [(31, 37), (59, 84), ...]"""
    if not scope.startswith("pages"):
        return None
    return [(int(a), int(b)) for a, b in re.findall(r"(\d+)-(\d+)", scope)]


# ------------------------------------------------------------------ splitting
def split_sections(text: str):
    paras = [p.strip() for p in re.split(r"\n\s*\n|\n(?=[A-Z0-9][^\n]{0,95}\n)", text) if p.strip()]
    parts, cur, cur_w, cur_head = [], [], 0, None
    for p in paras:
        first = p.splitlines()[0].strip()
        is_head = bool(HEADING.match(first)) and len(first.split()) <= 14
        w = len(p.split())
        if cur and ((is_head and cur_w >= TARGET_WORDS) or cur_w + w > MAX_WORDS):
            parts.append((cur_head, "\n\n".join(cur)))
            cur, cur_w, cur_head = [], 0, None
        if cur_head is None and is_head:
            cur_head = first[:120]
        cur.append(p)
        cur_w += w
    if cur:
        if parts and cur_w < MIN_WORDS:
            h, t = parts.pop()
            parts.append((h, t + "\n\n" + "\n\n".join(cur)))
        else:
            parts.append((cur_head, "\n\n".join(cur)))
    return parts


# ------------------------------------------------------------------ corpus assembly
DOCS: list[dict] = []


def add_doc(doc_id, text, **meta):
    text = text.strip()
    if len(text.split()) < (15 if meta.get("source") == "synthetic" else 40):
        WARN.append(f"skipped near-empty {doc_id}")
        return
    rec = dict(doc_id=doc_id, words=len(text.split()), sha1=hashlib.sha1(text.encode()).hexdigest(), **meta, text=text)
    DOCS.append(rec)


def base_meta(row, **kw):
    m = dict(source_id=row["source_id"], slice=row["slice"], source="real", title=row["title"], vendor_id=None,
             doc_type=row["slice"], document_date=row.get("version_date") or None, version=row.get("version_date") or None,
             status="SUPERSEDED" if "Superseded" in row.get("notes", "") else "CURRENT", licence=row["licence"],
             access_class="public", publisher=row["publisher"], jurisdiction=row["jurisdiction"], raw_path=row["file_path"])
    m.update(kw)
    return m


def ingest_split_pdf(row):
    path = RAW / row["file_path"]
    text = clean(pdf_text(path, parse_ranges(row["ingest_scope"])))
    parts = split_sections(text)
    for i, (head, t) in enumerate(parts, 1):
        add_doc(f"{row['source_id']}-S{i:03d}", t, **base_meta(row, title=f"{row['title']}: part {i} of {len(parts)}" + (f" ({head})" if head else ""),
                                                             part=i, parts=len(parts), section_heading=head))


def ingest_cuad(row):
    data = json.loads((RAW / "Contract Analysis Datasets/CUAD/data/CUADv1.json").read_text())["data"]
    keep = {r["cuad_title"] for r in csv.DictReader(open(MAN / "cuad_selection.csv")) if r["include"] == "yes"}
    n = 0
    for d in data:
        if d["title"] in keep:
            n += 1
            slug = re.sub(r"[^A-Za-z0-9]+", "-", d["title"].split("_")[0])[:40].strip("-")
            add_doc(f"CON-001-{n:03d}-{slug}", clean(d["paragraphs"][0]["context"]),
                    **base_meta(row, title=f"CUAD contract: {d['title']}", doc_type="contract_public", cuad_title=d["title"]))


def ingest_nda(row):
    raw = RAW / "Contract Analysis Datasets/Contract NLI/contract-nli/raw"
    n = 0
    for r in csv.DictReader(open(MAN / "nda_selection.csv")):
        if r["include"] != "yes":
            continue
        n += 1
        slug = re.sub(r"[^A-Za-z0-9]+", "-", Path(r["file"]).stem)[:40].strip("-")
        add_doc(f"CON-002-{n:03d}-{slug}", clean(any_text(raw / r["file"])),
                **base_meta(row, title=f"Non-disclosure agreement: {Path(r['file']).stem}", doc_type="nda_public", raw_path=f"{row['file_path']}{r['file']}"))


def ingest_common_paper(row):
    z = zipfile.ZipFile(RAW / row["file_path"])
    text = "\n\n".join(z.read(n).decode(errors="ignore") for n in sorted(z.namelist())
                       if n.endswith(".md") and "README" not in n and "/." not in n)
    add_doc(row["source_id"], text, **base_meta(row, doc_type="contract_template"))


def ingest_synthetic():
    for p in sorted(SYN.rglob("*.md")):
        raw = p.read_text()
        _, fm, body = raw.split("---\n", 2)
        meta = {k: json.loads(v) for k, v in (l.split(": ", 1) for l in fm.strip().splitlines())}
        did = meta.pop("doc_id")
        meta.setdefault("status", "CURRENT")
        add_doc(did, body, source_id=f"SYN-{meta.get('slice')}", source="synthetic", licence="Team-generated synthetic data (CC BY 4.0)",
                raw_path=str(p.relative_to(ROOT)), **{k: v for k, v in meta.items() if k not in ("source",)})


def main():
    PROC.mkdir(parents=True, exist_ok=True)
    reg = list(csv.DictReader(open(MAN / "source_register.csv")))
    for row in reg:
        if row["role"] not in ("corpus", "corpus + generation_template") or row["include"] not in ("yes", "partial"):
            continue
        sid = row["source_id"]
        if sid == "CON-001":
            ingest_cuad(row)
        elif sid == "CON-002":
            ingest_nda(row)
        elif row["file_path"].endswith(".zip"):
            ingest_common_paper(row)
        elif row["file_path"].endswith(".pdf"):
            ingest_split_pdf(row)
        else:
            WARN.append(f"no extractor for {sid}")
    ingest_synthetic()

    ids = Counter(d["doc_id"] for d in DOCS)
    dupes = [k for k, n in ids.items() if n > 1]
    if dupes:
        raise SystemExit(f"duplicate doc_ids: {dupes[:5]}")
    sha = Counter(d["sha1"] for d in DOCS)
    for d in DOCS:
        if sha[d["sha1"]] > 1:
            WARN.append(f"identical text: {d['doc_id']}")

    with open(PROC / "corpus_v1.jsonl", "w") as fh:
        for d in DOCS:
            fh.write(json.dumps(d, ensure_ascii=False, default=str) + "\n")
    cols = ["doc_id", "source_id", "source", "slice", "doc_type", "vendor_id", "title", "document_date", "status", "access_class",
            "licence", "words", "sha1", "raw_path"]
    with open(MAN / "corpus_v1_manifest.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore"); w.writeheader(); w.writerows(DOCS)

    by_slice = defaultdict(lambda: Counter())
    for d in DOCS:
        by_slice[d["slice"]][d["source"]] += 1
    report = dict(corpus_version="v1", documents=len(DOCS), words=sum(d["words"] for d in DOCS),
                  by_slice={k: dict(v) for k, v in sorted(by_slice.items())},
                  by_source_id=dict(Counter(d["source_id"] for d in DOCS)), warnings=WARN)
    (PROC / "ingest_report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps({k: v for k, v in report.items() if k not in ("by_source_id", "warnings")}, indent=1))
    print("warnings:", len(WARN), WARN[:8])


if __name__ == "__main__":
    main()
