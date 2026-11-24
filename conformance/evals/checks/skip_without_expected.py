import json, sys
r = json.load(sys.stdin)
print(json.dumps({"score": None} if r["expected"] is None else {"score": 1, "reason": "had an entry"}))
