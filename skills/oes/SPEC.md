# Open Eval Standard (OES)

Version 1, draft 5.

## 1. Purpose

The Open Eval Standard (OES) is a standard way to write evals of AI agents, as plain files. An eval says what to send the agent, what to expect back and how to score it. Any runner that follows this spec can run any eval written to it, in any language, with any model provider.

An agent here is any AI system that takes an input and replies or acts: a chatbot, an assistant that uses tools, a coding agent, or a single model call. The agent does not change how it is built. It exposes one entry point, the target, that the runner calls.

In this spec, "must", "never" and "rejects" are requirements for runners. A runner that meets them all, and passes the conformance suite in `conformance/`, is a conforming runner.

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

Eval and judge files are YAML 1.2, core schema. A runner rejects duplicate keys and files with more than one YAML document. Values are compared as JSON, so quote text that YAML could read as something else: `"no"`, `"0755"`, `"1.10"`, `"2026-04-15"`. A cases file is JSONL: one JSON object per line, blank lines ignored.

Names of evals, scorers and judges use lowercase letters, digits, hyphens and underscores. Paths in an eval file, and in its cases file, are relative to the eval file. Commands, for targets and custom checks, run from the repository root: the folder the runner is started in.

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

Either form can add `timeout_s`, the most seconds one call may take, such as `{command: "...", timeout_s: 600}`. The default is 300.

Request:

| Field | Meaning |
|---|---|
| `session_id` | A new id for each trial attempt. The same id for every turn of one attempt. |
| `messages` | The transcript so far, including the agent's earlier replies. On a turn with a new user message, it ends with that message. `[]` if there is nothing yet. |
| `data` | The test case's `input.data`, or `{}`. On a script turn with `data`, that `data` is merged over `input.data`: its keys win, and the other keys stay. |
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

### 4.1 Calling the target

A `command` runs through `/bin/sh -c`, from the repository root, with the runner's environment. Its stdout must be one JSON object. If the whole of stdout isn't, the runner reads its last non-empty line, so an agent can print logs first. stderr is ignored, except in error messages. A non-zero exit is an error, even if stdout holds valid JSON.

An `http` target gets a POST with `Content-Type: application/json`. A status outside 200 to 299 is an error.

A response that isn't a JSON object is an error. So is a `reply` that isn't text, a `state` that isn't an object, `tool_calls` that isn't a list of objects with a text `name`, or a `cost_usd` that isn't a number. Other fields are kept in `turns`.

When a target looks after its own tools, so the runner can't see them, the target reports them itself in `tool_calls`. An agent whose tools are internal needs a small hook that records each call.

### 4.2 Files

A file can go in a message part, or anywhere in `data` or a script item, as a `{type: file, path, mime}` object. `path` can be a file or a folder, and `mime` is optional. Any object with `type: file` and a text `path` counts.

Each trial gets its own copy of every file and folder, inside the run folder, and the request carries the copy's absolute path. So an agent can change its files freely, and the files stay with the run. A source used twice in one trial is copied once. A retried trial gets fresh copies.

This assumes the target can read the runner's files: the same machine, or a shared folder or volume. For a remote target, put a URL in `data` instead. An agent that changes files, such as a coding agent, returns where its work is in `data`, for example `{repo: /abs/path/todo-app}`, so checks can read it.

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
| `script` | Fixed inputs for later turns, one per turn. An item is a user message (text or parts), or `{data: ...}` for an agent with no conversation, or `{message, data}` for both. |
| `persona` | A simulated user, in plain text: who they are, what they want, what they know and when they stop. |
| `max_turns` | The most turns the runner will run. Required with `persona`. Allowed with `script`, where it can end the case early. |
| `stop_when` | Output values that end a multi-turn test case early, such as `{state.done: true}`. A list ends it when any item matches: `[{state.solved: true}, {state.handed_off: true}]`. |

There are two kinds of test case. The input decides which, so one eval can mix both:

| Kind | How it runs | Input |
|---|---|---|
| **Single-turn** | The runner calls the target once. An agent that makes many tool calls inside that one call is still single-turn. | `message`, `messages` or `data` |
| **Multi-turn** | The runner calls the target several times in a row, sending `state` back each time. | `script`, or `persona` with `max_turns` |

A multi-turn test case gets each next input in one of two ways:

