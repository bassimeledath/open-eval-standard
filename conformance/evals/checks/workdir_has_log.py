import json, os, sys
r = json.load(sys.stdin)
if r["expected"] is None:
    print(json.dumps({"score": None})); sys.exit()
wd = (r["output"].get("data") or {}).get("workdir")
ok = bool(wd) and os.path.exists(os.path.join(wd, "log.txt"))
print(json.dumps({"score": 1 if ok else 0, "reason": f"workdir={wd} exists={ok}"}))
