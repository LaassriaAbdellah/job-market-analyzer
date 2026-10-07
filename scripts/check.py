import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FILE = PROJECT_ROOT / "data" / "parsed_jobs.json"

with FILE.open("r", encoding="utf-8") as f:
    jobs = json.load(f)

jobs = sorted(
    jobs,
    key=lambda x: x.get("matching_score", 0),
    reverse=True
)

print("\n===== TOP 10 MATCHING =====\n")

for i, job in enumerate(jobs[:10], start=1):
    print(f"{i}. {job['title']}")
    print(f"   Entreprise : {job['company']}")
    print(f"   Score      : {job['matching_score']} %")
    print(f"   Skills     : {job['extracted_skills']}")
    print(f"   Source     : {job['source']}")
    print("-" * 70)