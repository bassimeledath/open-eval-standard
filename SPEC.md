# Open Eval spec

Version 1, draft. Status: under review.

## 1. Purpose

Open Eval is a plain file format for evals of AI apps. An eval says what to send the app, what we expect back and how to score it. Any runner that follows this spec can run any eval written to it.

It applies to any AI app: a chatbot, a voice agent, a tool-using agent, a classifier or a single model call. The app does not change how it is built. It exposes one entry point, the target, that the runner calls.

Field names follow common practice (`input`, `expected`, `metadata`, `tags`), so test cases move easily to and from eval tools that use the same names.

## 2. Terms

| Term | Meaning |
|---|---|
| Eval | A named group of test cases for one app, plus how to call the app and how to score it. One file. |
| Test case | One input, with the behavior we expect. |
| Single-turn eval | Sends one input, gets one output, scores it. The input can include the conversation so far. |
| Multi-turn eval | Runs a conversation, with a simulated user or a fixed script, and scores all of it. |
| Target | The app entry point the runner calls. |
| Scorer | Gives a test case a score from 0 to 1. A check runs code. A judge asks an LLM. |
| Trial | One attempt at one test case. A test case can run several trials. |
| Run | One execution of one eval on one version of the app. |
| Candidate | The version of the app under test. |
| Baseline | The version we compare with, normally the current one. |
| Result | The scores, cost, latency and status of a run. |
| Runner | The program that reads eval files, calls the target, scores the output and writes the result. |

## 3. The eval file

Write one eval per file, named `<name>.eval.yaml`, in an `evals/` folder in the app's repository. The eval does not name the model or the app version. The run supplies them, so one eval runs on both the candidate and the baseline.

### 3.1 Eval fields

| Field | Required | Meaning |
|---|---|---|
| `openeval` | Yes | The spec version. Use `1`. |
| `name` | Yes | Unique in the repository. Lowercase letters, digits and hyphens. |
| `kind` | Yes | `single_turn` or `multi_turn`. |
| `target` | Yes | How to call the app. See 3.2. |
| `scorers` | Yes | See 3.6. At least one scorer has a `pass` rule. |
| `cases` | Yes | A list of test cases, or a path to a JSONL file of them: `{file: cases/intent.jsonl}`. |
| `description` | No | One sentence on what the eval checks. |
| `trial_count` | No | Trials per test case. Default 1. |
| `tags`, `metadata` | No | Free labels and fields, copied to the run. |

### 3.2 The target

The target is one of:

| Form | Meaning |
|---|---|
| `{command: "python -m app.eval_entry"}` | The runner starts the command once per call, writes the request as JSON to stdin and reads the response as JSON from stdout. |
| `{http: "http://localhost:8000/eval"}` | The runner POSTs the request as JSON and reads the response as JSON. |
| `{function: "app/eval_entry.py:respond"}` | The runner imports the function and calls it with the request. Only for runners in the same language as the app. |

The runner calls the target once per app turn.

Request:

| Field | Meaning |
|---|---|
| `session_id` | A new id for each trial of each test case. The same id for every turn of one conversation. |
| `messages` | The conversation so far, as `{role, content}` items, with `role` of `user` or `assistant`. The last item is the newest user message. Empty if the app speaks first. |
| `data` | The test case's `input.data`, or `{}`. |
| `start_state` | The test case's `input.start_state`, on the first turn only. |

Response (every field optional):

| Field | Meaning |
|---|---|
| `reply` | The app's reply text for this turn. |
| `data` | Any JSON the app returns, such as a label or an extracted record. |
| `tool_calls` | `{name, args}` for each tool the app called this turn. |
| `actions` | Actions the app emitted, such as `handoff` or `end_conversation`. |
| `state` | App state after this turn. |
| `cost_usd` | What this turn cost, if the app knows. |

The runner measures latency itself.

### 3.3 Test case fields

| Field | Required | Meaning |
|---|---|---|
| `id` | Yes | Unique inside the eval. |
| `input` | Yes | What the app receives. See 3.4. |
| `expected` | No | What we expect. Scorers read it. See 3.6. |
| `tags`, `metadata` | No | Free labels and fields. |

### 3.4 Input fields

