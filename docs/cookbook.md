# OES cookbook

Short samples for each kind of eval. Each one shows the `scorers` and `cases` of an eval. Every eval also starts with `oes: 1`, a `name` and a `target`, as in the [README](../README.md). The [examples](../skills/oes/examples/) folder has complete evals with their fixtures and checks.

- [Checking the reply](#checking-the-reply)
- [Checking structured output](#checking-structured-output)
- [Checking tool calls](#checking-tool-calls)
- [Checking the final state](#checking-the-final-state)
- [Replaying a conversation](#replaying-a-conversation)
- [Simulating a user](#simulating-a-user)
- [Testing a coding agent](#testing-a-coding-agent)
- [Grading with an LLM judge](#grading-with-an-llm-judge)
- [Writing your own check](#writing-your-own-check)
- [Running several tries](#running-several-tries)
- [Gating on latency and cost](#gating-on-latency-and-cost)
- [Sending files and images](#sending-files-and-images)
- [Keeping cases in a separate file](#keeping-cases-in-a-separate-file)
- [Reading the results](#reading-the-results)

### Checking the reply

Text the reply must, or must never, contain. Matching ignores case.

```yaml
scorers:
  - {name: explains-refunds, check: reply_contains, pass: {mean: 0.9}}
  - {name: no-promises, check: reply_not_contains, pass: {each: 1}}
cases:
  - id: refund-policy
    input: {message: "How do refunds work?"}
    expected:
      explains-refunds: ["refund", "5 business days"]
      no-promises: ["guaranteed", "instantly"]
```

### Checking structured output

For classifiers and extractors that return data instead of text. A path picks a value out of the output.

```yaml
scorers:
  - {name: routed, check: equals, pass: {mean: 0.9}}
cases:
  - id: charged-twice
    input:
      data: {subject: "Charged twice", body: "I was billed two times for one order."}
    expected:
      routed: {data.queue: billing, data.priority: high}
```

### Checking tool calls

Tools the agent must call, with the arguments that matter, and tools it must never call.

```yaml
scorers:
  - {name: looks-up-order, check: tool_called, pass: {each: 1}}
  - {name: no-cancel, check: tool_not_called, pass: {each: 1}}
cases:
  - id: where-is-my-order
    input: {message: "Where is order 1042?"}
    expected:
      looks-up-order: [{name: get_order, args: {order_id: "1042"}}]   # other args are ignored
      no-cancel: [cancel_order, delete_order]
```

### Checking the final state

Start the agent in a known state and check where it ends up, whatever tools it used to get there.

```yaml
scorers:
  - {name: refunded, check: equals, pass: {each: 1}}
cases:
  - id: damaged-item
    input:
      message: "Order 1042 arrived broken. Please refund it."
      state: {orders: {"1042": {status: delivered}}}      # before the first turn
    expected:
      refunded: {state.orders.1042.status: refunded}       # after the last turn
```

### Replaying a conversation

Start partway through a real conversation, then send fixed user lines, one per turn.

```yaml
scorers:
  - {name: asks-for-address, check: reply_contains, pass: {mean: 1}}
cases:
  - id: return-with-new-address
    input:
      messages:                                   # the conversation so far
        - {role: user, content: "I want to return my headphones."}
        - {role: assistant, content: "Sure. What's the order number?"}
      script:                                     # the next user lines
        - "It's 1042."
        - "Can you send the label somewhere else?"
    expected:
      asks-for-address: ["address"]
```

### Simulating a user

An LLM plays the user from a short description, so the conversation can react to what the agent says.

```yaml
scorers:
  - {name: solved, judge: goal-completion, pass: {mean: 0.8}}
cases:
  - id: wifi-after-update
    input:
      persona: >
        A calm adult whose laptop stopped joining wifi after an update.
        Other devices work; say so only if asked. Stop when it works.
      max_turns: 20
      stop_when: [{state.solved: true}, {state.handed_off: true}]   # either ends it
    expected:
      solved: ["Asks what changed before suggesting fixes."]
```

### Testing a coding agent

Give the agent a repo and a task, follow up, then run the repo's tests. Each try gets its own copy of the repo.

```yaml
scorers:
  - name: tests-pass
    check: {command: "python evals/checks/run_tests.py"}   # reads output.data.repo
    pass: {mean: 0.8}
cases:
  - id: add-due-date
    input:
      data:
        repo: {type: file, path: fixtures/todo-app}       # a folder
        task: Add an optional due date to each todo item.
      script:
        - {data: {task: Now add tests for the due date.}}  # merged into data
    expected:
      tests-pass: {min_passing: 4}
```

### Grading with an LLM judge

For what code can't check. A judge is a small file, answers pass or fail, and gets each case's criteria.

```yaml
# evals/judges/faithful.judge.yaml
name: faithful
prompt: |
  Does the summary state only facts found in the document?
  Pass if every claim is supported. Fail if any claim is not.
```

```yaml
scorers:
  - {name: faithful-summary, judge: faithful, pass: {mean: 0.9}}
cases:
  - id: q3-report
    input:
      data: {document: {type: file, path: fixtures/q3-report.pdf}}
    expected:
      faithful-summary: ["Mentions the revenue drop.", "Doesn't invent figures."]
```

The runner reaches models through `OES_LLM_COMMAND`, a small script you write for whichever provider you use.

### Writing your own check

A check is any command or URL, in any language, that reads JSON and prints a score from 0 to 1.

```yaml
scorers:
  - name: total
    check: {command: "node evals/checks/close-enough.js"}
    params: {path: data.total, tolerance: 0.01}
    pass: {each: 1}
cases:
  - id: acme-invoice
    input:
      data: {invoice: {type: file, path: fixtures/acme.pdf, mime: application/pdf}}
    expected:
      total: 1249.50
```

```text
in:   {"input": ..., "output": ..., "expected": 1249.5, "params": {...}, "session_id": "..."}
out:  {"score": 1, "reason": "off by 0.004", "value": 0.004}
```

### Running several tries

Agents don't answer the same way twice. Run each case a few times. `each` means every try must pass, and `mean` sets a pass rate. A whole-run check can report pass@k.

```yaml
trial_count: 5
scorers:
  - {name: never-leaks, check: reply_not_contains, pass: {each: 1}}   # all 5 tries
  - {name: helpful, judge: helpful, pass: {mean: 0.8}}                # 4 out of 5
  - name: helpful-at-5
    check: {command: "python evals/checks/pass_at_k.py"}
    scope: run                                                         # once, over every try
    params: {scorer: helpful, mode: any}
    pass: {min: 0.9}
cases:
  - id: account-question
    input: {message: "What's on my account?"}
    expected:
      never-leaks: ["password", "card number"]
```

### Gating on latency and cost

Measured over the whole run. An agent that reports no cost can't pass a cost gate.

```yaml
scorers:
  - {name: fast, check: latency_p95_ms, pass: {max: 2000}}
  - {name: cheap, check: cost_per_trial_usd, pass: {max: 0.05}}
cases:
  - id: greeting
    input: {message: "Hi"}
```

### Sending files and images

A file can go in `data` or in a message. The agent gets the path of its own copy.

```yaml
scorers:
  - {name: spots-damage, check: reply_contains, pass: {mean: 0.9}}
cases:
  - id: cracked-screen
    input:
      message:
        - {type: text, text: "What's damaged in this photo?"}
        - {type: file, path: fixtures/cracked.jpg, mime: image/jpeg}
    expected:
      spots-damage: ["screen"]
```

### Keeping cases in a separate file

For many cases, or cases exported from production logs. One JSON test case per line.

```yaml
scorers:
  - {name: routed, check: equals, pass: {mean: 0.95}}
cases: {file: cases.jsonl}
```

### Reading the results

Each run writes `.oes/runs/<run_id>/`: `result.json` with the scores and status, and `rows.jsonl` with every try's input, output and scores.

```json
{
  "eval": "refund-agent",
  "status": "failed",
  "scores": {
    "refunds": {"value": 0.5, "passed": false, "scored": 2, "skipped": 0, "failing_cases": ["wrong-order"]}
  },
  "latency_ms": {"p50": 41, "p95": 44},
  "cost_usd": {"agent": null, "judges": null, "user": null},
  "eval_hash": "sha256:3f1c..."
}
```
