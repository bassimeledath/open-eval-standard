"""OES custom check: a number in the output is within a tolerance of the expected one.

params.path is an output path such as data.total, and params.tolerance the
largest allowed difference. The scorer's expected entry is the number.
"""
import json
import sys

req = json.load(sys.stdin)
params, expected = req.get("params") or {}, req.get("expected")
if expected is None:
    print(json.dumps({"score": None, "reason": "no expected entry"}))
    sys.exit()

value = req["output"]
for part in params["path"].split("."):
    value = value.get(part) if isinstance(value, dict) else None

if not isinstance(value, (int, float)) or isinstance(value, bool):
    print(json.dumps({"score": 0, "reason": f"{params['path']} is not a number: {value!r}"}))
else:
    off = abs(value - expected)
    print(json.dumps({"score": 1 if off <= params.get("tolerance", 0) else 0, "value": off,
                      "reason": f"{params['path']} = {value}, expected {expected}, off by {off:g}"}))
