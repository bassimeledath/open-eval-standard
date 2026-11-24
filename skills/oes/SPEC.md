# Open Eval Standard (OES)

Version 1, draft 4.

## 1. Purpose

The Open Eval Standard (OES) is a standard way to write evals of AI agents, as plain files. An eval says what to send the agent, what to expect back and how to score it. Any runner that follows this spec can run any eval written to it, in any language, with any model provider.

An agent here is any AI system that takes an input and replies or acts: a chatbot, an assistant that uses tools, a coding agent, or a single model call. The agent does not change how it is built. It exposes one entry point, the target, that the runner calls.

## 2. Terms

| Term | Meaning |
|---|---|
| Eval | A named group of test cases for one agent, plus how to call the agent and how to score it. One file. |
| Test case | One situation to give the agent, with what we expect. |
| Target | The agent entry point the runner calls. |
| Turn | One call to the target: it gets an input and returns an output. |
| Transcript | Every message sent to the agent and every reply it gave, in order. Empty if there were neither. |
| State | Data the agent carries from one turn to the next. |
| Scorer | Grades each trial from 0 to 1, or the whole run with one number. A check runs code. A judge asks an LLM. |
| Trial | One attempt at one test case. A test case can run several trials. |
| Run | One execution of one eval on one version of the agent. |
| Result | What a run produced: scores, status, cost and latency. |
| Runner | The program that reads eval files, calls the target, scores the output and writes the result. |

## 3. The eval file

Write one eval per file, named `<name>.eval.yaml`, in an `evals/` folder in the agent's repository. The eval does not name the model or the agent version. The run supplies them, so the same eval runs on every version of the agent.

Names of evals, scorers and judges use lowercase letters, digits, hyphens and underscores. Paths in an eval file, and in its cases file, are relative to the eval file. Commands, for targets and custom checks, run from the repository root.

| Field | Required | Meaning |
|---|---|---|
| `oes` | Yes | The spec version. Use `1`. |
| `name` | Yes | Unique in the repository. |
| `target` | Yes | How to call the agent. See 4. |
| `scorers` | Yes | How to score. See 6. At least one scorer has a `pass` rule. |
| `cases` | Yes | A list of test cases, or a JSONL file of them: `{file: cases.jsonl}`. |
| `description` | No | One sentence on what the eval checks. |
| `trial_count` | No | Trials per test case. Default 1. |
| `tags`, `metadata` | No | Free labels and fields, copied to the result. |

## 4. The target

The target is one of:

| Form | Meaning |
|---|---|
| `{command: "python -m agent.eval_entry"}` | The runner starts the command for each turn, writes the request as JSON to stdin and reads the response as JSON from stdout. |
| `{http: "http://localhost:8000/eval"}` | The runner POSTs the request as JSON and reads the response as JSON. |

Either form can add `timeout_s`, the most seconds one call may take, such as `{command: "...", timeout_s: 600}`. Without it, the runner's default applies.

Request:

| Field | Meaning |
|---|---|
| `session_id` | A new id for each trial. The same id for every turn of one trial. |
| `messages` | The transcript so far, ending with the newest user message. Empty for an agent with no conversation. |
| `data` | The script item's `data` on a scripted turn that has one; it replaces `input.data` for that turn. Otherwise the test case's `input.data`, or `{}`. Keep anything needed across turns in `state`. |
| `state` | On the first turn, the test case's `input.state`. After that, the `state` the agent returned on the turn before. `{}` if neither. |

Response. Every field is optional:

| Field | Meaning |
|---|---|
| `reply` | The agent's text output for this turn, if it has one: an answer, a summary, a report. |
| `data` | Structured output for this turn, such as a label, an extracted record or test results. |
| `tool_calls` | Each tool the agent called this turn: `{name, args}`, plus `result` or `error` if known. |
| `state` | The agent's state after this turn. The runner sends it back on the next turn, so the target can be stateless. |
| `cost_usd` | What this turn cost, if the agent knows. |

