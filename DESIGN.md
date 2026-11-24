# OES design

## What it is

The Open Eval Standard (OES) is one simple way to write tests for AI agents. These tests are called evals.

By agent we mean any AI system that takes an input and replies or acts: a chatbot, an assistant that uses tools, a coding agent, or a single model call that labels or extracts something.

An eval is a file. It lists tasks or inputs to give your agent, says what a good output looks like, and says how good the agent has to be to pass. A program called a runner reads the file, runs each one on your agent, scores the outputs and writes down what happened.

## Why

Every project that uses AI ends up inventing its own way to test it. The tests live in one-off scripts, each in a different shape, and they're hard to reuse or compare. Each new project starts from zero.

OES is one shape that fits most AI agents, from a single model call to an agent that uses tools over many steps. Write evals the same way in every project, and any runner, or any coding agent, can work with them.

## The pieces

There are five.

1. **The eval file.** One YAML file per eval, kept in the agent's own repository.
2. **Test cases.** Each one is something to send the agent, plus what we expect.
3. **The target.** How the runner reaches the agent: a command it runs, or a URL it calls. The agent sends back its output: a text reply, structured data, the tools it used or its updated state.
4. **Scorers.** How each try is graded, from 0 to 1. A **check** is a bit of code ("did it pick the billing queue?"). A **judge** asks an AI model ("did it solve the problem?"). Each scorer can have a **pass rule**, such as "90% of tries must pass".
5. **The result.** What the run produced: the scores, whether it passed, how long it took and what it cost. It's saved as plain files in the project.

## How a run works

1. The runner reads the eval file.
2. For each test case, it sends the input to the agent and collects the output. For a multi-turn case, it keeps going turn by turn.
3. It scores each try with every scorer.
4. It checks the pass rules and writes the result.

## Two kinds of test case

Every test case uses the same fields. What you put in the input decides how it runs, so one eval can mix both kinds.

- **Single-turn.** Call the agent once and score what comes back: answer a question, label a ticket, pull the total out of an invoice. This covers most agents, including one that makes many tool calls inside one request.
- **Multi-turn.** Call the agent several times in a row, passing its state along. The next input comes one of two ways:
  - **Scripted:** a fixed list, written in advance. A chat replay, or a coding task followed by "now add tests".
  - **Simulated:** an AI model plays the user from a short description ("a calm adult whose laptop won't connect to wifi"). Good when the user's replies need to react to what the agent says. It's the least predictable, so run these a few times each.

## Design choices

**Plain files.** Evals are YAML, and results are JSON. You can read them, review them in a pull request and keep them in git. No service is needed.

**Works with anything.** The format never names a model provider, a language or a framework. The runner decides which models play judges and users. The agent only needs a command or a URL that takes JSON and returns JSON.

**The agent doesn't change.** You add a small entry point. The agent itself stays as it is.

**Code before AI.** Use a check when code can tell if an answer is right. Use a judge only when it can't. Checks are fast, free and never change their minds.

**Each scorer reads its own expectations.** In a test case, `expected` has one entry per scorer, under the scorer's name. So one eval can have several scorers of the same kind, each with its own pass rule.

**One run stands alone.** A result describes one run of one version of the agent. To compare two versions, compare their results, but only when the eval and the judges are the same in both.

**Not evaluated is not a pass.** If something didn't run, the result says so. Nothing is allowed to turn that into a pass.

**An eval must be able to fail.** Before trusting an eval, run it once against an agent that returns nothing. If it still passes, it isn't testing anything.

## Left out on purpose

- **A runner.** The format comes first. A coding agent can write a small runner for any project from the spec, and a shared one can come later.
- **Voice-specific fields** like interruptions or background noise. Voice agents that work turn by turn fit already. The rest can live in `metadata` until there's a clear pattern.
- **A list of every eval across projects**, and **a record of whether a change was adopted.** Useful for teams, but not needed to test one agent.
- **Side-by-side judging**, where a judge sees two versions' outputs at once. It needs care to be fair, and it can be added later.

## How it grows

The core stays small. New uses go in docs and cookbooks first, built from what's already there:

- **Custom checks**, in any language. A check is a command or URL that gets JSON and returns a score.
- **Judges** for any quality that's easier to describe than to code.
- **Whole-run scores**, like accuracy across all test cases or the slowest 5% of turns.
- **`metadata`, `data` and `state`**, open fields for anything specific to one agent.

Cookbook ideas: coding agents, browser agents, search-based agents (RAG), structured output, voice, images and documents, and turning real failures into test cases.

A new field joins the format only when a real use case can't be covered by these.

## The exact shapes

The whole format is built from the eight shapes below. Each one lists every field it has; there are no others. Fields marked `required` must be there, and everything else is optional. The files you write are YAML. Everything sent between the runner and the agent, checks and models is JSON with the same fields.

| Shape | Fields | Required |
|---|---|---|
| Eval file | 9 | 5 |
| Test case | 5 | 2 |
| Input | 8 | at least 1 |
| Message | 2 | 2 |
| Scorer | 6 | 1, plus a check or a judge |
| Judge | 4 | 2 |
| What the runner sends the agent | 4 | 4 |
| What the agent sends back | 5 | 0 |

### Eval file

