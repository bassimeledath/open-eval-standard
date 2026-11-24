#!/usr/bin/env python3
"""Open Eval Standard (OES) reference runner, following skills/oes/SPEC.md (version 1, draft 5).

  oes run <name.eval.yaml> [--agent-version LABEL] [--agent-model NAME]
  oes validate <name.eval.yaml>

Run it from the repository root. Judges and simulated users are reached through OES_LLM_COMMAND (see README.md).
"""
import argparse, copy, datetime as dt, hashlib, json, math, os, re, secrets, shutil, signal
import socket, subprocess, sys, time, urllib.error, urllib.request, uuid
from pathlib import Path

import jsonschema
from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError
from ruamel.yaml.resolver import BaseResolver

RUNNER = {"name": "oes-python", "version": "0.1.0"}
DEFAULT_TIMEOUT_S = 300            # targets, custom checks and LLM calls without timeout_s
RUN_CHECKS = {"latency_p95_ms", "cost_per_trial_usd"}
ROOTS = {"reply", "data", "state", "tool_calls", "turns"}
DEFAULT_CHOICES = {"pass": 1, "fail": 0}
JUDGE_FIELDS = {"name", "prompt", "choices", "model"}
EPS = 1e-9                         # rounding allowance for pass rules (section 6)
MISSING = object()


class Invalid(Exception):
    """The eval is invalid; args[0] is a list of reasons."""


class Fail(Exception):
    """A trial or scorer failed for a reason outside the agent's logic (section 8.1)."""
    def __init__(self, kind, msg):
        super().__init__(msg)
        self.kind = kind


def log(*a):
    print(*a, file=sys.stderr, flush=True)


# ---------------------------------------------------------------- YAML 1.2 core schema (section 3)

class CoreResolver(BaseResolver):
    """Exactly the YAML 1.2 core schema: no dates, no yes/no booleans, no underscores in numbers."""
    processing_version = (1, 2)

    def __init__(self, version=None, loader=None):
        super().__init__(loader)


for _tag, _rx, _first in [
        ("bool", r"^(?:true|True|TRUE|false|False|FALSE)$", "tTfF"),
        ("int", r"^(?:[-+]?[0-9]+|0o[0-7]+|0x[0-9a-fA-F]+)$", "-+0123456789"),
        ("float", r"^(?:[-+]?(?:\.[0-9]+|[0-9]+(?:\.[0-9]*)?)(?:[eE][-+]?[0-9]+)?|[-+]?\.(?:inf|Inf|INF)|\.(?:nan|NaN|NAN))$",
         "-+.0123456789"),
        ("null", r"^(?:~|null|Null|NULL|)$", ["~", "n", "N", ""])]:
    CoreResolver.add_implicit_resolver("tag:yaml.org,2002:" + _tag, re.compile(_rx), list(_first))


def no_infinities(x, where):
    """Rule 9.2: reject values JSON can't hold, such as .inf and .nan."""
    if isinstance(x, float) and not math.isfinite(x):
        raise Invalid([f"{where}: {x} is not a value JSON can hold"])
    for v in x.values() if isinstance(x, dict) else x if isinstance(x, list) else []:
        no_infinities(v, where)
    return x


def load_yaml(path):
    """One YAML document; duplicate keys and extra documents are errors."""
    y = YAML(typ="safe", pure=True)
    y.Resolver = CoreResolver
    try:
        return no_infinities(y.load(Path(path).read_text(encoding="utf-8")), path)
    except (OSError, UnicodeDecodeError, YAMLError) as e:
        raise Invalid([f"{path}: {e}"])


def strict_pairs(pairs):
    keys = [k for k, _ in pairs]
    dup = next((k for k in keys if keys.count(k) > 1), None)
    if dup is not None:
        raise ValueError(f"duplicate key {dup!r}")
    return dict(pairs)


def load_case_line(line):
    """A cases file line: JSON with no duplicate keys and no NaN or Infinity."""
    return json.loads(line, object_pairs_hook=strict_pairs,
                      parse_constant=lambda c: (_ for _ in ()).throw(ValueError(f"{c} is not a value JSON can hold")))


# ---------------------------------------------------------------- loading and validation (sections 3, 5, 6, 7, 9)

