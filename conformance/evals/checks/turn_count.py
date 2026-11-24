import json, sys
r = json.load(sys.stdin)
n = len(r["output"].get("turns") or [])
exp = r["expected"]
print(json.dumps({"score": None} if exp is None else {"score": 1 if n == exp else 0, "reason": f"{n} turns", "value": n}))