- **Scripted.** `script` lists the inputs. The first turn uses `message`, `messages` or `data` if there is one; otherwise it uses the first script item. The test case ends after the last item. It suits chat replays and non-chat sequences alike, such as a task and then a follow-up for a coding agent.
- **Simulated.** `persona`. An LLM plays the user. It writes each next user message, and can end the conversation. Every turn sends `input.data`.

A multi-turn test case also ends at `max_turns`, or when `stop_when` matches. The runner checks `stop_when` after every turn, the first included. It uses the same output paths and matching as `equals`: every path in one object must match, and a list matches when any of its objects does.

The simulated user gets the persona and the transcript, not `data`, `state` or tool calls. It replies with the next user message, or with exactly `[done]` (after trimming spaces) to end the conversation. It speaks first when the input has no `message` or `messages`, or when `messages` ends with an `assistant` message. If it ends the conversation before the first turn, the test case did not run. The runner records which model played the user.

## 6. Scorers

| Field | Required | Meaning |
|---|---|---|
| `name` | Yes | Unique inside the eval. Shown in the result. |
| `check` | One of | A built-in check, or a custom check: `{command: ...}` or `{http: ...}`. |
| `judge` | One of | The name of a judge file. See 7. |
| `scope` | No | `trial` (default) or `run`. Only custom checks set it. |
| `params` | No | Settings for a custom check, such as `{k: 5}`. Sent to it on every call. |
| `pass` | No | A pass rule. |

A scorer reads its own entry in `expected`: the scorer `fields` reads `expected.fields`. So an eval can have many scorers of the same kind, each with its own expectations and pass rule. An entry of `null` is the same as no entry.

A trial scorer scores each trial from 0 to 1. A built-in check skips a test case that has no entry for it. A judge and a custom trial check run on every test case, and read the entry if there is one. A run scorer scores the whole run once and returns a number. Trial scorers run in file order on each trial, after its last turn. Run scorers go after every trial, in file order, so they can read the trial scores. A skipped trial logs `score: null` and counts toward neither `mean` nor `failing_cases`.

A scorer that gates the run should have an entry in every test case it is meant to cover. The result reports how many trials each scorer scored and skipped, so a gap shows.

Pass rules:

| Rule | For | Passes when |
|---|---|---|
| `{each: x}` | Trial scorers | Every scored trial scores at least x. |
| `{mean: x}` | Trial scorers | The mean over all scored trials is at least x. |
| `{min: x}` | Run scorers | The run's number is at least x. |
| `{max: x}` | Run scorers | The run's number is at most x. |

A scorer with no `pass` rule is reported but does not set the status. A runner rejects a trial rule on a run scorer, and the other way round. Comparisons allow for rounding: a mean of 0.7999999999 meets `{mean: 0.8}`.

Built-in checks:

| Check | Scope | Expected entry | Scores 1 when |
|---|---|---|---|
| `equals` | Trial | Output paths and values: `{data.queue: billing, state.handed_off: false}` | Every path has exactly that value. |
| `reply_contains` | Trial | Texts: `[refund, 5 days]` | Each text appears in at least one agent reply. |
| `reply_not_contains` | Trial | Texts: `[password, guaranteed]` | None of the texts appears in any agent reply. |
| `tool_called` | Trial | Tool names, or `{name, args}`: `[{name: refund, args: {amount: 20}}]` | Each listed tool was called at least once. Every listed arg matches in that one call; other args are ignored. A call that returned an error still counts. |
| `tool_not_called` | Trial | Tool names: `[delete_account]` | None of the listed tools was called. |
| `latency_p95_ms` | Run | None | Returns the 95th percentile of turn latency, in milliseconds (see 8). |
| `cost_per_trial_usd` | Run | None | Returns the agent's mean cost per trial, in US dollars. If the agent never reports a cost, it returns `null`: unknown, not zero. |

A trial check scores 1 or 0. A runner rejects a built-in entry of the wrong shape, such as a single text where `reply_contains` needs a list.

**Text.** `reply_contains` and `reply_not_contains` look in every reply, ignoring case. A trial with no replies fails `reply_contains` and passes `reply_not_contains`.

**Output paths.** A path is dot-separated and starts with `reply`, `data`, `state`, `tool_calls` or `turns`: `data.queue`, `state.handed_off`, `tool_calls.0.name` or `turns.0.data.queue`. `reply`, `data` and `state` are what the agent returned on its last turn. `tool_calls` lists every turn's calls, in order, each with the `turn` it happened on, counting from 1. `turns` lists every response the target gave, in order. A number segment indexes a list, counting from 0, and is a key on an object. A key that contains a dot can't be reached. A runner rejects a path with another start.

