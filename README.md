# Open Eval

A plain file format for evals of AI apps: what to send the app, what to expect, and how to score it.

Every project ends up inventing its own eval format. Open Eval is one format that works for chatbots, agents, voice apps, classifiers and single model calls, so evals look the same across projects and any runner can run them.

It's written to be handed to a coding agent: point the agent at this repo and ask it to add evals to your app. See [AGENTS.md](AGENTS.md).

```yaml
openeval: 1
name: ticket-triage
kind: single_turn
target: {command: "python -m triage.eval_entry"}
scorers:
  - {name: right_queue, check: equals, pass: {mean: 0.9}}
cases:
  - id: refund-request
    input:
      data: {subject: "Charged twice", body: "I was billed two times for one order."}
    expected:
      equals: {data.queue: billing}
```

## What's here

- [SPEC.md](SPEC.md): the format. Eval files, the target interface, scorers, judges and the result of a run.
- [schema/eval.schema.json](schema/eval.schema.json): JSON Schema for eval files.
- [examples/](examples/): one single-turn eval, one multi-turn eval and a judge.
- [AGENTS.md](AGENTS.md): the order of work for a coding agent adding evals to a project.

## Status

Draft, version 1. The format may change before a first release.

## License

MIT