def schema(name):
    """Load a schema from OES_SCHEMA_DIR, or else from the copies bundled with the runner (oes_schemas/)."""
    d = Path(os.environ.get("OES_SCHEMA_DIR") or Path(__file__).resolve().parent / "oes_schemas")
    try:
        return json.loads((d / name).read_text())
    except (OSError, ValueError) as e:
        raise SystemExit(f"oes: cannot read {d / name}: {e}")


def schema_errors(doc, name, where=""):
    out = []
    for e in sorted(jsonschema.Draft202012Validator(schema(name)).iter_errors(doc), key=lambda e: list(map(str, e.absolute_path))):
        while e.context:  # oneOf/anyOf: report the deepest branch's error, not "valid under none"
            e = max(e.context, key=lambda c: (len(c.absolute_path), c.validator != "type"))
        msg = "at least one scorer must have a pass rule" if e.validator == "contains" else e.message
        out.append(f"{where}{'/'.join(map(str, e.absolute_path)) or '<root>'}: {msg[:300]}")
    return out


def is_file_obj(x):
    return isinstance(x, dict) and x.get("type") == "file" and isinstance(x.get("path"), str)


def map_files(x, fn):
    """Return a copy of x with every {type: file, path} object replaced by fn(obj)."""
    if is_file_obj(x):
        return fn(x)
    if isinstance(x, dict):
        return {k: map_files(v, fn) for k, v in x.items()}
    if isinstance(x, list):
        return [map_files(v, fn) for v in x]
    return x


FILE_KEYS = ("message", "messages", "data", "script")  # where files can go (4.2)


def input_files(inp):
    found = []
    for k in FILE_KEYS:
        if k in inp:
            map_files(inp[k], lambda f: found.append(f["path"]) or f)
    return found


def valid_path(p):
    return isinstance(p, str) and p.split(".")[0] in ROOTS and all(p.split("."))


def check_expected(check, exp):
    """Shape of a built-in check's expected entry; returns an error string or None."""
    if isinstance(exp, list) and not exp:
        return "must not be an empty list"
    texts = isinstance(exp, list) and all(isinstance(t, str) for t in exp)
    if check == "equals":
        if not isinstance(exp, dict) or not exp:
            return "must be a map of output paths to values"
        bad = [p for p in exp if not valid_path(p)]
        return f"bad output path(s) {bad}; a path starts with one of {sorted(ROOTS)}" if bad else None
    if check in ("reply_contains", "reply_not_contains", "tool_not_called"):
        return None if texts else "must be a list of texts"
    if check == "tool_called":
        ok = isinstance(exp, list) and all(
            isinstance(t, str) or (isinstance(t, dict) and isinstance(t.get("name"), str)
                                   and set(t) <= {"name", "args"} and isinstance(t.get("args", {}), dict))
            for t in exp)
        return None if ok else "must be a list of tool names or {name, args} objects"
    return None


def load_judge(base, name, errs):
    path = base / "judges" / f"{name}.judge.yaml"
    if not path.is_file():
        errs.append(f"judge '{name}': file not found: {path}")
        return None
    try:
        j = load_yaml(path)
    except Invalid as e:
        errs.extend(e.args[0])
        return None
    bad = schema_errors(j, "judge.schema.json", f"judge file {path.name}: ")
    if isinstance(j, dict) and set(j) - JUDGE_FIELDS:
        bad.insert(0, f"judge file {path.name}: fields other than {sorted(JUDGE_FIELDS)}: {sorted(set(j) - JUDGE_FIELDS)}")
    elif isinstance(j, dict) and j.get("name") != name:
        bad.append(f"judge file {path.name}: name must be '{name}', got {j.get('name')!r}")
    errs.extend(bad)
    return j