**Equality.** Values compare as JSON, deeply: object key order doesn't matter, list order does, and there's no conversion between types. So `1` equals `1.0`, `true` doesn't equal `1`, and `"5"` doesn't equal `5`. A `null` that is present equals `null`. A missing path never equals a value, not even `null`. Text matches exactly, case included.

**Custom checks.** Put their scripts in a `checks/` folder next to the eval file, so `eval_hash` covers them. A custom check is a command or URL called the same way as a target (4.1), with the same JSON in and out:

- Trial scope gets `{input, output, expected, params, session_id}`, where `expected` is the scorer's own entry or `null`, and `params` is `{}` if not set. It returns `{score, reason}`: a score from 0 to 1, or `null` to skip the trial. It can also return `value`, a raw number such as how far off an amount was. The row logs it, and pass rules ignore it. Any other score is a `check` error.
- Run scope gets `{rows, params}`, where `rows` is every trial row of the run, errored ones included, with their scores (see 8). It returns `{score, reason}`, where the score is any number, or `null` if it couldn't measure.

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
| `name` | Yes | The judge's name. It matches the file name, and scorers refer to it. |
| `prompt` | Yes | What to judge, in plain language. |
| `choices` | No | Each answer and its score, from 0 to 1. Default `{pass: 1, fail: 0}`. |
| `model` | No | The model to use, as a name the runner understands. Default: the runner's judge model. |

The runner sends the judge model the prompt, the test case's input (with any files, if the model accepts them), the transcript and output, and the scorer's expected entry, if there is one (often a list of criteria, or a reference answer). The judge answers in JSON, `{reason, choice}`, giving its reason first. A choice matches ignoring case. An answer that isn't valid JSON, or names no listed choice, is a `judge` error. The row logs `score`, `reason` and `choice`.

How a runner reaches a model is up to the runner, and so is the wording around the judge prompt and the simulated user. That's why results record the runner (8).

Prefer two choices. They are easier to agree on and to check against human labels. Before trusting a judge, check it against a few human labels.

## 8. The result

Each run writes a folder, `.oes/runs/<run_id>/`, in the agent's repository:

- `result.json`: the result of the run.
- `rows.jsonl`: one row per trial.
- `files/`: the trial copies of any input files.

`run_id` must be unique, even for runs that start in the same second. A runner may also send the same rows to an eval platform. The local files are the source of truth.

`result.json`:

| Field | Meaning |
|---|---|
| `eval`, `run_id`, `started_at` | The eval, the run id and when the run started, in ISO 8601 UTC. |
| `runner` | `{name, version}` of the runner. |
| `tags`, `metadata` | Copied from the eval. |
| `agent_version` | A label for the agent version under test, such as a git commit, or `null`. |
| `models` | Every model that the run used, by role: `agent`, `judge`, `user`. Whatever names the runner knows, or `null`. |
| `eval_hash` | See 8.2. |
| `status` | `passed`, `failed`, `error` or `not_evaluated`. |
| `scores` | Per scorer. Trial scorers: `value` (the mean of scored trials), `passed`, `scored` and `skipped` (numbers of trials), and `failing_cases`. Run scorers: `value`, `passed` and `reason`. `passed` is `null` when there is no pass rule or nothing was scored. |
| `latency_ms` | `p50` and `p95` of one turn, over every turn of trials that didn't error. |
| `cost_usd` | Mean cost of one trial, over trials that didn't error, for the `agent`, the `judges` and the simulated `user`. The agent's mean covers only trials where it reported a cost, and is `null` if it never did. For judges and the user, a trial with no such call counts as 0, and the value is `null` if the run made none. |
| `cases` | `total`, the number of test cases, and `errored`, the ids of test cases that errored. |

Percentiles use the nearest-rank method: sort the values and take the one at position `ceil(p / 100 × n)`, counting from 1.

Status, in order:

1. `error`: the run stopped, a test case errored after retries, or a run scorer errored.
2. `not_evaluated`: some test cases did not run, or a scorer with a pass rule scored nothing.
3. `failed`: at least one pass rule is not met.
4. `passed`: every pass rule is met.

`not_evaluated` is never a pass. No tool may change it to `passed`. A cost gate on an agent that reports no cost is `not_evaluated`.

