<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/logo-dark.svg">
    <img src="docs/logo.svg" alt="OES, Open Eval Standard" width="260">
  </picture>
</p>

<p align="center"><b>Write agent evals in YAML. Run them against any agent from any provider in any language.</b></p>

OES evals are YAML files in your repo. A runner sends each test to your agent through a command or a URL, checks what comes back (the reply, the tools it called, its final state) and tells you whether it passed. Your agent doesn't change, and it can be written in any language and use any model provider.

![An eval file in your repo goes to oes run, which calls your agent through a command or URL, checks the tool calls, final state and reply, and passes or fails.](docs/outside-in.svg)

```yaml
# evals/refund-agent.eval.yaml
oes: 1
name: refund-agent
target: {command: "python agent.py"}          # or {http: "http://localhost:8000/eval"}
scorers:                                       # the names are your own choice
  - {name: refunds, check: tool_called, pass: {each: 1}}
  - {name: order-refunded, check: equals, pass: {each: 1}}
  - {name: never-deletes, check: tool_not_called, pass: {each: 1}}
  - {name: says-timeline, check: reply_contains, pass: {mean: 0.9}}
cases:
  - id: damaged-item
    input:
      message: "My order 1042 arrived broken. Can I get my money back?"
      state: {orders: {"1042": {total: 20, status: delivered}}}
    expected:                                  # what each scorer expects
      refunds: [{name: refund, args: {order_id: "1042", amount: 20}}]
      order-refunded: {state.orders.1042.status: refunded}
      never-deletes: [delete_order]
      says-timeline: ["5 business days"]
```

With a second case, `wrong-order`, that the agent gets wrong:

```console
$ oes run evals/refund-agent.eval.yaml
refund-agent: failed
  refunds: value=0.5 passed=False failing=['wrong-order']
  order-refunded: value=0.5 passed=False failing=['wrong-order']
  never-deletes: value=0.5 passed=False failing=['wrong-order']
  says-timeline: value=0.5 passed=False failing=['wrong-order']
```

## Why OES

- **Your agent stays as it is.** It's tested from the outside, through a command or a URL, so it can be Python, TypeScript, Go, a CLI or a deployed service. There's no SDK to import.
- **Checks you can trust.** Code checks come first: the right tool with the right arguments, the final state, an exact value. LLM judges are there for what code can't check, and they answer pass or fail. A test that couldn't run is reported as not evaluated, never as a pass.
- **Your coding agent can write them.** The format is small, has a schema and comes with a skill. Ask your coding agent to "add OES evals to this project".
- **Plain files, not a platform.** Any conforming runner can run them. The Python and TypeScript runners pass the same [conformance suite](conformance/), and results are plain JSON you can send wherever you like.

## Single-turn and multi-turn

| Kind | What it does |
|---|---|
| **Single-turn** | Calls the agent once. Answer a question, label a ticket, extract a PDF. |
| **Multi-turn** | Calls it several times in a row, with fixed inputs or an AI playing the user. A coding task with follow-ups, a support chat. |

## Run it

```bash
uvx --from "git+https://github.com/bassimeledath/open-eval-standard#subdirectory=runners/python" oes run evals/refund-agent.eval.yaml
```

It exits 0 when the eval passes and 1 when it doesn't, so it drops straight into CI. Results go to `.oes/runs/`. There's also a [TypeScript runner](runners/typescript/). Evals with an LLM judge or a simulated user need `OES_LLM_COMMAND`, a small script that calls whichever model you use ([example](runners/python/README.md#the-llm-command)).

## Use it with a coding agent

Install the skill, then ask your coding agent to "add OES evals to this project".

```bash
npx skills add bassimeledath/open-eval-standard
```

Or copy `skills/oes/` into your agent's skills folder.

## How it fits with pytest, DeepEval and eval platforms

They do different jobs, and work well together.

- **pytest or DeepEval** are for tests in your code: call a Python function and check what it returns.
- **OES** tests the whole agent from the outside, the way Hurl tests an HTTP API: the running agent, in any language, with tests that live as plain files.
- **Braintrust, LangSmith, Langfuse and the rest** are for storing runs and looking at traces. Keep using them. With OES your eval definitions stay in your repo, so they don't change when you switch platforms.

## Read more

- [Design](DESIGN.md): what OES is and why, in plain language.
- [Spec](skills/oes/SPEC.md): the full format.
- [Examples](skills/oes/examples/): a coding agent, invoice extraction, a ticket classifier, a refund agent with tools, and a support chat with a simulated user.

## License

MIT