def load_eval(path):
    path = Path(path).resolve()
    base = path.parent
    doc = load_yaml(path)
    errs = schema_errors(doc, "eval.schema.json", "schema: ")
    if errs:
        raise Invalid(errs)
    files = [path]
    cases = doc["cases"]
    if isinstance(cases, dict):
        cf = (base / cases["file"]).resolve()
        files.append(cf)
        try:
            cases = [load_case_line(ln) for ln in cf.read_text(encoding="utf-8").splitlines() if ln.strip()]
        except (OSError, UnicodeDecodeError, ValueError) as e:
            raise Invalid([f"cases file {cf}: {e}"])
        errs = schema_errors({**doc, "cases": cases}, "eval.schema.json", f"cases file {cf.name}: ")
        if errs:
            raise Invalid(errs)
    scorers = doc["scorers"]
    for kind, seq in (("test case id", [c["id"] for c in cases]), ("scorer name", [s["name"] for s in scorers])):
        errs += [f"two test cases or scorers share the {kind} '{x}'" for x in sorted({x for x in seq if seq.count(x) > 1})]
    by_name = {s["name"]: s for s in scorers}
    judges = {}
    for s in scorers:
        if "judge" in s and s["judge"] not in judges:
            judges[s["judge"]] = load_judge(base, s["judge"], errs)
            files.append(base / "judges" / f"{s['judge']}.judge.yaml")
    for c in cases:
        for key, exp in (c.get("expected") or {}).items():
            s = by_name.get(key)
            if s is None:
                errs.append(f"case '{c['id']}': expected key '{key}' names no scorer")
            elif exp is not None and isinstance(s.get("check"), str):
                bad = check_expected(s["check"], exp)
                errs += [f"case '{c['id']}': expected.{key} ({s['check']}): {bad}"] if bad else []
        stops = c["input"].get("stop_when", [])
        for m in [stops] if isinstance(stops, dict) else stops:
            errs += [f"case '{c['id']}': stop_when: bad output path '{p}'" for p in m if not valid_path(p)]
        for p in input_files(c["input"]):
            fp = (base / p).resolve()
            errs += [] if fp.exists() else [f"case '{c['id']}': input file not found: {p}"]
            files.append(fp)
    if errs:
        raise Invalid(errs)
    return {"path": path, "base": base, "doc": doc, "cases": cases, "scorers": scorers, "judges": judges, "files": files}


def is_run_scorer(s):
    return (isinstance(s.get("check"), str) and s["check"] in RUN_CHECKS) or s.get("scope") == "run"


def eval_hash(ev):
    """Section 8.2: sha256 over (path, 0, length, 0, bytes) of every file the eval uses, sorted by path bytes."""
    roots = set(ev["files"]) | ({ev["base"] / "checks"} if (ev["base"] / "checks").is_dir() else set())
    entries = {}
    for p in map(Path, roots):
        for f in ([Path(d) / n for d, _, ns in os.walk(p) for n in ns] if p.is_dir() else [p]):
            rel = Path(os.path.relpath(f, ev["base"])).as_posix()
            if f.is_file() and "__pycache__" not in rel.split("/") and not rel.endswith(".pyc") and f.name != ".DS_Store":
                entries[rel] = f
    h = hashlib.sha256()
    for rel in sorted(entries, key=lambda r: r.encode("utf-8")):
        data = entries[rel].read_bytes()
        h.update(rel.encode("utf-8") + b"\0" + str(len(data)).encode() + b"\0" + data)
    return "sha256:" + h.hexdigest()


# ---------------------------------------------------------------- calling commands, URLs and the LLM command (4.1)

def parse_obj(text, kind):
    """The whole output as one JSON object, or else its last non-empty line."""
    try:
        v = json.loads(text)
    except ValueError:
        lines = [ln for ln in text.splitlines() if ln.strip()]
        try:
            v = json.loads(lines[-1])
        except (ValueError, IndexError):
            raise Fail(kind, f"output is not JSON: {text.strip()[:300]!r}")
    if not isinstance(v, dict):
        raise Fail(kind, f"output is not a JSON object: {json.dumps(v)[:200]}")
    return v


