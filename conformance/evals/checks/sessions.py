"""Run check: every row has its own session_id, and every turn of a row saw that same id (data.sid)."""
import json, sys
rows = json.load(sys.stdin)["rows"]
ids = [r["session_id"] for r in rows]
same = all(t.get("data", {}).get("sid") == r["session_id"] for r in rows for t in r["output"]["turns"])
ok = len(set(ids)) == len(ids) and all(ids) and same
print(json.dumps({"score": 1 if ok else 0, "reason": f"{len(set(ids))} distinct ids over {len(ids)} rows; turns match: {same}"}))
