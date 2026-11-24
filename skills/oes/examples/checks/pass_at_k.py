"""OES run-scope custom check: pass@k or pass^k over another scorer's trial scores.

params.scorer names the trial scorer to read. params.mode is "any" (pass@k: at
least one try passed) or "all" (pass^k: every try passed). Returns the share of
test cases that meet it.
"""
import json
import sys

req = json.load(sys.stdin)
params = req.get("params") or {}
name, mode = params["scorer"], params.get("mode", "any")

by_case = {}
for row in req["rows"]:
    score = (row.get("scores") or {}).get(name, {}).get("score")
    if score is not None:
        by_case.setdefault(row["case_id"], []).append(score >= 1)

if not by_case:
    print(json.dumps({"score": None, "reason": f"{name} scored nothing"}))
else:
    hits = sum((any if mode == "any" else all)(tries) for tries in by_case.values())
    print(json.dumps({"score": hits / len(by_case), "reason": f"{hits} of {len(by_case)} cases, mode {mode}"}))