def call_endpoint(ep, payload, kind):
    """Send payload as JSON to a {command} (stdin/stdout via /bin/sh, from the repository root) or an {http} URL."""
    timeout = ep.get("timeout_s", DEFAULT_TIMEOUT_S)
    body = json.dumps(payload)
    if "command" in ep:
        p = subprocess.Popen(["/bin/sh", "-c", ep["command"]], cwd=os.getcwd(), stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
        try:
            out, err = p.communicate(body, timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(p.pid, signal.SIGKILL)
            p.communicate()
            raise Fail("timeout", f"{kind} command timed out after {timeout}s")
        if p.returncode != 0:
            raise Fail(kind, f"{kind} command exited with code {p.returncode}: {err.strip()[-1000:]}")
        return parse_obj(out, kind)
    req = urllib.request.Request(ep["http"], data=body.encode(), method="POST", headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return parse_obj(r.read().decode("utf-8", "replace"), kind)
    except urllib.error.HTTPError as e:
        raise Fail(kind, f"{kind} URL returned HTTP {e.code}: {e.read()[:500].decode('utf-8', 'replace')}")
    except (TimeoutError, socket.timeout):
        raise Fail("timeout", f"{kind} URL timed out after {timeout}s")
    except urllib.error.URLError as e:
        if isinstance(e.reason, (TimeoutError, socket.timeout)):
            raise Fail("timeout", f"{kind} URL timed out after {timeout}s")
        raise Fail(kind, f"{kind} URL failed: {e.reason}")


def is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def llm(role, model, prompt):
    """One judge or simulated-user call through OES_LLM_COMMAND. Returns (text, cost in USD or None)."""
    res = call_endpoint({"command": os.environ["OES_LLM_COMMAND"]}, {"role": role, "model": model, "prompt": prompt}, role)
    if not isinstance(res.get("text"), str):
        raise Fail(role, "LLM command output has no text")
    if "cost_usd" in res and not is_number(res["cost_usd"]):
        raise Fail(role, "LLM command cost_usd is not a number")
    return res["text"], res.get("cost_usd")


def retries():
    return int(os.environ.get("OES_RETRIES", "2"))


def retry(fn, what):
    for i in range(retries() + 1):
        try:
            return fn()
        except Fail as e:
            if i == retries():
                raise
            log(f"  retrying {what} after {e.kind} error: {e}")
            time.sleep(0.2 * (i + 1))


def add_cost(a, b):
    return a if b is None else (a or 0) + b


# ---------------------------------------------------------------- running a trial (sections 4 and 5)

def check_response(r):
    if "reply" in r and not isinstance(r["reply"], str):
        raise Fail("target", "response 'reply' is not text")
    if "state" in r and not isinstance(r["state"], dict):
        raise Fail("target", "response 'state' is not an object")
    tc = r.get("tool_calls", [])
    if not (isinstance(tc, list) and all(isinstance(c, dict) and isinstance(c.get("name"), str) for c in tc)):
        raise Fail("target", "response 'tool_calls' is not a list of objects with a text 'name'")
    if "cost_usd" in r and not is_number(r["cost_usd"]):
        raise Fail("target", "response 'cost_usd' is not a number")


def make_output(conv):
    turns = conv["turns"]
    out = {"transcript": conv["transcript"],
           "tool_calls": [{**c, "turn": i + 1} for i, t in enumerate(turns) for c in t.get("tool_calls", [])],
           "turns": turns}
    for k in ("reply", "data", "state"):
        if turns and k in turns[-1]:
            out[k] = turns[-1][k]
    return out


def content_text(c):
    if isinstance(c, str):
        return c
    return " ".join(p["text"] if p.get("type") == "text" else f"[file: {p.get('path')}]" for p in c)


def render(msgs, user="USER", agent="AGENT"):
    return "\n\n".join(f"{user if m['role'] == 'user' else agent}: {content_text(m['content'])}" for m in msgs) or "(nothing yet)"


def simulated_user(persona, transcript):
    prompt = (
        "You are role-playing a user who is talking to an AI agent, so that the agent can be tested.\n\n"
        f"# Who you are\n{persona}\n\n"
        f"# The conversation so far\n{render(transcript, 'YOU', 'AGENT')}\n\n"
        "# Your task\nWrite the user's next message, in character. Reply with only the message text: no quotes, labels "
        "or commentary. If the user would now end the conversation (their goal is met, they give up, or the persona "
        "says to stop), reply with exactly [done] and nothing else.")
    text, cost = llm("user", os.environ.get("OES_USER_MODEL"), prompt)
    text = text.strip()
    if not text:
        raise Fail("user", "the simulated user returned an empty message")
    return (None if text == "[done]" else text), cost


def converse(ev, inp, sid, conv):
    """Run the turns of one trial attempt, filling conv as it goes (so a failed attempt keeps what happened)."""
    tr = conv["transcript"]
    if "messages" in inp:
        tr.extend(copy.deepcopy(inp["messages"]))
    elif "message" in inp:
        tr.append({"role": "user", "content": copy.deepcopy(inp["message"])})
    base, state = inp.get("data", {}), inp.get("state", {})
    script, persona = list(inp.get("script", [])), inp.get("persona")
    max_turns = inp.get("max_turns", math.inf) if (script or persona) else 1
    stops = inp.get("stop_when", [])
    stops = [stops] if isinstance(stops, dict) else stops

    def next_user():
        text, cost = simulated_user(persona, tr)
        conv["user_cost"] = add_cost(conv["user_cost"], cost)
        if text is not None:
            tr.append({"role": "user", "content": text})
        return text is not None

    def next_script():
        item = script.pop(0)
        if not isinstance(item, dict):
            item = {"message": item}
        if "message" in item:
            tr.append({"role": "user", "content": copy.deepcopy(item["message"])})
        return {**base, **item.get("data", {})}

    data, ready = base, True
    if persona and (not tr or tr[-1]["role"] == "assistant"):
        ready = next_user()                      # the simulated user speaks first
    elif script and not any(k in inp for k in ("message", "messages", "data")):
        data = next_script()                     # the first script item is the first turn
    while ready:
        req = {"session_id": sid, "messages": copy.deepcopy(tr), "data": data, "state": state}
        t0 = time.monotonic()
        resp = call_endpoint(ev["doc"]["target"], req, "target")
        resp = {k: v for k, v in resp.items() if v is not None}  # a field set to null counts as absent
        check_response(resp)  # an invalid response errors the trial and isn't logged as a turn
        conv["latency"].append(round((time.monotonic() - t0) * 1000, 1))
        conv["turns"].append(resp)
        conv["agent_cost"] = add_cost(conv["agent_cost"], resp.get("cost_usd"))
        if "reply" in resp:
            tr.append({"role": "assistant", "content": resp["reply"]})
        state = resp.get("state", {})
        out = make_output(conv)
        if len(conv["turns"]) >= max_turns or any(all(same(get_path(out, p), v) for p, v in m.items()) for m in stops):
            break
        if script:
            data = next_script()
        elif persona:
            ready = next_user()
        else:
            break


def copy_inputs(ev, case, dest):
    """Give one trial attempt its own copy of every file input; return the input with the copies' absolute paths."""
    shutil.rmtree(dest, ignore_errors=True)
    copies = {}

    def cp(f):
        src = (ev["base"] / f["path"]).resolve()
        if src not in copies:
            target = dest / str(len(copies) + 1) / src.name
            target.parent.mkdir(parents=True, exist_ok=True)
            (shutil.copytree if src.is_dir() else shutil.copy2)(src, target)
            copies[src] = str(target)
        return {**f, "path": copies[src]}

    inp = copy.deepcopy(case["input"])
    for k in FILE_KEYS:
        if k in inp:
            inp[k] = map_files(inp[k], cp)
    return inp


def run_trial(ev, index, case, trial, run_dir):
    dest = run_dir / "files" / f"{index + 1}-{re.sub(r'[^A-Za-z0-9_.-]', '_', case['id'])}.{trial}"
    for attempt in range(1, retries() + 2):
        sid = str(uuid.uuid4())
        inp = copy_inputs(ev, case, dest)
        conv = {"transcript": [], "turns": [], "latency": [], "agent_cost": None, "user_cost": None}
        err = None
        try:
            converse(ev, inp, sid, conv)
            break
        except Fail as e:
            err = e
            if attempt <= retries():
                log(f"  retrying trial after {e.kind} error: {e}")
                time.sleep(0.2 * attempt)
    row = {"case_id": case["id"], "trial": trial, "session_id": sid, "attempts": attempt, "tags": case.get("tags", []),
           "input": inp, "expected": case.get("expected") or {}, "output": make_output(conv), "scores": {},
           "latency_ms": conv["latency"], "cost_usd": {"agent": conv["agent_cost"], "judges": None, "user": conv["user_cost"]}}
    if err is None:
        try:
            for sc in ev["scorers"]:
                if is_run_scorer(sc) or not conv["turns"]:  # no turns: the simulated user ended first, so no scores
                    continue
                res, cost = retry(lambda: score_trial(ev, sc, row), f"scorer '{sc['name']}'")
                row["cost_usd"]["judges"] = add_cost(row["cost_usd"]["judges"], cost)
                row["scores"][sc["name"]] = res
        except Fail as e:
            err, row["scores"] = e, {}
    if err is not None:
        row["error"] = {"kind": err.kind, "message": str(err)}
    row["cost_usd"] = {k: None if v is None else round(v, 10) for k, v in row["cost_usd"].items()}
    return row


# ---------------------------------------------------------------- scoring (sections 6 and 7)

def get_path(out, path):
    cur = out
    for seg in path.split("."):
        if isinstance(cur, dict) and seg in cur:
            cur = cur[seg]
        elif isinstance(cur, list) and seg.isascii() and seg.isdigit() and int(seg) < len(cur):
            cur = cur[int(seg)]
        else:
            return MISSING
    return cur


def same(a, b):
    """JSON equality: deep, key order ignored, 1 == 1.0, no other conversion between types."""
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if is_number(a) and is_number(b):
        return a == b
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(same(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b))
    return type(a) is type(b) and a == b


def show(v):
    return "missing" if v is MISSING else json.dumps(v)[:200]


def builtin(check, exp, out):
    replies = [t["reply"].casefold() for t in out["turns"] if isinstance(t.get("reply"), str)]
    calls = out["tool_calls"]
    if check == "equals":
        bad = [f"{p}: expected {show(v)}, got {show(get_path(out, p))}" for p, v in exp.items() if not same(get_path(out, p), v)]
    elif check == "reply_contains":
        bad = [f"no reply contains {t!r}" for t in exp if not any(t.casefold() in r for r in replies)]
    elif check == "reply_not_contains":
        bad = [f"a reply contains {t!r}" for t in exp if any(t.casefold() in r for r in replies)]
    elif check == "tool_called":
        def hit(want, c):
            args = c.get("args") if isinstance(c.get("args"), dict) else {}
            return c["name"] == want["name"] and all(k in args and same(args[k], v) for k, v in want.get("args", {}).items())
        wants = [{"name": t} if isinstance(t, str) else t for t in exp]
        bad = [f"{json.dumps(w)} was not called" for w in wants if not any(hit(w, c) for c in calls)]
    else:  # tool_not_called
        bad = [f"{t} was called" for t in exp if any(c["name"] == t for c in calls)]
    return {"score": 0 if bad else 1, "reason": "; ".join(bad) or "all matched"}


def judge_model(j):
    return j.get("model") or os.environ.get("OES_JUDGE_MODEL") or None


def judge(ev, sc, row, exp):
    j = ev["judges"][sc["judge"]]
    choices = j.get("choices", DEFAULT_CHOICES)
    out = {k: v for k, v in row["output"].items() if k != "transcript"}
    prompt = (
        "You are a careful grader of an AI agent's output.\n\n"
        f"# What to judge\n{j['prompt'].strip()}\n\n"
        f"# The test case input\n{json.dumps(row['input'], indent=2)}\n(Files are given by path only.)\n\n"
        f"# The transcript\n{render(row['output']['transcript'])}\n\n"
        f"# The agent's output\n{json.dumps(out, indent=2)}\n\n"
        + (f"# What is expected\n{json.dumps(exp, indent=2)}\n\n" if exp is not None else "")
        + "# How to answer\nAnswer with only a JSON object, giving your reason first: "
        f'{{"reason": "<one or two sentences>", "choice": "<one of: {", ".join(choices)}>"}}')
    text, cost = llm("judge", judge_model(j), prompt)
    try:
        ans = json.loads(text[text.index("{"):text.rindex("}") + 1])
        said = ans["choice"]
    except (ValueError, KeyError, TypeError):  # ValueError covers a missing brace too
        raise Fail("judge", f"judge answer is not JSON with a choice: {text[:300]!r}")
    choice = next((k for k in choices if isinstance(said, str) and k.lower() == said.strip().lower()), None)
    if choice is None:
        raise Fail("judge", f"judge choice {said!r} is not one of {list(choices)}")
    return {"score": choices[choice], "reason": str(ans.get("reason", "")), "choice": choice}, cost


def score_trial(ev, sc, row):
    """Score one logged row with one trial scorer. Returns (score entry, judge cost or None)."""
    exp = row["expected"].get(sc["name"])
    if "judge" in sc:
        return judge(ev, sc, row, exp)
    if isinstance(sc["check"], str):
        if exp is None:
            return {"score": None, "reason": "no expected entry: skipped"}, None
        return builtin(sc["check"], exp, row["output"]), None
    res = call_endpoint(sc["check"], {"input": row["input"], "output": row["output"], "expected": exp,
                                      "params": sc.get("params", {}), "session_id": row["session_id"]}, "check")
    s = res.get("score", MISSING)
    if not (s is None or (is_number(s) and 0 <= s <= 1)):
        raise Fail("check", f"a trial check must return a score from 0 to 1 or null, got {show(s)}")
    entry = {"score": s, "reason": res.get("reason")}
    if "value" in res:
        entry["value"] = res["value"]
    return entry, None


def percentile(vals, p):
    """Nearest rank: the value at position ceil(p/100 * n), counting from 1."""
    if not vals:
        return None
    s = sorted(vals)
    return s[max(1, math.ceil(p / 100 * len(s))) - 1]


def mean_cost(rows, role):
    """Agent: mean over trials that reported a cost. Judges, user: a trial with no call counts as 0."""
    vals = [r["cost_usd"][role] for r in rows if "error" not in r]
    known = [v for v in vals if v is not None]
    if not known:
        return None
    return sum(known) / (len(known) if role == "agent" else len(vals))


def run_score(sc, rows):
    """Score the whole run with one run scorer. Returns (value, reason)."""
    if sc.get("check") == "latency_p95_ms":
        return percentile([ms for r in rows if "error" not in r for ms in r["latency_ms"]], 95), None
    if sc.get("check") == "cost_per_trial_usd":
        return mean_cost(rows, "agent"), None
    res = call_endpoint(sc["check"], {"rows": rows, "params": sc.get("params", {})}, "check")
    v = res.get("score", MISSING)
    if not (v is None or is_number(v)):
        raise Fail("check", f"a run check must return a number or null, got {show(v)}")
    return v, res.get("reason")


def summarize(ev, rows, stopped):
    ok = [r for r in rows if "error" not in r]
    case_ids = [c["id"] for c in ev["cases"]]
    errored = [cid for cid in case_ids if any(r["case_id"] == cid and "error" in r for r in rows)]
    ran = {r["case_id"] for r in rows if "error" in r or r["output"]["turns"]}
    scores, gate = {}, []
    for sc in ev["scorers"]:
        rule = sc.get("pass")
        kind, x = next(iter(rule.items())) if rule else (None, None)
        if is_run_scorer(sc):
            try:
                value, reason = retry(lambda: run_score(sc, rows), f"run scorer '{sc['name']}'")
            except Fail as e:
                stopped, value, reason = True, None, f"error ({e.kind}): {e}"
            passed = None if rule is None or value is None else (value >= x - EPS if kind == "min" else value <= x + EPS)
            scores[sc["name"]] = {"value": value, "passed": passed, "reason": reason}
        else:
            per_case, skipped = {}, 0
            for r in ok:
                if sc["name"] not in r["scores"]:  # a trial that did not run counts as neither scored nor skipped
                    continue
                s = r["scores"][sc["name"]]["score"]
                if s is None:
                    skipped += 1
                else:
                    per_case.setdefault(r["case_id"], []).append(s)
            allv = [s for v in per_case.values() for s in v]
            value = sum(allv) / len(allv) if allv else None

            def short(v):
                return min(v) < x - EPS if kind == "each" else sum(v) / len(v) < x - EPS if kind == "mean" else min(v) < 1 - EPS
            passed = None if rule is None or value is None else (min(allv) >= x - EPS if kind == "each" else value >= x - EPS)
            scores[sc["name"]] = {"value": value, "passed": passed, "scored": len(allv), "skipped": skipped,
                                  "failing_cases": [c for c in case_ids if c in per_case and short(per_case[c])]}
        if rule:
            gate.append(scores[sc["name"]]["passed"])
    if stopped or errored:
        status = "error"
    elif any(cid not in ran for cid in case_ids) or any(p is None for p in gate):
        status = "not_evaluated"
    elif not all(gate):
        status = "failed"
    else:
        status = "passed"
    lat = [ms for r in ok for ms in r["latency_ms"]]
    return status, scores, errored, {"p50": percentile(lat, 50), "p95": percentile(lat, 95)}


# ---------------------------------------------------------------- commands (section 8.4)

def git_commit():
    try:
        p = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10)
        return (p.stdout.strip() or None) if p.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def report_invalid(path, e):
    log(f"invalid eval {path}:")
    for m in e.args[0]:
        log(f"  - {m}")
    return 2


def cmd_run(path, agent_version, agent_model):
    try:
        ev = load_eval(path)
    except Invalid as e:
        return report_invalid(path, e)
    try:
        if retries() < 0:
            raise ValueError
    except ValueError:
        log(f"OES_RETRIES must be a whole number of 0 or more, got {os.environ['OES_RETRIES']!r}")
        return 2
    uses_persona = any("persona" in c["input"] for c in ev["cases"])
    if (ev["judges"] or uses_persona) and not os.environ.get("OES_LLM_COMMAND"):
        log("this eval needs an LLM for its judges or simulated users: set OES_LLM_COMMAND (see the runner's README)")
        return 2
    started = dt.datetime.now(dt.timezone.utc)
    run_id = started.strftime("%Y%m%dT%H%M%SZ") + "-" + secrets.token_hex(4)
    run_dir = (Path.cwd() / ".oes" / "runs" / run_id).resolve()
    run_dir.mkdir(parents=True)
    rows, stopped = [], False
    try:
        for i, case in enumerate(ev["cases"]):
            for t in range(1, ev["doc"].get("trial_count", 1) + 1):
                row = run_trial(ev, i, case, t, run_dir)
                rows.append(row)
                log(f"[{case['id']} trial {t}] " + (f"error ({row['error']['kind']}): {row['error']['message']}" if "error" in row
                                                    else ", ".join(f"{k}={v['score']}" for k, v in row["scores"].items())))
    except KeyboardInterrupt:
        stopped = True
        log("interrupted: the run stopped")
    except Exception as e:  # a runner fault: keep what ran and mark the run as stopped
        stopped = True
        log(f"the run stopped: {type(e).__name__}: {e}")
    status, scores, errored, latency = summarize(ev, rows, stopped)
    jm = sorted({judge_model(j) for j in ev["judges"].values()} - {None})
    result = {
        "eval": ev["doc"]["name"], "run_id": run_id, "started_at": started.isoformat().replace("+00:00", "Z"),
        "runner": RUNNER, "tags": ev["doc"].get("tags", []), "metadata": ev["doc"].get("metadata", {}),
        "agent_version": agent_version if agent_version is not None else git_commit(),
        "models": {"agent": agent_model, "judge": (jm[0] if len(jm) == 1 else jm) or None,
                   "user": os.environ.get("OES_USER_MODEL") or None if uses_persona else None},
        "eval_hash": eval_hash(ev), "status": status, "scores": scores, "latency_ms": latency,
        "cost_usd": {k: mean_cost(rows, k) for k in ("agent", "judges", "user")},
        "cases": {"total": len(ev["cases"]), "errored": errored},
    }
    with open(run_dir / "rows.jsonl", "w", encoding="utf-8") as f:
        f.writelines(json.dumps(r) + "\n" for r in rows)
    (run_dir / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"{result['eval']}: {status}")
    for name, s in scores.items():
        print(f"  {name}: value={s['value']} passed={s['passed']}" + (f" failing={s['failing_cases']}" if s.get("failing_cases") else ""))
    print(run_dir)
    return 0 if status == "passed" else 1


def cmd_validate(path):
    try:
        load_eval(path)
    except Invalid as e:
        return report_invalid(path, e)
    log(f"valid: {path}")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="oes", description="Open Eval Standard runner")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="validate and run an eval")
    r.add_argument("eval")
    r.add_argument("--agent-version", default=None, help="label for the agent version (default: the git commit)")
    r.add_argument("--agent-model", default=None, help="the model the agent uses, recorded in models.agent")
    v = sub.add_parser("validate", help="check an eval and its judge files without calling anything")
    v.add_argument("eval")
    a = ap.parse_args(argv)
    return cmd_run(a.eval, a.agent_version, a.agent_model) if a.cmd == "run" else cmd_validate(a.eval)


if __name__ == "__main__":
    sys.exit(main())
