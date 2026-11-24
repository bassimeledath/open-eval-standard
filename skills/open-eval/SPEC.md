# Open Eval spec

Version 1, draft 2.

## 1. Purpose

Open Eval is a plain file format for evals of AI apps. An eval says what to send the app, what to expect back and how to score it. Any runner that follows this spec can run any eval written to it, in any language, with any model provider.

The app does not change how it is built. It exposes one entry point, the target, that the runner calls.

## 2. Terms

| Term | Meaning |
|---|---|
| Eval | A named group of test cases for one app, plus how to call the app and how to score it. One file. |
| Test case | One input, with what we expect. |
| Target | The app entry point the runner calls. |
| Turn | One call to the target: the user speaks, the app replies. |
| Transcript | Every message in a test case's conversation, in order. |
| State | Data the app carries from one turn to the next. |
| Scorer | Gives a trial a score from 0 to 1. A check runs code. A judge asks an LLM. |
| Trial | One attempt at one test case. A test case can run several trials. |
| Run | One execution of one eval on one version of the app. |
| Result | What a run produced: scores, status, cost and latency. |
| Runner | The program that reads eval files, calls the target, scores the output and writes the result. |

## 3. The eval file

Write one eval per file, named `<name>.eval.yaml`, in an `evals/` folder in the app's repository. The eval does not name the model or the app version. The run supplies them, so the same eval runs on every version of the app.

Names of evals, scorers and judges use lowercase letters, digits, hyphens and underscores. Paths in an eval file are relative to that file.

| Field | Required | Meaning |
|---|---|---|
| `openeval` | Yes | The spec version. Use `1`. |
| `name` | Yes | Unique in the repository. |
| `target` | Yes | How to call the app. See 4. |
| `scorers` | Yes | How to score. See 6. At least one scorer has a `pass` rule. |
| `cases` | Yes | A list of test cases, or a JSONL file of them: `{file: cases.jsonl}`. |
| `description` | No | One sentence on what the eval checks. |
| `trial_count` | No | Trials per test case. Default 1. |
| `tags`, `metadata` | No | Free labels and fields, copied to the result. |

## 4. The target

The target is one of:

| Form | Meaning |
|---|---|
| `{command: "python -m app.eval_entry"}` | The runner starts the command for each turn, writes the request as JSON to stdin and reads the response as JSON from stdout. |
| `{http: "http://localhost:8000/eval"}` | The runner POSTs the request as JSON and reads the response as JSON. |

Request:

| Field | Meaning |
|---|---|
| `session_id` | A new id for each trial. The same id for every turn of one trial. |
| `messages` | The transcript so far. The last item is the newest user message. |
| `data` | The test case's `input.data`, or `{}`. |
| `state` | On the first turn, the test case's `input.state`. After that, the `state` the app returned on the turn before. `{}` if neither. |

Response. Every field is optional:

| Field | Meaning |
|---|---|
| `reply` | The app's reply for this turn. |
| `data` | Structured output for this turn, such as a label or an extracted record. |
| `tool_calls` | Each tool the app called this turn: `{name, args}`, plus `result` or `error` if known. |
| `state` | The app's state after this turn. The runner sends it back on the next turn, so the target can be stateless. |
| `cost_usd` | What this turn cost, if the app knows. |

A message is `{role, content}`, with `role` of `user` or `assistant`. `content` is text, or a list of parts: `{type: text, text}` or `{type: file, path, mime}` for images, audio and documents.

## 5. Test cases

| Field | Required | Meaning |
|---|---|---|
| `id` | Yes | Unique inside the eval. |
| `input` | Yes | What the app receives. |
| `expected` | No | What each scorer expects, keyed by scorer name. See 6. |
| `tags`, `metadata` | No | Free labels and fields. |

`input` fields:

| Field | Meaning |
|---|---|
| `message` | One user message. Short for `messages: [{role: user, content: ...}]`. |
| `messages` | The conversation so far. Use it to start at any point of a real conversation. To have the app speak first, start with an `assistant` message. |
| `data` | Any other JSON the app receives. An app with no conversation uses only `data`. |
| `state` | The app's state before the first turn. |
| `script` | Fixed user lines, sent one per turn after `message` or `messages`. |
| `persona` | A simulated user, in plain text: who they are, what they want, what they know and when they stop. |
| `max_turns` | Required with `script` or `persona`. The most turns the runner will run. |
| `stop_when` | Output values that end the conversation early, such as `{state.done: true}`. |

The input decides how the test case runs:

- **One turn.** `message`, `messages` or `data` alone. The runner calls the target once. An agent that makes many tool calls inside that one call is still one turn.
- **Scripted.** `script`. The runner sends each line in turn.
- **Simulated.** `persona`. An LLM plays the user. It writes each next user message, and can end the conversation.

A scripted or simulated test case also ends at `max_turns`, or when `stop_when` matches the target's response.

The simulated user gets the persona and the transcript. It replies with the next user message, or with exactly `[done]` to end the conversation. The runner records which model played the user.

## 6. Scorers

| Field | Required | Meaning |
|---|---|---|
| `name` | Yes | Unique inside the eval. Shown in the result. |
| `check` | One of | A built-in check, or a custom check: `{command: ...}` or `{http: ...}`. |
| `judge` | One of | The name of a judge file. See 7. |
| `scope` | No | `trial` (default) or `run`. Only custom checks set it. |
| `pass` | No | A pass rule. |

A scorer reads its own entry in `expected`: the scorer `right_queue` reads `expected.right_queue`. So an eval can have many scorers of the same kind, each with its own expectations and pass rule.

A trial scorer scores each trial from 0 to 1. A built-in check skips a test case that has no entry for it. A judge runs on every test case and reads the entry if there is one. A run scorer scores the whole run once and returns a number.

