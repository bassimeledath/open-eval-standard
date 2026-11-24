# OES conformance suite

A runner that passes this suite, and meets every requirement in `skills/oes/SPEC.md`, is a conforming runner (SPEC 1).

## Run it

```bash
python3 conformance/run.py <runner command...>
```

For example, from the repository root:

```bash
python3 conformance/run.py uv run --project runners/python oes
python3 conformance/run.py node runners/typescript/dist/oes.js
```

It needs Python 3.10 or later and nothing else. It uses port 8811, so only one copy of the suite can run at a time. It prints one line per check and exits 1 if any check fails. Options go before the runner command: `--only <text>` runs the checks whose name contains the text, `-v` prints every mismatch, and `--keep` keeps the temporary copy of the suite.

## What the runner must support

The suite drives the runner only through the command line and environment variables of SPEC 8.4. It calls the runner, from a fresh temporary copy of this folder, which is the repository root for every run:

- `<runner> run <eval file> --agent-version v-conformance --agent-model fake-agent`
- `<runner> validate <eval file>`

Arguments of the runner command that name an existing path, such as `runners/python`, are made absolute first, so relative paths work.

Judges and simulated users go through `OES_LLM_COMMAND` (SPEC 8.4), so no model vendor is involved. The suite sets `OES_LLM_COMMAND="python3 fake_llm.py"`, a deterministic fake whose answers are set by `<<judge: ...>>` and `<<user: ...>>` directives in the judge prompts and personas (see `fake_llm.py`). The runner's own prompt wording doesn't matter, as long as it includes the judge prompt, the input, the transcript, the output and the expected entry for a judge, and the persona and the transcript (and nothing else from the case) for a simulated user. It also sets `OES_JUDGE_MODEL=fake-judge-1` and `OES_USER_MODEL=fake-user-1`, and `OES_RETRIES` for one run. It passes every other variable through unchanged.

## What it checks

| Part | Checks |
|---|---|
| `evals/*.eval.yaml` | Each eval runs against the fake agents in `agents/fake.py` (as commands, and over HTTP through `serve.py`). `expected/<name>.json` holds what must match: the exit code, `status`, `cases`, per scorer `value`, `passed`, `scored`, `skipped` and `failing_cases`, some result fields, and some row facts. Numbers match within 0.1%. Latency is compared only as a pass or fail, where the agent sleeps. Some expected files run an eval with a changed environment (`env`; `null` unsets a variable), or count the fake LLM's calls (`counters`). |
| every run | `result.json` and every row of `rows.jsonl` match `skills/oes/result.schema.json`. The last stdout line is the run folder, in `.oes/runs/<run_id>/`. `run_id` is unique. The exit code matches the status. `agent_version` and `models.agent` come from the flags. |
| `evals/invalid/` | `validate` and `run` both exit 2, no run folder is written, and the target is never called. |
| `hash-vectors/` | Each vector eval's `eval_hash` equals the one in `vectors.json`, computed by `hash-vectors/compute.py` from SPEC 8.2 alone. The suite adds `__pycache__`, `.pyc` and `.DS_Store` files to the copy, which the hash must leave out. |
| hash changes | Running an eval twice gives the same hash. Editing a check, a fixture or a judge changes it. |
| schema copies | Every runner under `runners/` bundles `eval`, `judge` and `result.schema.json` in `oes_schemas/` or `schemas/`, byte for byte the same as `skills/oes/` (`check_schema_copies.py`). |

## Changing the suite

- After changing a schema in `skills/oes/`, copy it into every runner's bundle.
- After changing a hash vector, run `python3 conformance/hash-vectors/compute.py --write`.
- To add a built-in check to the standard (SPEC 9.5), add an eval here and its expected file.
