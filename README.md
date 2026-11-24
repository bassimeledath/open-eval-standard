# Open Eval

A simple file format for testing AI apps.

You write what to send your app and what you expect back. A runner sends it, scores the answers and tells you if the app passed. It works with any app, any language and any model provider.

```yaml
openeval: 1
name: ticket-triage
target: {command: "python -m triage.eval_entry"}
scorers:
  - {name: right-queue, check: equals, pass: {mean: 0.9}}
cases:
  - id: charged-twice
    input:
      data: {subject: "Charged twice", body: "I was billed two times for one order."}
    expected:
      right-queue: {data.queue: billing}
```

## Use it with a coding agent

Install the skill, then ask your agent to "add evals to this app".

```bash
npx skills add bassimeledath/open-eval
```

Or copy `skills/open-eval/` into your agent's skills folder.

## Read more

- [Design](DESIGN.md): what Open Eval is and why, in plain language.
- [Spec](skills/open-eval/SPEC.md): the full format.
- [Examples](skills/open-eval/examples/): a classifier, a tool-using agent and a chat with a simulated user.

## Status

Draft. The format may change before version 1 is final.

MIT license.
