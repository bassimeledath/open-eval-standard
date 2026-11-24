#!/usr/bin/env python3
"""OES conformance suite. Stdlib only.

  python3 conformance/run.py [--only TEXT] [--keep] [-v] <runner command...>

Runs every check of the suite against a runner and prints a pass/fail table. Exits 1 on any mismatch.
The runner command is called as `<runner command...> run <eval> --agent-version v-conformance
--agent-model fake-agent` and `<runner command...> validate <eval>`, from a fresh copy of the suite,
which is the repository root for the run. Arguments of the runner command that name an existing
path (like `--project runners/python`) are made absolute first.
"""
import json, math, os, re, shutil, socket, subprocess, sys, tempfile, time

SUITE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(SUITE)
RESULT_SCHEMA = json.load(open(os.path.join(REPO, "skills", "oes", "result.schema.json")))
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.join(SUITE, "hash-vectors"))
from compute import eval_hash as reference_hash  # noqa: E402
sys.path.insert(0, SUITE)
from check_schema_copies import results as schema_copy_results  # noqa: E402

MISSING = object()
LLM_ENV = {"OES_LLM_COMMAND": "python3 fake_llm.py", "OES_JUDGE_MODEL": "fake-judge-1", "OES_USER_MODEL": "fake-user-1"}
CONTROLLED = {*LLM_ENV, "OES_RETRIES"}  # the suite sets these; any other variable reaches the runner as it is
RUN_FLAGS = ["--agent-version", "v-conformance", "--agent-model", "fake-agent"]


# ---------------------------------------------------------------- a small JSON Schema validator (the keywords result.schema.json uses)

TYPES = {"object": lambda v: isinstance(v, dict), "array": lambda v: isinstance(v, list), "string": lambda v: isinstance(v, str),
         "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
         "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
         "boolean": lambda v: isinstance(v, bool), "null": lambda v: v is None}


def schema_errors(v, s, at="$"):
    if "$ref" in s:
        s = RESULT_SCHEMA["$defs"][s["$ref"].split("/")[-1]]
    errs = []
    if "type" in s:
        types = s["type"] if isinstance(s["type"], list) else [s["type"]]
        if not any(TYPES[t](v) for t in types):
            return [f"{at}: expected {'/'.join(types)}, got {json.dumps(v)[:60]}"]
    if "enum" in s and v not in s["enum"]:
        errs.append(f"{at}: {v!r} not in {s['enum']}")
    if isinstance(v, str):
        if len(v) < s.get("minLength", 0):
            errs.append(f"{at}: too short")
        if "pattern" in s and not re.search(s["pattern"], v):
            errs.append(f"{at}: {v!r} does not match {s['pattern']}")
    if TYPES["number"](v):
        if v < s.get("minimum", -math.inf) or v > s.get("maximum", math.inf):
            errs.append(f"{at}: {v} out of range")
    if isinstance(v, dict):
        errs += [f"{at}: missing {k}" for k in s.get("required", []) if k not in v]
        for k, x in v.items():
            sub = s.get("properties", {}).get(k, s.get("additionalProperties"))
            if isinstance(sub, dict):
                errs += schema_errors(x, sub, f"{at}.{k}")
    if isinstance(v, list) and "items" in s:
        for i, x in enumerate(v):
            errs += schema_errors(x, s["items"], f"{at}.{i}")
    if "anyOf" in s and all(schema_errors(v, b, at) for b in s["anyOf"]):
        errs.append(f"{at}: matches none of anyOf")
    if "oneOf" in s and sum(not schema_errors(v, b, at) for b in s["oneOf"]) != 1:
        errs.append(f"{at}: must match exactly one of oneOf; " + "; ".join(e for b in s["oneOf"] for e in schema_errors(v, b, at))[:300])
    if "not" in s and not schema_errors(v, s["not"], at):
        errs.append(f"{at}: matches a 'not' schema")
    return errs


# ---------------------------------------------------------------- comparing values

def get(obj, path):
    for seg in path.split(".") if path else []:
        if isinstance(obj, dict) and seg in obj:
            obj = obj[seg]
        elif isinstance(obj, list) and seg.isdigit() and int(seg) < len(obj):
            obj = obj[int(seg)]
        else:
            return MISSING
    return obj