| Field | Kind | Meaning |
|---|---|---|
| `message` | Single-turn | The user's message. Short for `messages: [{role: user, content: ...}]`. |
| `messages` | Both | The conversation so far. Use it to start a test case at any turn, for example from a real transcript. |
| `data` | Both | Any other JSON the app receives. An app with no conversation uses only `data`. |
| `start_state` | Both | App state to set before the first turn. |
| `persona` | Multi-turn | The simulated user, in plain text: who they are, what they want, what they know and when they stop. |
| `script` | Multi-turn | Fixed user lines, sent in order. Use instead of `persona` to replay a conversation. |
| `max_turns` | Multi-turn | Required. The runner stops the conversation after this many app turns. |
| `stop_when` | Multi-turn | Output values that end the conversation, for example `{state.done: true}` or `{actions: end_conversation}`. |

A single-turn input has `message`, `messages` or `data`. A multi-turn input has `persona` or `script`.

In a multi-turn eval, the runner plays the user. With `persona`, an LLM plays the persona and can end the conversation. With `script`, the runner sends the lines in order and stops after the last one. The conversation also stops at `max_turns` or when `stop_when` matches.

### 3.5 The output

For each trial, the runner logs:

| Field | Meaning |
|---|---|
| `transcript` | Every turn, as `{role, content}` items. The last assistant turn is the reply. |
| `data` | The last `data` the app returned. |
| `tool_calls` | Every tool call, in order. |
| `actions` | Every action, in order. |
| `state` | The last `state` the app returned. |
| `latency_ms` | Per turn. |
| `cost_usd` | Per turn, if the app reported it. |

Scorers read only the logged input, output and expected values. So a runner can re-score a saved run, for example with a new judge version, without calling the app again.

### 3.6 Scorers and pass rules

| Field | Required | Meaning |
|---|---|---|
| `name` | Yes | Name shown in the result. |
| `check` | One of | A built-in check, or `path/file.py:function` for a custom one. |
| `judge` | One of | A judge and its version, such as `goal_completion@2`. |
| `params` | No | Values for the check, such as `{value: 4000}`. |
| `pass` | No | A pass rule. See below. |

Pass rules:

- `{each: x}`: every trial of every test case scores at least x.
- `{mean: x}`: the mean over all test cases and trials is at least x.
- `{vs_baseline: -x}`: the candidate's mean is no more than x below the baseline's.

A scorer with no `pass` rule is reported but does not set the status.

Built-in checks:

| Check | Reads | Scores 1 when |
|---|---|---|
| `tool_called` | `expected.tools_called` | Every listed tool was called. An item is a name, or `{name, args}` to match some arguments. |
| `tool_not_called` | `expected.tools_not_called` | None of the listed tools was called. |
| `action_present` | `expected.actions` | Every listed action is in the output. |
| `equals` | `expected.equals` | Every listed output path has the listed value, such as `state.escalated: false` or `data.label: refund`. |
| `reply_contains` | `expected.reply_contains` | The reply contains every listed text. |
| `latency_max_ms` | `params.value` | Every turn took no more than the value. |
| `cost_max_usd` | `params.value` | The trial cost no more than the value. |

A check skips a test case that has no matching `expected` key. Skipped test cases do not count toward `each` or `mean`.

A custom check is a function that takes `(input, output, expected, params)` and returns a score from 0 to 1, or `None` to skip.

Judges read `expected.rules` (plain-English rules, including what must not happen) and `expected.reference` (a reference answer or transcript).

### 3.7 Judges

A judge is a file in the repository, `<name>.judge.yaml`, in `evals/judges/`:

```yaml
name: goal_completion
version: 2
uses: [transcript, input, expected]
prompt: |
  Judge whether the assistant got the user to the right outcome.
  - "pass": the problem is solved, or the assistant hands off correctly.
  - "partial": there was progress, but no clear next step.
  - "fail": the assistant misunderstood, gave wrong guidance, or looped.
choices: {pass: 1.0, partial: 0.5, fail: 0.0}
model: null   # null = the runner's default judge model
```

- The judge gives its reason, then its choice. The runner logs both.
- A judge can read the candidate and baseline outputs side by side: `uses: [output, baseline_output]`.
- A change to `prompt`, `choices` or `model` is a new version. A new version never changes an old run.
- The result records the judge version and the model that actually ran. Compare a candidate and a baseline only when both match.
- Before trusting a judge, check it against a small set of human labels.

### 3.8 Errors

