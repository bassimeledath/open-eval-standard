# oes-python

The reference Python runner for the Open Eval Standard. One file, `oes.py`, following `skills/oes/SPEC.md` (version 1.0.0-rc.1). It needs Python 3.10 or later, `ruamel.yaml` and `jsonschema`.

```bash
uvx --from "git+https://github.com/bassimeledath/open-eval-standard#subdirectory=runners/python" oes validate evals/refund-agent.eval.yaml
uv run --project runners/python oes validate evals/refund-agent.eval.yaml   # from a checkout
uv run --project runners/python oes run evals/refund-agent.eval.yaml --agent-version "$(git rev-parse --short HEAD)" --agent-model my-model
```

Run it from your repository root: commands run from there and results go to `.oes/runs/<run_id>/`. `run` exits 0 for `passed`, 1 for any other status, and 2 for an invalid eval. `--agent-version` defaults to the git commit. The schemas are bundled in `oes_schemas/`, copies of `skills/oes/*.schema.json` that the conformance suite keeps identical; `OES_SCHEMA_DIR` overrides them.

## Settings

| Variable | Meaning |
|---|---|
| `OES_LLM_COMMAND` | The command that answers judge and simulated-user calls. Needed only by evals with a judge or a persona. |
| `OES_JUDGE_MODEL` | The judge model, when the judge file names none. |
| `OES_USER_MODEL` | The model that plays the simulated user. |
| `OES_RETRIES` | Retries after a failure (SPEC 8.1). Default 2. Use 0 for agents with real side effects. |

Trials run one at a time.

## The LLM command

The runner reaches models only through `OES_LLM_COMMAND`, so it works with any provider. For each judge or simulated-user call, it runs the command through `/bin/sh` from the repository root, writes one JSON object to its stdin, and reads one from its stdout:

```
in:  {"role": "judge" | "user", "model": <string or null>, "prompt": <string>}
out: {"text": <string>, "cost_usd": <number, optional>}
```

A non-zero exit or bad JSON is a `judge` or `user` error. A judge's text must hold `{"reason": ..., "choice": ...}`; the runner reads it from the first `{` to the last `}`, so a code fence is fine. A wrapper can be this small:

```python
#!/usr/bin/env python3
# llm.py: OES_LLM_COMMAND="python3 llm.py"
import json, sys

req = json.load(sys.stdin)
text = call_my_model(model=req["model"] or "my-default-model", prompt=req["prompt"])  # your client goes here
print(json.dumps({"text": text}))
```

`conformance/fake_llm.py` is a working example that answers without any model.

## Conformance

```bash
python3 conformance/run.py uv run --project runners/python oes
```
