# Open Eval Standard (OES)

A dead simple standard for testing AI agents. Each test says what to give your agent, what you expect it to do, and how to tell whether it passed. Plain YAML files, any language, any model provider.

<p align="center">
  <img src="docs/on-my-eval.jpg" alt="An engineer reports a 94% score. A colleague asks to run the same evals. They need the script, the spreadsheet, a Slack thread from March, and Dave, who is chained to his laptop." width="560">
</p>

A score like 94% is easier to interpret when you can see the tests behind it. With OES, those tests live in your repo as YAML files that teammates can read, review, and run again when the prompt or model changes.

Every test case is one of two kinds:

| Kind | What it does |
|---|---|
| **Single-turn** | Calls the agent once. Ask a question, label a ticket, extract a PDF. |
| **Multi-turn** | Calls it several times in a row, with fixed inputs or an AI playing the user. A coding task with follow-ups, a support chat. |

![Open Eval Standard flow](docs/oes-diagram.svg)

```yaml
oes: 1
name: capitals
target: {http: "http://localhost:8000/eval"}   # where to reach your agent
scorers:
  - {name: knows-capital, check: reply_contains, pass: {mean: 0.9}}   # any name you like
cases:
  - id: france
    input:
      message: What is the capital of France?
    expected:
      knows-capital: [Paris]     # under the scorer's name: the reply must mention Paris
```

## Use it with a coding agent

Install the skill, then ask your coding agent to "add OES evals to this project".

```bash
npx skills add bassimeledath/open-eval-standard
```

Or copy `skills/oes/` into your agent's skills folder.

## I use Braintrust/LangSmith/Langfuse/Arize/&lt;any-of-the-other-million-ones&gt;, why do I even need this?

Keep using them. They're great at storing runs, showing traces and comparing results. OES is about the evals themselves. Today your test cases and grading rules live in one tool's SDK or UI, so they're hard to share across teams and you lose them when you switch tools. With OES they're plain files in your repo that any runner can run, your coding agent can write, and your teammates can review in a pull request. Each run writes plain JSON rows, so you can send the results to whichever platform you already use.

## Read more

- [Design](DESIGN.md): what OES is and why, in plain language.
- [Spec](skills/oes/SPEC.md): the full format.
- [Examples](skills/oes/examples/): a coding agent, invoice extraction, a ticket classifier, a refund agent with tools, and a support chat with a simulated user.

## License

MIT
