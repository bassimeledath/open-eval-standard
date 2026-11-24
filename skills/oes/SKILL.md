---
name: oes
description: Add, run or fix evals for an AI agent using the Open Eval Standard (OES) (plain YAML eval files, any language, any model provider). Use when the user asks to write evals, test cases or benchmarks for any AI agent: a coding agent, extractor, classifier, browser agent, data pipeline, tool-using assistant, chatbot or single model call, to check a prompt or model change, or to run or repair existing *.eval.yaml files.
---

# Open Eval Standard (OES)

OES is a standard way to write evals of AI agents, as plain files. `SPEC.md` in this folder is the source of truth. Read it before writing anything. `examples/` has one eval of each common shape, and `eval.schema.json` and `judge.schema.json` check the files.

## Add evals to a project

1. **Start from real failures, if there are any.** If the agent has logs, traces or bug reports, read some first and note how it fails. Those failures make the best test cases.
2. **Find the entry point.** Find where the agent takes an input (a message, a task, a document, JSON) and produces an output. Add a small target next to it that follows SPEC 4: it reads `{session_id, messages, data, state}` and returns whichever of `reply`, `data`, `tool_calls`, `state` and `cost_usd` apply. Return whatever the scorers will read. Use `command` for scripts and CLIs, `http` for servers. Don't change how the agent works. If its tools are internal, add a small hook that records each call, so the target can report them in `tool_calls`.
3. **Write the evals.** One file per eval, in `evals/<name>.eval.yaml`. Start with 5 to 20 test cases that cover the agent's main jobs and its known failures. Use single-turn test cases unless the behavior only shows up across several calls. For multi-turn, use `script` for fixed inputs (a chat replay, or a task and its follow-ups), and `persona` only when a user's replies need to react to the agent. Quote any text YAML could misread: `"no"`, `"0755"`, `"2026-04-15"`.
4. **Prefer checks to judges.** Use a built-in check (SPEC 6) when the expected behavior is a value, a tool call or some text. Use a custom check (`{command}` or `{http}`) when code can verify the result in other ways: running tests, comparing numbers within a tolerance, validating JSON or SQL. Use a judge (SPEC 7) only for what code can't check, and put its criteria in the test case's expected entry. Judges go in `evals/judges/`, and custom checks in `evals/checks/`.
5. **Set pass rules with the user.** At least one scorer needs `pass`. If the right bar isn't obvious, ask. Don't invent thresholds. Give a gating scorer an entry in every test case it should cover.
6. **Allow for randomness.** An agent that calls a model won't give the same answer every time. Use `trial_count: 3` or more and `mean` rules for quality. Keep `each: 1` for things that must never happen, like leaking data.
7. **Run it with a reference runner.** Don't write your own. Use the Python or TypeScript runner from the OES repository (see its README):
   - `oes validate evals/<name>.eval.yaml` checks the files.
   - `oes run evals/<name>.eval.yaml` runs the eval and writes `.oes/runs/<run_id>/`. Add `.oes/` to `.gitignore`.
   - Judges and simulated users need `OES_LLM_COMMAND`: a small script that reads `{role, model, prompt}` as JSON and prints `{text}`. Write it with the model provider the project already uses.

   If neither runner fits, a new runner must follow SPEC 8.4, reject anything it doesn't support, and pass `conformance/`.
8. **Make sure each eval can fail** (SPEC 9, rule 3). Run it once against a target that returns `{}`. If it still passes, strengthen it.
9. **Report.** Give the user each eval's status, the failing test case ids, how many trials each scorer skipped, and anything you assumed.

## Fix a failing eval

Read `rows.jsonl` for the failing test cases. Decide whether the agent or the eval is wrong. Fix the agent when the agent is wrong. Change the eval only when the expectation itself was wrong, and say so.

## When something real breaks

When the user reports a bug in the agent, add a test case that reproduces it, so it can't come back unnoticed.

## Don't

- Don't add fields the spec doesn't define. Put anything agent-specific in `metadata`, `data` or `state`.
- Don't hard-code a model provider in eval or judge files. `model` is optional, and the runner decides what it means.
- Don't report `not_evaluated` as a pass.
- Don't set retries above 0 for an agent with real side effects, such as sending email or charging a card, unless it points at a test environment.
