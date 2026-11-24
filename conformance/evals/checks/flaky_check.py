"""Skips cases with no entry. With an entry, fails (exit 1) the first time it runs in a run, then scores 1."""
import fcntl, json, os, sys
r = json.load(sys.stdin)
if r["expected"] is None:
    print(json.dumps({"score": None})); sys.exit()
os.makedirs(".counters", exist_ok=True)
with open(".counters/flaky_check", "a+") as f:
    fcntl.flock(f, fcntl.LOCK_EX); f.seek(0); n = int(f.read() or 0) + 1; f.seek(0); f.truncate(); f.write(str(n))
if n == 1:
    print("flaky check: first call fails", file=sys.stderr); sys.exit(1)
print(json.dumps({"score": 1, "reason": f"call {n}"}))