def same(a, b):
    """Deep JSON equality, numbers within 0.1% (expected values are written rounded)."""
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b
    if TYPES["number"](a) and TYPES["number"](b):
        return math.isclose(a, b, rel_tol=1e-3, abs_tol=1e-9)
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(same(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(map(same, a, b))
    return type(a) is type(b) and a == b


def mismatch(actual, want, where):
    """Return a message if actual doesn't match want; want may be {"$absent"}, {"$len": n} or {"$set": [...]}."""
    show = lambda v: "absent" if v is MISSING else json.dumps(v)[:120]
    if isinstance(want, dict) and "$absent" in want:
        return None if actual is MISSING else f"{where}: should be absent, got {show(actual)}"
    if isinstance(want, dict) and "$len" in want:
        ok = isinstance(actual, (list, dict, str)) and len(actual) == want["$len"]
        return None if ok else f"{where}: want length {want['$len']}, got {show(actual)}"
    if isinstance(want, dict) and "$set" in want:
        ok = isinstance(actual, list) and sorted(map(str, actual)) == sorted(want["$set"]) and len(set(actual)) == len(actual)
        return None if ok else f"{where}: want a list of {want['$set']} in any order, got {show(actual)}"
    return None if actual is not MISSING and same(actual, want) else f"{where}: want {show(want)}, got {show(actual)}"


def file_objects(x):
    if isinstance(x, dict):
        return [x] if x.get("type") == "file" and isinstance(x.get("path"), str) else [f for v in x.values() for f in file_objects(v)]
    return [f for v in x for f in file_objects(v)] if isinstance(x, list) else []


# ---------------------------------------------------------------- driving the runner

class Suite:
    def __init__(self, runner, root, verbose):
        self.runner, self.root, self.verbose = runner, root, verbose
        self.results, self.run_ids = [], set()

    def record(self, name, problems, detail=""):
        self.results.append((name, not problems, problems[0] if problems else detail))
        if problems and self.verbose:
            for p in problems[1:]:
                print(f"      {name}: {p}", file=sys.stderr)

    def runs_dir(self):
        d = os.path.join(self.root, ".oes", "runs")
        return set(os.listdir(d)) if os.path.isdir(d) else set()

    def invoke(self, verb, eval_rel, env_over=None):
        env = {k: v for k, v in os.environ.items() if k not in CONTROLLED}
        env.update(LLM_ENV)
        for k, v in (env_over or {}).items():
            env.pop(k, None) if v is None else env.__setitem__(k, v)
        counters = os.path.join(self.root, ".counters")
        shutil.rmtree(counters, ignore_errors=True)
        os.makedirs(counters)
        before = self.runs_dir()
        cmd = self.runner + [verb, eval_rel] + (RUN_FLAGS if verb == "run" else [])
        try:
            p = subprocess.run(cmd, cwd=self.root, env=env, capture_output=True, text=True, timeout=900)
            code, out, err = p.returncode, p.stdout, p.stderr
        except subprocess.TimeoutExpired:
            code, out, err = "timeout", "", "the runner took over 900 s"
        if self.verbose and code not in (0, 1, 2):
            print(err[-2000:], file=sys.stderr)
        return {"exit": code, "stdout": out, "stderr": err, "new_runs": self.runs_dir() - before}

    def load_run(self, r, eval_rel):
        """Check the run folder and result against SPEC 8; return (result, rows, problems)."""
        lines = [ln for ln in r["stdout"].splitlines() if ln.strip()]
        run_dir = lines[-1].strip() if lines else ""
        if not (os.path.isabs(run_dir) and os.path.isfile(os.path.join(run_dir, "result.json"))):
            return None, None, [f"exit {r['exit']}; last stdout line is not a run folder: {run_dir[:150]!r}; stderr: {r['stderr'][-300:]!r}"]
        problems, r["run_dir"] = [], run_dir
        if os.path.dirname(os.path.realpath(run_dir)) != os.path.realpath(os.path.join(self.root, ".oes", "runs")):
            problems.append(f"run folder is not in .oes/runs/ of the repository root: {run_dir}")
        result = json.load(open(os.path.join(run_dir, "result.json")))
        rows = [json.loads(ln) for ln in open(os.path.join(run_dir, "rows.jsonl")) if ln.strip()]
        problems += [f"result.json: {e}" for e in schema_errors(result, RESULT_SCHEMA)]
        for i, row in enumerate(rows):
            problems += [f"row {i + 1}: {e}" for e in schema_errors(row, {"$ref": "#/$defs/row"})]
        if not problems:
            name = os.path.basename(eval_rel)[: -len(".eval.yaml")]
            rid = result["run_id"]
            problems += [m for m in (
                mismatch(result["eval"], name, "eval"),
                None if os.path.basename(run_dir) == rid else f"run folder {os.path.basename(run_dir)} is not named after run_id {rid}",
                None if rid not in self.run_ids else f"run_id {rid} was used before",
                mismatch(result["agent_version"], "v-conformance", "agent_version"),
                mismatch(result["models"]["agent"], "fake-agent", "models.agent"),
                None if r["exit"] == (0 if result["status"] == "passed" else 1) else f"exit {r['exit']} for status {result['status']}",
                None if len({(x["case_id"], x["trial"]) for x in rows}) == len(rows) else "two rows share a case_id and trial",
            ) if m]
            self.run_ids.add(rid)
        return result, rows, problems

    def check_expected(self, key, e):
        verb, eval_rel = e.get("verb", "run"), e["eval"]
        r = self.invoke(verb, eval_rel, e.get("env"))
        want_exit = e.get("exit", 0 if e.get("status") == "passed" else 1)
        problems = [] if r["exit"] == want_exit else [f"exit {r['exit']}, want {want_exit}; stderr: {r['stderr'][-300:]!r}"]
        if verb == "validate" or want_exit == 2:
            if r["new_runs"]:
                problems.append(f"wrote a run folder: {sorted(r['new_runs'])}")
            self.record(key, problems)
            return None
        result, rows, more = self.load_run(r, eval_rel)
        problems += more
        if result is None or more:
            self.record(key, problems)
            return result
        problems += [m for m in [mismatch(result["status"], e["status"], "status")] if m]
        if "cases" in e:
            problems += [m for m in (mismatch(result["cases"]["total"], e["cases"]["total"], "cases.total"),
                                     mismatch(result["cases"]["errored"], e["cases"]["errored"], "cases.errored")) if m]
        for name, fields in e.get("scores", {}).items():
            for field, want in fields.items():
                m = mismatch(get(result["scores"], f"{name}.{field}"), want, f"scores.{name}.{field}")
                problems += [m] if m else []
        for path, want in e.get("result", {}).items():
            problems += [m for m in [mismatch(get(result, path), want, path)] if m]
        if "n_rows" in e and len(rows) != e["n_rows"]:
            problems.append(f"{len(rows)} rows, want {e['n_rows']}")
        for want in e.get("rows", []):
            row = next((x for x in rows if x["case_id"] == want["case_id"] and x["trial"] == want["trial"]), None)
            where = f"row {want['case_id']}#{want['trial']}"
            if row is None:
                problems.append(f"{where}: missing")
                continue
            for path, v in want["facts"].items():
                problems += [m for m in [mismatch(get(row, path), v, f"{where} {path}")] if m]
        for special in e.get("checks", []):
            problems += getattr(self, special)(rows, r)
        for name, n in e.get("counters", {}).items():
            path = os.path.join(self.root, ".counters", name)
            got = int(open(path).read()) if os.path.exists(path) else 0
            problems += [] if got == n else [f"counter {name}: {got} calls, want {n}"]
        self.record(key, problems, f"status {result['status']}")
        return result

    def files_in_run_dir(self, rows, r):
        problems, seen = [], {}
        run_dir = r["run_dir"]
        for row in rows:
            paths = {f["path"] for k in ("message", "messages", "data", "script") for f in file_objects(row["input"].get(k))}
            for p in paths:
                if not (os.path.isabs(p) and os.path.realpath(p).startswith(os.path.realpath(run_dir) + os.sep) and os.path.exists(p)):
                    problems.append(f"row {row['case_id']}#{row['trial']}: {p} is not an existing copy inside the run folder")
            for other, ps in seen.get(row["case_id"], []):
                if ps & paths:
                    problems.append(f"case {row['case_id']}: trials {other} and {row['trial']} share a copy")
            seen.setdefault(row["case_id"], []).append((row["trial"], paths))
        return problems

    def fixture_untouched(self, rows, r):
        log = os.path.join(self.root, "evals", "fixtures", "workdir", "log.txt")
        return [f"the agent changed the source fixture: {log} exists"] if os.path.exists(log) else []

    def hash_of(self, eval_rel):
        r = self.invoke("run", eval_rel)
        result, _, problems = self.load_run(r, eval_rel)
        return (result or {}).get("eval_hash"), problems


def edit(path, fn):
    old = open(path).read()
    open(path, "w").write(fn(old))
    return lambda: open(path, "w").write(old)


def main(argv):
    only, keep, verbose = None, False, False
    while argv and argv[0] in ("--only", "--keep", "-v"):
        flag = argv.pop(0)
        only = argv.pop(0) if flag == "--only" else only
        keep, verbose = keep or flag == "--keep", verbose or flag == "-v"
    if not argv:
        sys.exit(__doc__)
    runner = [os.path.abspath(a) if os.path.exists(a) and not a.startswith("-") else a for a in argv]
    root = os.path.join(tempfile.mkdtemp(prefix="oes-conformance-"), "repo")
    shutil.copytree(SUITE, root, ignore=shutil.ignore_patterns(".oes", ".counters", "__pycache__", "expected", "run.py", "check_schema_copies.py", "*.md", "READY"))
    for junk in ("hash-vectors/v2/checks/__pycache__/score.cpython-312.pyc", "hash-vectors/v2/checks/.DS_Store",
                 "hash-vectors/v2/checks/stale.pyc", "hash-vectors/v3/fixtures/folder/.DS_Store",
                 "hash-vectors/v3/fixtures/folder/__pycache__/x.pyc", "hash-vectors/v4/checks/lib/__pycache__/helper.cpython-312.pyc"):
        os.makedirs(os.path.dirname(os.path.join(root, junk)), exist_ok=True)
        open(os.path.join(root, junk), "wb").write(b"junk that 8.2 leaves out")
    with socket.socket() as s:
        if s.connect_ex(("127.0.0.1", 8811)) == 0:
            sys.exit("port 8811 is in use; stop whatever is listening there and try again")
    server = subprocess.Popen([sys.executable, "serve.py"], cwd=root)
    for _ in range(100):
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", 8811)) == 0:
                break
        time.sleep(0.05)
    suite = Suite(runner, root, verbose)
    hashes = {}
    try:
        for fn in sorted(os.listdir(os.path.join(SUITE, "expected"))):
            key = fn[:-5]
            if only and only not in key:
                continue
            print(f"  ... {key}", file=sys.stderr, flush=True)
            result = suite.check_expected(key, json.load(open(os.path.join(SUITE, "expected", fn))))
            if result and "." not in key:
                hashes[key] = result.get("eval_hash")
        for fn in sorted(os.listdir(os.path.join(root, "evals", "invalid"))):
            if not fn.endswith(".eval.yaml") or (only and only not in "invalid/" + fn):
                continue
            rel = f"evals/invalid/{fn}"
            v, r = suite.invoke("validate", rel), suite.invoke("run", rel)
            problems = [f"{verb} exit {x['exit']}, want 2" for verb, x in (("validate", v), ("run", r)) if x["exit"] != 2]
            problems += ["run wrote a run folder"] * bool(r["new_runs"])
            problems += ["the runner called the target"] * os.path.exists(os.path.join(root, ".counters", "INVALID-EVAL-RAN"))
            msg = (v["stderr"].strip().splitlines() or [""])[-1][:90]
            suite.record(f"invalid/{fn[:-10]}", problems, msg)
        vectors = json.load(open(os.path.join(SUITE, "hash-vectors", "vectors.json")))
        for name, vec in vectors.items():
            if only and only not in name:
                continue
            base = os.path.join(root, "hash-vectors", os.path.dirname(vec["eval"]))
            if reference_hash(base, vec["uses"]) != vec["eval_hash"]:
                suite.record(f"hash/{name}", ["the suite's own vectors.json is out of date (run hash-vectors/compute.py)"])
                continue
            got, problems = suite.hash_of(f"hash-vectors/{vec['eval']}")
            suite.record(f"hash/{name}", problems or [m for m in [mismatch(got, vec["eval_hash"], "eval_hash")] if m], got[:20] if got else "")
        if not only or "hash-change" in only:
            for key, eval_rel, path, change in (
                    ("z08-custom", "evals/z08-custom.eval.yaml", None, None),
                    ("z08-custom", "evals/z08-custom.eval.yaml", "evals/checks/close_enough.py", lambda s: s + "\n# edited\n"),
                    ("z11-files", "evals/z11-files.eval.yaml", "evals/fixtures/note.txt", lambda s: s + "edited\n"),
                    ("z15-judges", "evals/z15-judges.eval.yaml", "evals/judges/polite.judge.yaml", lambda s: s + "  Be fair.\n")):
                undo = edit(os.path.join(root, path), change) if path else None
                try:
                    got, problems = suite.hash_of(eval_rel)
                finally:
                    undo and undo()
                before = hashes.get(key)
                what = f"edit {path}" if path else "same files"
                if not problems and (before is None or got is None):
                    problems = [f"no hash to compare (first run: {before}, this run: {got})"]
                elif not problems and (got == before) != (path is None):
                    problems = [f"{what}: hash {'changed' if path is None else 'did not change'}"]
                suite.record(f"hash-change/{key}: {what}", problems)
    finally:
        server.kill()
        shutil.rmtree(os.path.dirname(root), ignore_errors=True) if not keep else print(f"kept {root}", file=sys.stderr)
    if not only or "schema-copies" in only:
        for name, problems in schema_copy_results().items():
            suite.record(f"schema-copies/{name}", problems, "same bytes as skills/oes/")
    width = max(len(n) for n, _, _ in suite.results)
    print(f"{'check':{width}}  result  detail")
    for name, ok, detail in suite.results:
        print(f"{name:{width}}  {'pass' if ok else 'FAIL'}    {detail}")
    failed = sum(not ok for _, ok, _ in suite.results)
    print(f"\n{len(suite.results) - failed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
