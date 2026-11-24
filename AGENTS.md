# Adding evals to a project with Open Eval

Instructions for a coding agent asked to add evals to an app using this spec. Read `SPEC.md` first. It is the source of truth; this page is the order of work.

1. **Find the entry point.** Work out where the app takes a user message (or a JSON input) and returns a reply. Add a small target that follows SPEC 3.2: it takes a request with `session_id`, `messages`, `data` and `start_state`, and returns `reply`, plus `data`, `tool_calls`, `actions` and `state` where the app has them. Prefer `command` or `http`. Don't change how the app itself works.
2. **Write the evals.** Put each one in `evals/<name>.eval.yaml`. Start with 5 to 20 test cases that cover the app's main jobs and its known failures. Use `single_turn` unless the behavior only shows up across a conversation.
3. **Prefer checks to judges.** Use a built-in check (SPEC 3.6) when the expected behavior is a value, a tool call or an action. Use a judge only for qualities that code can't check, and write its rules in `expected.rules`. Put judges in `evals/judges/`.
4. **Give every eval a pass rule.** At least one scorer needs `pass`. Ask the user for thresholds if the right bar isn't clear. Don't invent them.
5. **Validate.** Check each file against `schema/eval.schema.json`.
6. **Run it.** If the project has no runner, write a small one that follows SPEC 3 to 5: call the target, play the user for multi-turn evals, score, and write `.openeval/runs/<run_id>/`. Add `.openeval/` to `.gitignore`.
7. **Check that the eval can fail** (SPEC 6, rule 2). Run it against a target that returns an empty reply. If it still passes, the test cases or scorers are too weak. Fix them.
8. **Report.** Tell the user the status of each eval, the failed test case ids, and anything you assumed.

When a real failure turns up later, add it as a new test case so it can't come back unnoticed.