Pass rules:

| Rule | For | Passes when |
|---|---|---|
| `{each: x}` | Trial scorers | Every trial scores at least x. |
| `{mean: x}` | Trial scorers | The mean over all trials is at least x. |
| `{min: x}` | Run scorers | The run's number is at least x. |
| `{max: x}` | Run scorers | The run's number is at most x. |

A scorer with no `pass` rule is reported but does not set the status.

Built-in checks:

| Check | Scope | Expected entry | Scores 1 when |
|---|---|---|---|
| `equals` | Trial | Output paths and values: `{data.queue: billing, state.handed_off: false}` | Every path has exactly that value. |
| `reply_contains` | Trial | Texts: `[refund, 5 days]` | Each text appears in at least one app reply. |
| `tool_called` | Trial | Tool names, or `{name, args}`: `[{name: refund, args: {amount: 20}}]` | Each listed tool was called at least once. Listed args must match; others are ignored. |
| `tool_not_called` | Trial | Tool names: `[delete_account]` | None of the listed tools was called. |
| `latency_p95_ms` | Run | None | Returns the 95th percentile of turn latency, in milliseconds. |
| `cost_per_trial_usd` | Run | None | Returns the mean cost of one trial, in US dollars. |

A trial check scores 1 or 0. An output path is dot-separated: `data.queue`, `state.handed_off` or `tool_calls.0.name`. `data` and `state` are what the app returned on its last turn. A missing path never equals a value, not even `null`.

A custom check is a command or URL that uses the same JSON in and out as the target:

- Trial scope gets `{input, output, expected}`, where `expected` is the scorer's own entry or `null`. It returns `{score, reason}`, or `{score: null}` to skip the trial.
- Run scope gets `{rows}`, every trial row of the run (see 8). It returns `{score, reason}`.

## 7. Judges

A judge is a file in the repository, `<name>.judge.yaml`, in `evals/judges/`:

```yaml
name: goal-completion
prompt: |
  Did the assistant get the user to the right outcome?
  Pass if the problem is solved, or the assistant hands off correctly.
  Fail if it misunderstood, gave wrong guidance, or looped.
choices: {pass: 1, fail: 0}
```

| Field | Required | Meaning |
|---|---|---|
| `name` | Yes | The judge's name. Scorers refer to it. |
| `prompt` | Yes | What to judge, in plain language. |
| `choices` | No | Each answer and its score. Default `{pass: 1, fail: 0}`. |
| `model` | No | The model to use, as a name the runner understands. Default: the runner's judge model. |

The runner sends the judge model the prompt, the test case's input, the transcript and output, and the scorer's expected entry, if there is one (often a list of rules, or a reference answer). The judge answers in JSON, `{reason, choice}`, giving its reason first. The runner logs both.

Prefer two choices. They are easier to agree on and to check against human labels. Before trusting a judge, check it against a few human labels.

## 8. The result

Each run writes a folder, `.openeval/runs/<run_id>/`, in the app's repository:

- `result.json`: the result of the run.
- `rows.jsonl`: one row per trial.

A runner may also send the same rows to an eval platform. The local files are the source of truth.

`result.json`:

| Field | Meaning |
|---|---|
| `eval`, `run_id`, `started_at` | The eval, a unique run id and when the run started. |
| `app_version` | A label for the app version under test, such as a git commit. |
| `models` | Every model that the run used, by role: `app`, `judge`, `user`. Whatever names the runner knows. |
| `eval_hash` | SHA-256 of the eval file, its cases file and its judge files. |
| `status` | `passed`, `failed`, `error` or `not_evaluated`. |
| `scores` | Per scorer: `value` (the mean, or the run number), `passed` (true, false or null if no pass rule), and `failing_cases` (ids of test cases with a trial scoring below 1). |
| `latency_ms` | p50 and p95 of one turn. |
| `cost_usd` | Mean cost of one trial, for the app and for the judges. |
| `cases` | `total`, the number of test cases, and `errored`, the ids of test cases that errored. |

Status, in order:

1. `error`: the run stopped, or a test case errored after retries.
2. `not_evaluated`: some test cases did not run, or a scorer with a pass rule scored nothing.
3. `failed`: at least one pass rule is not met.
4. `passed`: every pass rule is met.

`not_evaluated` is never a pass. No tool may change it to `passed`.

Each row in `rows.jsonl` has `case_id`, `trial`, `input`, `expected`, `output` (the `transcript`, `tool_calls`, and the last `data` and `state`), `scores` (per scorer: `score` and `reason`), `latency_ms` (per turn), `cost_usd` and, if it errored, `error`.

Scorers read only the logged rows. So a runner can re-score a saved run without calling the app again.

### 8.1 Errors

A trial can fail for a reason outside the app's logic: the target crashes, a judge or the simulated user breaks, or a call times out. The runner retries it first. If it still fails, the row gets `error: {kind, message}`, with `kind` of `target`, `judge`, `user` or `timeout`, and no scores.

### 8.2 Comparing runs

To compare two versions of an app, run the eval on each and compare the two results. Compare runs only when they have the same `eval_hash` and the same judge and user models. Otherwise the change in score may come from the eval, not the app. A saved result can be reused as the baseline while all of these stay the same.

## 9. Rules

1. Check each eval file against `eval.schema.json`. Unknown fields are errors, except inside `metadata`, `data`, `state` and `expected`.
2. A runner rejects an eval with two test cases or two scorers of the same name.
3. An eval must be able to fail. Run it once against a target that replies with nothing and calls no tools. If it passes, the test cases or scorers are too weak. The exception is an eval that only checks that something does not happen, such as `tool_not_called`.
4. A change that breaks existing evals raises `openeval`. A new optional field does not.
5. To add a built-in check, add a row to the table in 6.
