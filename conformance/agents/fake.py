"""Deterministic fake agents for the OES conformance suite. Stdlib only.

Command form:  python3 agents/fake.py <behavior>   (request JSON on stdin, response JSON on stdout)
HTTP form:     served by serve.py, which imports BEHAVIORS from here.
Counters live in .counters/ under the folder the agent runs from (the repository root).
"""
import fcntl, json, os, sys, time


def bump(name):
    """Increment a named counter and return the new value."""
    os.makedirs(".counters", exist_ok=True)
    with open(os.path.join(".counters", name), "a+") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.seek(0)
        n = int(f.read() or 0) + 1
        f.seek(0); f.truncate(); f.write(str(n))
    return n


def text_of(content):
    return content if isinstance(content, str) else " ".join(p.get("text", "") for p in content if p.get("type") == "text")


def last_user_text(req):
    for m in reversed(req.get("messages") or []):
        if m.get("role") == "user":
            return text_of(m["content"])
    return ""


def file_objects(x):
    if isinstance(x, dict):
        if x.get("type") == "file" and isinstance(x.get("path"), str):
            return [x]
        return [f for v in x.values() for f in file_objects(v)]
    if isinstance(x, list):
        return [f for v in x for f in file_objects(v)]
    return []


def triage(req):
    d = req.get("data") or {}
    text = (d.get("subject", "") + " " + d.get("body", "")).lower()
    q = "billing" if any(w in text for w in ("billed", "charged", "refund")) else \
        "account" if any(w in text for w in ("log in", "password", "reset")) else "general"
    return {"data": {"queue": q}}


def empty(req):
    return {}


def refund(req):
    state = json.loads(json.dumps(req.get("state") or {}))
    text = last_user_text(req)
    orders = state.get("orders", {})
    oid = next((o for o in orders if o in text), None)
    if not oid:
        return {"reply": "I can't find that order.", "state": state}
    total = orders[oid]["total"]
    orders[oid]["status"] = "refunded"
    return {
        "reply": "Done! Your refund will arrive in 5 Business Days.",
        "tool_calls": [
            {"name": "lookup_order", "args": {"order_id": oid}, "result": {"total": total}},
            {"name": "refund", "args": {"order_id": oid, "amount": float(total)}, "result": {"ok": True}},
        ],
        "state": state,
    }


def fixed_strings(req):
    # Strings a YAML 1.1 parser would read as something else, plus the numbers YAML 1.2 reads them as.
    return {"data": {"answer": "no", "yes_word": "yes", "due": "2026-04-15", "code": "0755", "country": "NO",
                     "ver": "1.10", "n755": 755, "n11": 1.1, "flag": False}}


def counter(req):
    state = req.get("state") or {}
    data = req.get("data") or {}
    total = state.get("total", 0) + data.get("add", 0)
    return {"data": {"total": total, "saw_data": data, "n_messages": len(req.get("messages") or [])},
            "state": {**state, "total": total}}


def chat(req):
    msgs = req.get("messages") or []
    k = sum(1 for m in msgs if m.get("role") == "assistant") + 1
    return {"reply": f"turn {k}: got {len(msgs)} messages",
            "data": {"n_messages": len(msgs), "roles": [m.get("role") for m in msgs], "last_user": last_user_text(req),
                     "sid": req.get("session_id"), "session_id_present": bool(req.get("session_id")),
                     "saw_data": req.get("data")}}


def misbehave(req):
    d = req.get("data") or {}
    mode = d.get("mode")
    ok = {"data": {"ok": True}}
    if mode == "stdout_noise":
        print("loading model weights...")  # a log line on stdout before the JSON
    if mode == "stderr_noise":
        print("loading model weights...", file=sys.stderr)
    if mode == "exit1":
        print(json.dumps(ok)); sys.stdout.flush(); os._exit(1)
    if mode == "bad_json":
        print("{not json"); sys.stdout.flush(); os._exit(0)
    if mode == "slow":
        time.sleep(4)
    if mode == "flaky":  # crashes on the first call of the run, then works
        if bump("flaky") == 1:
            print("boom", file=sys.stderr); sys.stdout.flush(); os._exit(3)
    if mode == "non_object":
        return ["not", "an", "object"]
    if mode == "bad_reply":
        return {"reply": 5}
    if mode == "bad_state":
        return {"state": "done"}
    if mode == "bad_tool_calls":
        return {"tool_calls": [{"args": {}}]}
    if mode == "bad_cost":
        return {"reply": "ok", "cost_usd": "0.01"}
    if mode == "null_fields":  # null counts as absent (SPEC 4.1)
        return {"reply": None, "data": {"ok": True}, "tool_calls": None, "state": None, "cost_usd": None, "trace_id": None}
    if mode == "extra_field":
        return {"data": {"ok": True}, "trace_id": "abc"}
    if mode == "counted":  # counts how often the agent was called for this key
        return {"data": {"ok": True, "call": bump("agent-" + d["key"])}}
    return ok


