"""Export JSON schemas for prompts and constrained decoding.  python -m scripts.export_json_schemas"""
import json
from pathlib import Path

from app.schemas import Answer, Clarification, ComparisonResult, Plan, Refusal, Report, ReviewRequest, VendorFacts

OUT = Path(__file__).resolve().parents[1] / "schemas"
OUT.mkdir(exist_ok=True)
for m in (ReviewRequest, Plan, Report, ComparisonResult, Answer, Clarification, Refusal, VendorFacts):
    (OUT / f"{m.__name__}.schema.json").write_text(json.dumps(m.model_json_schema(), indent=2))
    print("wrote", m.__name__)
