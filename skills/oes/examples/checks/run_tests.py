"""OES custom check: run the unit tests in the repo the agent changed.

Reads {output, expected} on stdin. The agent returns where its work is in
output.data.repo. Scores 1 when every test passes and at least
expected.min_passing tests ran.
"""
import json
import re
import subprocess
import sys

req = json.load(sys.stdin)
repo = (req["output"].get("data") or {}).get("repo")
if not repo:
    print(json.dumps({"score": 0, "reason": "the agent returned no data.repo"}))
    sys.exit()

run = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", repo, "-t", repo],
                     capture_output=True, text=True, timeout=600)
ran = re.search(r"Ran (\d+) tests?", run.stderr)
total = int(ran.group(1)) if ran else 0
need = (req.get("expected") or {}).get("min_passing", 1)
ok = run.returncode == 0 and total >= need
print(json.dumps({"score": 1 if ok else 0, "value": total,
                  "reason": f"{total} tests ran, {'all passed' if run.returncode == 0 else 'some failed'}; needed {need}"}))
