"""Create the copilot tables and load reference data (vendors, financial metrics, document metadata).

    python -m scripts.load_db                    # DATABASE_URL, or the local SQLite file data/processed/copilot.sqlite
Idempotent: rows already present are skipped. The API also runs this on start-up.
"""
from app.db.store import database_url, engine, load_reference_data

if __name__ == "__main__":
    n = load_reference_data(engine())
    print(f"{database_url().split('@')[-1]}: loaded {n}")