A test case can fail for a reason outside the app: the judge or the simulated user breaks, or a call times out. The runner retries it first. If it still fails, the runner logs no score and an `error_kind` (`target`, `judge`, `simulator` or `timeout`). The test case does not count toward `each` or `mean`, and it is counted in `cases.errored`.

## 4. Examples

Single-turn eval, for an app with no conversation:

```yaml
openeval: 1
name: ticket-triage
kind: single_turn
description: The app labels each support ticket with the right queue.
target: {command: "python -m triage.eval_entry"}
scorers:
  - {name: right_queue, check: equals, pass: {mean: 0.9}}
  - {name: fast_enough, check: latency_max_ms, params: {value: 2000}, pass: {mean: 0.95}}
cases:
  - id: refund-request
    input:
      data: {subject: "Charged twice", body: "I was billed two times for one order."}
    expected:
      equals: {data.queue: billing}
```

Multi-turn eval, with a simulated user:

```yaml
openeval: 1
name: wifi-troubleshooting
kind: multi_turn
description: A user cannot get a laptop online. The assistant must fix it or hand off.
target: {http: "http://localhost:8000/eval"}
trial_count: 3
scorers:
  - {name: goal_completion, judge: goal_completion@2, pass: {mean: 0.8}}
  - {name: no_handoff, check: equals, pass: {each: 1.0}}
cases:
  - id: forgot-network
    input:
      persona: >
        A calm adult whose laptop stopped joining home wifi after an update.
        Other devices work; say so only if asked. Stop when it works or you are handed off.
      max_turns: 20
    expected:
      equals: {state.handed_off: false}
      rules:
        - Asks what changed before suggesting fixes.
        - Never asks for the wifi password.
```

## 5. The result

One run of one eval makes one result.

| Field | Meaning |
|---|---|
| `eval`, `run_id` | The eval and a unique run id. |
| `status` | `passed`, `failed`, `error` or `not_evaluated`. |
| `candidate` | `label`, `version` and `model` of the version under test. |
| `baseline` | The same fields. Empty on a run with nothing to compare. |
| `eval_hash` | A hash of the eval file, its test cases and its judge versions. |
| `scores` | Per scorer: candidate mean, baseline mean, the change, and whether the pass rule is met. |
| `cost_usd` | Mean cost of one trial, for the app and for the judges, candidate and baseline. |
| `latency_ms` | p50 and p95 of one turn, candidate and baseline. |
| `cases` | `total`, `passed`, `failed`, `errored`, with the ids of failed and errored test cases. |

Status values:

- `passed`: the candidate meets every `pass` rule, and no test case errored.
- `failed`: at least one `pass` rule is not met.
- `error`: the run stopped, or a test case errored after retries.
- `not_evaluated`: the run covered only some of the test cases, or a scorer with a `pass` rule scored nothing.

`not_evaluated` is never a pass. No tool may change it to `passed`.

A baseline result can be reused: compare the candidate with the latest baseline run that has the same `eval_hash` and judge models. Run the baseline again only when one of those changed.

### 5.1 Where results go

By default, the runner writes each run to `.openeval/runs/<run_id>/` in the app's repository:

- `result.json`: the result above.
- `rows.jsonl`: one row per trial, with `id` (`{run_id}::{case_id}::{trial}`), `input`, `output`, `expected`, `scores`, `metrics` (latency and cost), `tags` and `metadata`.

A runner may also write the same rows to an eval platform. The local files stay the source of truth for this spec.

## 6. Rules

1. Check each eval file against `schema/eval.schema.json`. Unknown top-level fields are errors. Put app-specific fields in `metadata`.
2. Run each eval once against an empty target that replies with nothing and calls no tools. If the eval passes, it cannot catch a broken app. Fix the eval.
3. A change that breaks existing evals raises `openeval`. A new optional field does not.
4. To add a built-in check, add its name and the `expected` key it reads to the table in 3.6.

## 7. Open questions

1. **Whole-run metrics.** `each` and `mean` cannot express F1, p90 latency or a count of false claims. Add a `metric` pass rule?
2. **Voice.** Noise, interruptions and time to first audio. Do they become input fields, or stay in `metadata`?
3. **Shared personas.** Keep persona files that many evals can reference?
4. **Eval index.** A project file listing every eval with its owner and what it depends on, so a runner can pick the evals a change affects?
5. **Decisions.** Record whether a change was adopted, rejected or deferred, next to the results?
