import json, sys
r = json.load(sys.stdin)
name = r["params"]["scorer"]
scores = [row["scores"][name]["score"] for row in r["rows"] if row.get("scores", {}).get(name, {}).get("score") is not None]
print(json.dumps({"score": sum(scores) / len(scores) if scores else 0, "reason": f"{len(scores)} scored rows of {len(r['rows'])}"}))