```yaml
oes: 1                           # required. The spec version
name: ticket-triage              # required. Lowercase letters, digits, - and _
target: {command: "python -m triage.eval_entry"}   # required. Or {http: "http://..."}
                                 # either can add timeout_s: 60
scorers: [ ... ]                 # required. At least one has a pass rule
cases: [ ... ]                   # required. Or {file: cases.jsonl}
description: One sentence on what it checks.
trial_count: 1                   # tries per test case
tags: []
metadata: {}                     # anything else
```

### Test case

```yaml
id: charged-twice                # required. Unique in the eval
input: { ... }                   # required. See below
expected:                        # one entry per scorer, under the scorer's name
  right-queue: {data.queue: billing}
tags: []
metadata: {}
```

### Input

At least one of `message`, `messages`, `data`, `script` or `persona`. With `script` or `persona` it's multi-turn; otherwise single-turn.

```yaml
message: "I was billed twice."   # one user message
messages: [ ... ]                # or the conversation so far, as messages
data: {}                         # a JSON object the agent takes. Files and folders: {type: file, path}
state: {}                        # the agent's state before the first turn
script: ["It's order 1042", {data: {task: "Now add tests"}}]   # inputs for later turns: messages or data. Ends after the last one
persona: A calm adult whose laptop won't join wifi.   # an AI plays this user
max_turns: 20                    # required with persona
stop_when: {state.done: true}    # end early when the agent returns this
                                 # or a list: [{state.solved: true}, {state.handed_off: true}]
```

`script` and `persona` can't be used together, and neither can `message` and `messages`.

### Message

```yaml
role: user                       # required. user or assistant
content: "What's in this photo?" # required. Text, or a list of parts:
# content:
#   - {type: text, text: "What's in this photo?"}
#   - {type: file, path: photo.png, mime: image/png}
```

### Scorer

```yaml
name: right-queue                # required. Unique in the eval
check: equals                    # a check or a judge, not both
judge: goal-completion           # the name of a judge file
scope: trial                     # trial or run. Only custom checks set it
params: {k: 5}                   # settings for a custom check
pass: {mean: 0.9}                # each or mean (trial), min or max (run)
```

A check is a built-in name (`equals`, `reply_contains`, `reply_not_contains`, `tool_called`, `tool_not_called`, `latency_p95_ms`, `cost_per_trial_usd`), or a custom one: `{command: "..."}` or `{http: "..."}`.

### Judge

```yaml
name: goal-completion            # required
prompt: Did the agent do what the task asked?   # required
choices: {pass: 1, fail: 0}      # each answer and its score
model: null                      # a name the runner understands. null = its default
```

### What the runner sends the agent

```yaml
session_id: 7f3a                 # the same for every turn of one try
messages: [ ... ]                # the conversation so far, or []
data: {}                         # the test case's data
state: {}                        # the state the agent returned last turn
```

### What the agent sends back

```yaml
reply: Your refund is on its way.   # text output, if any
data: {queue: billing}           # structured output
tool_calls:
  - {name: refund, args: {order_id: "1042"}, result: {ok: true}}   # or error
state: {refund_done: true}       # sent back on the next turn
cost_usd: 0.002
```

### The other messages

These follow from the shapes above. They're short enough to list here.

| Who | Gets | Returns |
|---|---|---|
| Custom check, per try | `input`, `output`, `expected` (its own entry), `params`, `session_id` | `score` (0 to 1, or null to skip), `reason`, and optionally `value`, a raw number to log |
| Custom check, per run | `rows` (every try of the run, with its scores) and `params` | `score` and `reason` |
| Judge model | the prompt, input, transcript, output and expected entry | `reason` and `choice` |
| Simulated user | the persona and the transcript | the next user message, or `[done]` |

### What a run writes

`result.json`, one per run:

```yaml
eval: ticket-triage
run_id: 2026-11-23-a1b2
started_at: "2026-11-23T21:30:00Z"
tags: []                         # copied from the eval, with metadata
agent_version: a1b2c3d             # for example a git commit
metadata: {}
models: {agent: "...", judge: "...", user: "..."}
eval_hash: "sha256:..."          # changes when the eval, a judge or an input file changes
status: passed                   # passed, failed, error or not_evaluated
scores:
  right-queue: {value: 0.95, passed: true, failing_cases: [reset-email]}
  fast: {value: 1800, passed: true}                     # a run scorer
latency_ms: {p50: 640, p95: 1800}   # nearest-rank, over every turn
cost_usd: {agent: 0.002, judges: 0.0, user: 0.0}
cases: {total: 20, errored: []}
```

`rows.jsonl`, one line per try:

```yaml
case_id: charged-twice
trial: 1
session_id: 7f3a
tags: [smoke]                     # the test case's
input: { ... }
expected: { ... }
output: {transcript: [ ... ], tool_calls: [ ... ], turns: [ ... ], data: {queue: billing}, state: {}}   # turns: every response, in order
scores: {right-queue: {score: 1, reason: null}}       # plus value, if a check sent one
latency_ms: [640]                # one per turn
cost_usd: 0.002
error: null                      # or {kind: target, message: "..."}
```

## Where things are

- `skills/oes/SPEC.md`: the full format.
- `skills/oes/eval.schema.json`: checks that an eval file is valid.
- `skills/oes/examples/`: a coding agent, invoice extraction, a ticket classifier, a refund agent with tools, and a support chat with a simulated user.
- `skills/oes/SKILL.md`: the instructions a coding agent follows to add evals to a project.