def numbers(req):
    return {"data": {"total": (req.get("data") or {}).get("total_shown")}}


def priced(req):
    d = req.get("data") or {}
    return {"reply": "ok", **({"cost_usd": d["cost"]} if "cost" in d else {})}


def sleepy(req):
    time.sleep(0.3)
    return {"reply": "ok", "cost_usd": 0.01}


def files(req):
    d = req.get("data") or {}
    found = file_objects(d) + file_objects(req.get("messages") or [])
    paths = [f["path"] for f in found]
    out = {"n_files": len(paths), "n_distinct": len(set(paths)),
           "all_abs": all(os.path.isabs(p) for p in paths), "all_exist": all(os.path.exists(p) for p in paths)}
    if req.get("state"):  # files in state are left alone (SPEC 4.2)
        out["state_doc"] = req["state"].get("doc")
    doc = d.get("doc") or {}
    if doc.get("path") and os.path.isfile(doc["path"]):
        out["doc_text"] = open(doc["path"]).read().strip()
    wd = d.get("dir") or {}
    if wd.get("path") and os.path.isdir(wd["path"]):
        log = os.path.join(wd["path"], "log.txt")
        with open(log, "a") as f:
            f.write("touched\n")
        out["lines"] = sum(1 for _ in open(log))
        out["workdir"] = wd["path"]
    if d.get("crash_once") and bump("files_crash") == 1:  # after writing to the copy, so a reused copy shows
        os._exit(3)
    return {"data": out}


def flipper(req):
    # Every third call (3, 6, 9, ...) gives the wrong answer.
    return {"data": {"answer": "wrong" if bump("flipper") % 3 == 0 else "right"}}


def paths(req):
    return {"data": {"a.b": 1, "list": [10, 20], "obj": {"0": "zero"}, "nul": None, "num": 20.0, "flag": True,
                     "five": "5", "pair": {"a": 1, "b": 2}, "word": "Hello"},
            "tool_calls": [{"name": "lookup", "args": {"id": 7}}]}


def support(req):
    """Deterministic wifi helpdesk bot for the persona test."""
    state = dict(req.get("state") or {})
    text = last_user_text(req).lower()
    if not state.get("asked"):
        state["asked"] = True
        return {"reply": "Sorry to hear that. What changed recently on the laptop?", "state": state}
    if "update" in text and not state.get("suggested"):
        state["suggested"] = True
        return {"reply": "Updates can reset network settings. Forget the wifi network, then rejoin it. Does it work now?",
                "state": state}
    if state.get("suggested") and any(w in text for w in ("works", "working", "connected", "fixed", "online")):
        state["solved"] = True
        return {"reply": "Great, glad it's working!", "state": state}
    if state.get("suggested"):
        state["handed_off"] = True
        return {"reply": "I'll hand you to a specialist.", "state": state}
    return {"reply": "Did anything change recently, like an update?", "state": state}


def relfile(req):
    # A relative file path in the output: the runner must keep it exactly as returned.
    return {"reply": "Wrote out/report.txt", "data": {"out": {"type": "file", "path": "out/report.txt"}, "dir": "./out"}}


def boom(req):
    """Target of the invalid evals: a runner must never call it."""
    bump("INVALID-EVAL-RAN")
    return {}


BEHAVIORS = {f.__name__: f for f in (triage, empty, refund, fixed_strings, counter, chat, misbehave, numbers, priced,
                                     sleepy, files, flipper, paths, support, relfile, boom)}

if __name__ == "__main__":
    req = json.loads(sys.stdin.read() or "{}")
    print(json.dumps(BEHAVIORS[sys.argv[1]](req)))