A message is `{role, content}`, with `role` of `user` or `assistant`. `content` is text, or a list of parts: `{type: text, text}` or `{type: file, path, mime}` for images, audio and documents.

A file can also go anywhere in `data`, at any depth, as the same `{type: file, path, mime}` object. `path` can be a file or a folder, and `mime` is optional. Each trial gets its own copy, and the runner sends its absolute path, so an agent can change it freely. This assumes the target can read the runner's files: the same machine, or a shared folder or volume. For a remote target, put a URL in `data` instead. An agent that changes files, such as a coding agent, returns where its work is in `data`, for example `{repo: /tmp/run-1/todo-app}`, so checks can read it.

## 5. Test cases

| Field | Required | Meaning |
|---|---|---|
| `id` | Yes | Unique inside the eval. |
| `input` | Yes | What the agent receives. |
| `expected` | No | What each scorer expects, keyed by scorer name. See 6. |
| `tags`, `metadata` | No | Free labels and fields. |

`input` fields:

| Field | Meaning |
|---|---|
| `message` | One user message. Short for `messages: [{role: user, content: ...}]`. |
| `messages` | The conversation so far. Use it to start at any point of a real conversation. |
| `data` | A JSON object the agent receives, such as a task, a document or a record. An agent with no conversation uses only `data`. |
| `state` | The agent's state before the first turn. |
| `script` | Fixed inputs for the turns after the first, one per turn. An item is a user message (text or parts), or `{data: ...}` for an agent with no conversation, or `{message, data}` for both. |
| `persona` | A simulated user, in plain text: who they are, what they want, what they know and when they stop. |
| `max_turns` | Required with `persona`. The most turns the runner will run. |
| `stop_when` | Output values that end a multi-turn test case early, such as `{state.done: true}`. A list ends it when any item matches: `[{state.solved: true}, {state.handed_off: true}]`. |

There are two kinds of test case. The input decides which, so one eval can mix both:

| Kind | How it runs | Input |
|---|---|---|
| **Single-turn** | The runner calls the target once. An agent that makes many tool calls inside that one call is still single-turn. | `message`, `messages` or `data` |
| **Multi-turn** | The runner calls the target several times in a row, sending `state` back each time. | `script`, or `persona` with `max_turns` |

A multi-turn test case gets each next input in one of two ways:

- **Scripted.** `script` lists the inputs. The first turn uses `message`, `messages` or `data` if there is one; otherwise it uses the first script item. The test case ends after the last item. It suits chat replays and non-chat sequences alike, such as a task and then a follow-up for a coding agent.
- **Simulated.** `persona`. An LLM plays the user. It writes each next user message, and can end the conversation.

A multi-turn test case also ends at `max_turns`, or when `stop_when` matches the target's response on any turn. `stop_when` uses the same output paths as `equals`.

The simulated user gets the persona and the transcript. It replies with the next user message, or with exactly `[done]` to end the conversation. With no `message` or `messages`, it speaks first. The runner records which model played the user.

## 6. Scorers

| Field | Required | Meaning |
|---|---|---|
| `name` | Yes | Unique inside the eval. Shown in the result. |
| `check` | One of | A built-in check, or a custom check: `{command: ...}` or `{http: ...}`. |
| `judge` | One of | The name of a judge file. See 7. |
| `scope` | No | `trial` (default) or `run`. Only custom checks set it. |
| `params` | No | Settings for a custom check, such as `{k: 5}`. Sent to it on every call. |
| `pass` | No | A pass rule. |

A scorer reads its own entry in `expected`: the scorer `fields` reads `expected.fields`. So an eval can have many scorers of the same kind, each with its own expectations and pass rule.

