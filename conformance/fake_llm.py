"""A fake, deterministic LLM that speaks the OES LLM command protocol. Stdlib only.

stdin:  {"role": "judge" | "user", "model": <string or null>, "prompt": <string>}
stdout: {"text": <string>, "cost_usd": <number>}

What it answers is set by directives that the eval puts in a judge prompt or a persona. A runner copies
those into the prompt with its own wording around them, so the fake looks for the directives anywhere:

  <<judge: if NEEDLE => OUT>>   or  <<user: if NEEDLE => OUT>>
  <<judge: else => OUT>>        or  <<user: else => OUT>>

It uses only the directives for its own role, in order. The first `if` whose NEEDLE appears in the
prompt (with every directive removed, plus "[model=<model>]") wins; otherwise the `else`.

For a judge, OUT is a choice, answered as {"reason", "choice"}. For a user, OUT is the next message.
Special values of OUT:
  !notjson           a judge answer that is not JSON
  !badchoice         a judge answer naming a choice that does not exist
  !fenced CHOICE     a judge answer in a code fence, with prose around it
  !fail              exit 1
  !padded-done       "  [done]\n", which a runner trims to [done]
  !flaky NAME REST   exit 1 the first time NAME is used in this run, then answer REST
  !counted NAME REST count the call in .counters/llm-count-NAME, then answer REST
Without a match: a judge says "pass" and a user says "[done]".
Each call costs 0.001 for a judge and 0.002 for a user.
"""
import fcntl, json, os, re, sys

RULE = re.compile(r"<<(judge|user): (?:if (.+?)|else) => (.*?)>>", re.S)
ANY = re.compile(r"<<(?:judge|user):.*?>>", re.S)


def bump(name):
    os.makedirs(".counters", exist_ok=True)
    with open(os.path.join(".counters", name), "a+") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.seek(0)
        n = int(f.read() or 0) + 1
        f.seek(0); f.truncate(); f.write(str(n))
    return n


def main():
    req = json.loads(sys.stdin.read())
    role, prompt = req["role"], req["prompt"]
    with open(os.path.join(".counters", "llm-calls.jsonl") if os.path.isdir(".counters") else os.devnull, "a") as f:
        f.write(json.dumps({"role": role, "model": req.get("model")}) + "\n")
    haystack = ANY.sub(" ", prompt) + f" [model={req.get('model')}]"
    out = None
    for r, needle, value in RULE.findall(prompt):
        if r == role and (not needle or needle.strip() in haystack):
            out = value.strip()
            break
    if out is None:
        out = "pass" if role == "judge" else "[done]"
    if out.startswith("!flaky "):
        _, name, out = out.split(" ", 2)
        if bump("llm-flaky-" + name) == 1:
            print("fake LLM: flaky failure", file=sys.stderr)
            sys.exit(1)
    if out.startswith("!counted "):
        _, name, out = out.split(" ", 2)
        bump("llm-count-" + name)
    if out == "!fail":
        print("fake LLM: asked to fail", file=sys.stderr)
        sys.exit(1)
    if role == "judge" and out.startswith("!fenced "):
        answer = json.dumps({"reason": "fenced", "choice": out.split(" ", 1)[1]})
        text = f"Here is my verdict.\n```json\n{answer}\n```\nThanks."
    elif role == "judge":
        text = {"!notjson": "I think it passes.",
                "!badchoice": json.dumps({"reason": "unsure", "choice": "maybe"})}.get(
            out, json.dumps({"reason": f"fake judge chose {out}", "choice": out}))
    else:
        text = "  [done]\n" if out == "!padded-done" else out
    print(json.dumps({"text": text, "cost_usd": 0.001 if role == "judge" else 0.002}))


if __name__ == "__main__":
    main()
