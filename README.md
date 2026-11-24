# Open Eval Standard (OES)

A simple standard for testing AI apps. Plain YAML files, any language, any model provider.

![Open Eval Standard flow](docs/oes-diagram.svg)

```yaml
oes: 1
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
npx skills add bassimeledath/open-eval-standard
```

Or copy `skills/oes/` into your agent's skills folder.

## Read more

- [Design](DESIGN.md): what OES is and why, in plain language.
- [Spec](skills/oes/SPEC.md): the full format.
- [Examples](skills/oes/examples/): a classifier, a tool-using agent and a chat with a simulated user.

## Status

Draft. The standard may change before version 1 is final.

MIT license.