A trial scorer scores each trial from 0 to 1. A built-in check skips a test case that has no entry for it. A judge runs on every test case and reads the entry if there is one. A run scorer scores the whole run once and returns a number. Run scorers go after every trial scorer, so they can read the trial scores. A skipped trial logs `score: null` and counts toward neither `mean` nor `failing_cases`.

Pass rules:

| Rule | For | Passes when |
|---|---|---|
| `{each: x}` | Trial scorers | Every trial scores at least x. |
| `{mean: x}` | Trial scorers | The mean over all trials is at least x. |
| `{min: x}` | Run scorers | The run's number is at least x. |
| `{max: x}` | Run scorers | The run's number is at most x. |

A scorer with no `pass` rule is reported but does not set the status. A runner rejects a trial rule on a run scorer, and the other way round.

Built-in checks:

| Check | Scope | Expected entry | Scores 1 when |
|---|---|---|---|
| `equals` | Trial | Output paths and values: `{data.queue: billing, state.handed_off: false}` | Every path has exactly that value. |
| `reply_contains` | Trial | Texts: `[refund, 5 days]` | Each text appears in at least one agent reply. |
| `reply_not_contains` | Trial | Texts: `[password, guaranteed]` | None of the texts appears in any agent reply. |
| `tool_called` | Trial | Tool names, or `{name, args}`: `[{name: refund, args: {amount: 20}}]` | Each listed tool was called at least once. Listed args must match; others are ignored. |
| `tool_not_called` | Trial | Tool names: `[delete_account]` | None of the listed tools was called. |
| `latency_p95_ms` | Run | None | Returns the 95th percentile of turn latency, in milliseconds (see 8). |
| `cost_per_trial_usd` | Run | None | Returns the mean cost of one trial, in US dollars. |

A trial check scores 1 or 0. `reply_contains` and `reply_not_contains` ignore case. `equals` and `tool_called` match exactly. An output path is dot-separated and starts with `reply`, `data`, `state`, `tool_calls` or `turns`: `data.queue`, `state.handed_off`, `tool_calls.0.name` or `turns.0.data.queue`. `reply`, `data` and `state` are what the agent returned on its last turn; `tool_calls` lists every turn's calls, in order; `turns` lists every response the target gave, in order, so a check can read any turn. A missing path never equals a value, not even `null`.

Put custom check scripts in a `checks/` folder next to the eval file, so `eval_hash` covers them.

A custom check is a command or URL that uses the same JSON in and out as the target:

- Trial scope gets `{input, output, expected, params, session_id}`, where `expected` is the scorer's own entry or `null`. It returns `{score, reason}`, or `{score: null}` to skip the trial. It can also return `value`, a raw number such as how far off an amount was. The row logs it, and pass rules ignore it.
- Run scope gets `{rows, params}`, where `rows` is every trial row of the run, with its scores (see 8). It returns `{score, reason}`.

## 7. Judges

A judge is a file, `<name>.judge.yaml`, in a `judges/` folder next to the eval file. It can judge any output: a reply, a summary, a record or a conversation.

```yaml
name: faithful
prompt: |
  Does the output state only facts found in the input?
  Pass if every claim is supported. Fail if any claim is not.
choices: {pass: 1, fail: 0}
```

| Field | Required | Meaning |
|---|---|---|
| `name` | Yes | The judge's name. Scorers refer to it. |
| `prompt` | Yes | What to judge, in plain language. |
| `choices` | No | Each answer and its score. Default `{pass: 1, fail: 0}`. |
| `model` | No | The model to use, as a name the runner understands. Default: the runner's judge model. |

The runner sends the judge model the prompt, the test case's input (with any files, if the model accepts them), the transcript and output, and the scorer's expected entry, if there is one (often a list of criteria, or a reference answer). The judge answers in JSON, `{reason, choice}`, giving its reason first. The runner logs both.

Prefer two choices. They are easier to agree on and to check against human labels. Before trusting a judge, check it against a few human labels.

## 8. The result

