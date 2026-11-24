# oes-runner (TypeScript)

The TypeScript reference runner for the Open Eval Standard. It follows `skills/oes/SPEC.md` (version 1.0.0-rc.1) and writes `runner: {name: "oes-typescript", version: "0.1.0"}` into every result.

## Install and build

Needs Node 20 or later.

```sh
cd runners/typescript
npm install
npm run build        # compiles src/oes.ts to dist/oes.js
```

The runner loads its schemas from `schemas/` in the package, so it works when installed on its own. Those files are exact copies of `skills/oes/*.schema.json`: run `npm run sync-schemas` after the schemas change. `OES_SCHEMA_DIR` overrides the folder.

## Usage

Run from the agent's repository root. Target and check commands run from there, and results go to `.oes/runs/<run_id>/`.

```sh
node runners/typescript/dist/oes.js validate evals/triage.eval.yaml
node runners/typescript/dist/oes.js run evals/triage.eval.yaml [--agent-version LABEL] [--agent-model LABEL]
```

`npm link` puts the same thing on your path as `oes`.

- `run` prints a short summary, then the run folder's absolute path as its last line. It exits 0 for `passed`, 1 for any other status, and 2 for an invalid eval, without running it.
- `validate` checks the eval, its cases file and its judge files without calling anything. It exits 0 if valid, 2 if not.

Progress goes to stderr.

## Environment

| Variable | Meaning |
|---|---|
| `OES_LLM_COMMAND` | Shell command for judges and simulated users. See below. |
| `OES_JUDGE_MODEL` | Judge model, when the judge file has no `model`. Default `null`. |
| `OES_USER_MODEL` | Simulated user model. Default `null`. |
| `OES_RETRIES` | Retries per failing step (8.1). Default 2; 0 turns them off. |
| `OES_AGENT_VERSION`, `OES_AGENT_MODEL` | Fill `agent_version` and `models.agent`, like the flags. `agent_version` otherwise comes from `git describe`. |
| `OES_SCHEMA_DIR` | Where to find the schema files. |

Trials run one at a time.

## The LLM command

The runner names no model vendor. For each judge or simulated-user call it runs `OES_LLM_COMMAND` through `/bin/sh -c`, from the repository root, and writes one JSON object to its stdin:

```json
{"role": "judge", "model": "some-model-or-null", "prompt": "..."}
```

`role` is `judge` or `user`. `model` comes from the judge file's `model`, then `OES_JUDGE_MODEL`, then `null` for judges; from `OES_USER_MODEL`, then `null` for the user.

The command prints `{"text": "...", "cost_usd": 0.001}` (`cost_usd` is optional). As with targets, if the whole of stdout isn't JSON, the last non-empty line is read. A non-zero exit, output that isn't such an object, or a call over 300 seconds is a `judge` or `user` error (`timeout` for the last), and is retried.

A judge's `text` holds the JSON answer `{"reason": ..., "choice": ...}`. The runner reads it from the first `{` to the last `}`, so a code fence around it is fine. A simulated user's `text` is the next user message, or `[done]` to end the conversation.

If an eval needs a judge or a simulated user and `OES_LLM_COMMAND` isn't set, `run` exits 2 and says so. `validate` doesn't need it.

A minimal command, as a script that calls whatever model you use:

```sh
export OES_LLM_COMMAND="python3 scripts/oes_llm.py"
```
