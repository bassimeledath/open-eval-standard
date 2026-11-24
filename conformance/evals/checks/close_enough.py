import json, sys
r = json.load(sys.stdin)
if r["expected"] is None:
    print(json.dumps({"score": None})); sys.exit()
cur = r["output"]
for k in r["params"]["path"].split("."):
    cur = (cur or {}).get(k)
diff = abs((cur if isinstance(cur, (int, float)) else float("inf")) - r["expected"])
print(json.dumps({"score": 1 if diff <= r["params"]["tolerance"] else 0, "reason": f"off by {diff}", "value": diff}))