Each run writes a folder, `.oes/runs/<run_id>/`, in the agent's repository:

- `result.json`: the result of the run.
- `rows.jsonl`: one row per trial.

A runner may also send the same rows to an eval platform. The local files are the source of truth.

`result.json`:

| Field | Meaning |
|---|---|
| `eval`, `run_id`, `started_at` | The eval, a unique run id and when the run started. |
| `tags`, `metadata` | Copied from the eval. |
| `agent_version` | A label for the agent version under test, such as a git commit. |
| `models` | Every model that the run used, by role: `agent`, `judge`, `user`. Whatever names the runner knows. |
| `eval_hash` | SHA-256 over every file the eval uses: the eval file, its cases file, its judge files, its `{type: file}` inputs and the `checks/` folder, hashed in path order. Changing a test, a grader or an input changes the hash. A URL check is recorded by its URL only. |
| `status` | `passed`, `failed`, `error` or `not_evaluated`. |
| `scores` | Per scorer: `value` (the mean, or the run number), `passed` (true, false or null if no pass rule), `failing_cases`, and `reason` from a run scorer. |
| `latency_ms` | p50 and p95 of one turn, over every turn of the run. Percentiles use the nearest-rank method: the smallest value at or above that share of turns. |
| `cost_usd` | Mean cost of one trial, for the `agent`, the `judges` and the simulated `user`. |
| `cases` | `total`, the number of test cases, and `errored`, the ids of test cases that errored. |

Status, in order:

1. `error`: the run stopped, or a test case errored after retries.
2. `not_evaluated`: some test cases did not run, or a scorer with a pass rule scored nothing.
3. `failed`: at least one pass rule is not met.
4. `passed`: every pass rule is met.

`not_evaluated` is never a pass. No tool may change it to `passed`.

`failing_cases` lists the test cases that fall short on a trial scorer: a case with any trial below `x` for `{each: x}`, a case whose trials average below `x` for `{mean: x}`, or a case with any trial below 1 when the scorer has no pass rule. Run scorers have no `failing_cases`.

Each row in `rows.jsonl` has `case_id`, `trial`, `session_id`, `tags` (the test case's), `input`, `expected`, `output` (the `transcript`, `tool_calls` each with the `turn` it happened on, counting from 1, `turns` with every response the target gave, and the last `reply`, `data` and `state`), `scores` (per scorer: `score`, `reason` and any `value`), `latency_ms` (per turn), `cost_usd` and, if it errored, `error`.

Scorers read only the logged rows. A custom check gets `input` and `output` in this same shape, with file paths made absolute. So a runner can re-score a saved run without calling the agent again.

### 8.1 Errors

A trial can fail for a reason outside the agent's logic: the target crashes, a check, a judge or the simulated user breaks, or a call times out. The runner retries it first. If it still fails, the row gets `error: {kind, message}`, with `kind` of `target`, `check`, `judge`, `user` or `timeout`, and no scores.

### 8.2 Comparing runs

To compare two versions of an agent, run the eval on each and compare the two results. Compare runs only when they have the same `eval_hash` and the same judge and user models. Otherwise the change in score may come from the eval, not the agent. A saved result can be reused as the baseline while all of these stay the same.

## 9. Rules

1. Check each eval file against `eval.schema.json`. Unknown fields are errors, except inside `metadata`, `data`, `state` and `expected`.
2. A runner rejects an eval with two test cases or two scorers of the same name, or with an `expected` key that names no scorer. A typo there would otherwise skip a check without a word. Judge files have only the four fields in 7; the runner checks them.
3. An eval must be able to fail. Run it once against a target that returns an empty response, `{}`. If it passes, the test cases or scorers are too weak. The exception is an eval that only checks that something does not happen, such as `tool_not_called`.
4. A change that breaks existing evals raises `oes`. A new optional field does not.
5. To add a built-in check, add a row to the table in 6.
