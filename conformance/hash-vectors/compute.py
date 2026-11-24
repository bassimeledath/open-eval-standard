"""Compute eval_hash per SPEC 8.2, independently of any runner. Stdlib only.

  python3 compute.py            print each vector's hash and whether vectors.json agrees
  python3 compute.py --write    store the hashes in vectors.json

vectors.json lists, per vector, the files and folders the eval uses (step 1), relative to the eval's folder.
"""
import hashlib, json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))


def eval_hash(base, uses):
    files = set()
    for u in uses + (["checks"] if os.path.isdir(os.path.join(base, "checks")) else []):
        p = os.path.join(base, u)
        walked = [os.path.join(d, f) for d, _, fs in os.walk(p) for f in fs] if os.path.isdir(p) else [p]
        files |= {os.path.relpath(f, base).replace(os.sep, "/") for f in walked}
    keep = lambda r: "__pycache__" not in r.split("/") and not r.endswith(".pyc") and r.split("/")[-1] != ".DS_Store"
    h = hashlib.sha256()
    for rel in sorted((r for r in files if keep(r)), key=lambda r: r.encode("utf-8")):
        data = open(os.path.join(base, rel), "rb").read()
        h.update(rel.encode("utf-8") + b"\0" + str(len(data)).encode() + b"\0" + data)
    return "sha256:" + h.hexdigest()


if __name__ == "__main__":
    path = os.path.join(HERE, "vectors.json")
    vectors = json.load(open(path))
    for name, v in vectors.items():
        got = eval_hash(os.path.join(HERE, os.path.dirname(v["eval"])), v["uses"])
        print(f"{name}: {got} {'ok' if got == v.get('eval_hash') else 'DIFFERS'}")
        v["eval_hash"] = got
    if "--write" in sys.argv:
        json.dump(vectors, open(path, "w"), indent=2)
        open(path, "a").write("\n")