`failing_cases` lists, in file order, the test cases that fall short on a trial scorer: a case with any scored trial below `x` for `{each: x}`, a case whose scored trials average below `x` for `{mean: x}`, or a case with any scored trial below 1 when the scorer has no pass rule.

Each row in `rows.jsonl` has:

| Field | Meaning |
|---|---|
| `case_id`, `trial` | The test case, and the trial counting from 1. |
| `session_id`, `attempts` | The id of the attempt recorded, and how many attempts the trial took. |
| `tags` | The test case's tags, or `[]`. |
| `input` | The input as sent, with file paths pointing at the trial copies. |
| `expected` | The test case's `expected`, or `{}`. |
| `output` | `transcript`, `tool_calls`, `turns`, and the last turn's `reply`, `data` and `state`. A key the last turn didn't return is left out. |
| `scores` | Per scorer: `score`, `reason`, plus `value` for custom checks and `choice` for judges. |
| `latency_ms` | One number per turn. |
| `cost_usd` | `{agent, judges, user}` for this trial, each `null` when unknown. |
| `error` | Only if it errored: `{kind, message}`. |

Scorers read only the logged rows, and a custom check gets `input` and `output` in this same shape. So a runner can re-score a saved run without calling the agent again.

### 8.1 Errors and retries

A trial can fail for a reason outside the agent's logic: the target crashes or returns something invalid, a check, a judge or the simulated user breaks, or a call times out. The `kind` is `target`, `check`, `judge`, `user` or `timeout`.

The runner retries up to 2 times by default, and must let the user set this to 0. Retries go like this:

- When the target or the simulated user fails, the whole trial runs again, with a new `session_id` and fresh file copies.
- When a check or a judge fails, only that scorer runs again, on the logged row. The agent is never called again because a grader failed.
- When a run scorer fails, it runs again on its own.

If it still fails, the row gets `error: {kind, message}` and no scores. The row keeps the last attempt's partial output and latency. Errored trials count toward no score, latency or cost. Cost and latency come from the attempt that was recorded.

Retrying calls the agent again. For an agent with real side effects, such as sending email or charging a card, set retries to 0 or point it at a test environment.

### 8.2 The eval hash

`eval_hash` is `sha256:` followed by the lowercase hex SHA-256 of this byte stream:

1. Take every file the eval uses: the eval file, its cases file, the judge files its scorers name, every `{type: file}` input (a folder counts as every regular file inside it), and every regular file in the `checks/` folder next to the eval file.
2. Leave out `__pycache__` folders, `.pyc` files and `.DS_Store` files.
3. Write each path relative to the eval file's folder, with `/` between parts, and sort the paths by their UTF-8 bytes.
4. For each file in that order, add the path's UTF-8 bytes, a zero byte, the file's length in bytes as decimal digits, a zero byte, and the file's bytes.

So changing a test, a grader or an input changes the hash, and moving the whole repository doesn't. A URL check counts only through its URL in the eval file, so a change behind the URL doesn't show. Test vectors are in `conformance/`.

### 8.3 Comparing runs

To compare two versions of an agent, run the eval on each and compare the two results. Compare runs only when they have the same `eval_hash`, the same `runner` and the same judge and user models. Otherwise the change in score may come from the eval or the grading, not the agent. A saved result can be reused as the baseline while all of these stay the same. A matching hash is needed for a fair comparison, but it doesn't prove one: a model behind the same name can change.

### 8.4 The command line

A runner offers these commands, so any runner can be tested the same way:

- `run <eval file>` runs the eval. Its last line of stdout is the run folder's absolute path. It exits 0 for `passed`, 1 for any other status, and 2 for an invalid eval, without running it.
- `validate <eval file>` checks the eval and its judge files without calling anything. It exits 0 if valid, 2 if not.

A runner rejects, with exit 2, any eval that uses something it doesn't support. It never scores what it can't run.

## 9. Rules

1. Check each eval file against `eval.schema.json`. Unknown fields are errors, except inside `metadata`, `data`, `state` and `expected`.
2. A runner rejects an eval with two test cases or two scorers of the same name, an `expected` key that names no scorer, a missing cases, judge or input file, or a judge file with fields other than the four in 7.
3. An eval must be able to fail. Run it once against a target that returns an empty response, `{}`. If it passes, the test cases or scorers are too weak. The exception is an eval that only checks that something does not happen, such as `tool_not_called`.
4. A change that breaks existing evals raises `oes`. A new optional field does not.
5. To add a built-in check, add a row to the table in 6, and a test to `conformance/`.
