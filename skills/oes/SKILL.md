---
name: oes
description: Add, run or fix evals for an AI app using the Open Eval Standard (OES) (plain YAML eval files, any language, any model provider). Use when the user asks to write evals, test cases or benchmarks for an LLM app, chatbot, agent or classifier, to check a prompt or model change, or to run or repair existing *.eval.yaml files.
---

# Open Eval Standard (OES)

OES is a standard way to write evals of AI apps, as plain files. `SPEC.md` in this folder is the source of truth. Read it before writing anything. `examples/` has one eval of each common shape, and `eval.schema.json` checks eval files.

## Add evals to a project

1. **Find the entry point.** Find where the app takes a user message, or a JSON input, and returns a reply. Add a small target next to it that follows SPEC 4: it reads a request (`session_id`, `messages`, `data`, `state`) and returns `reply`, plus `data`, `tool_calls` and `state` where the app has them. Use `command` for scripts and CLIs, `http` for servers. Don't change how the app works.
2. **Write the evals.** One file per eval, in `evals/<name>.eval.yaml`. Start with 5 to 20 test cases that cover the app's main jobs and its known failures. Use one-turn test cases unless the behavior only shows up across a conversation. Use `script` to replay a real conversation, and `persona` only when the user's replies need to react to the app.
3. **Prefer checks to judges.** Use a built-in check (SPEC 6) when the expected behavior is a value, a tool call or some text. Use a judge (SPEC 7) only for what code can't check, and put its rules in the test case's expected entry. Judges go in `evals/judges/`.
4. **Set pass rules with the user.** At least one scorer needs `pass`. If the right bar isn't obvious, ask. Don't invent thresholds.
5. **Validate.** Check every eval file against `eval.schema.json`.
6. **Run.** Use the project's runner if it has one. If not, write a small one in the project's language, following SPEC 4 to 8. Keep it short: load the eval, run each trial, score, write `.oes/runs/<run_id>/`. Use whatever model provider the project already uses for judges and simulated users. Add `.oes/` to `.gitignore`.
7. **Make sure each eval can fail** (SPEC 9, rule 3). Run it once against a target that returns nothing. If it still passes, strengthen it.
8. **Report.** Give the user each eval's status, the failing test case ids, and anything you assumed.

## Fix a failing eval

Read `rows.jsonl` for the failing test cases. Decide whether the app or the eval is wrong. Fix the app when the app is wrong. Change the eval only when the expectation itself was wrong, and say so.

## When something real breaks

When the user reports a bug in the app, add a test case that reproduces it, so it can't come back unnoticed.

## Don't

- Don't add fields the spec doesn't define. Put anything app-specific in `metadata`, `data` or `state`.
- Don't hard-code a model provider in eval or judge files. `model` is optional, and the runner decides what it means.
- Don't report `not_evaluated` as a pass.
