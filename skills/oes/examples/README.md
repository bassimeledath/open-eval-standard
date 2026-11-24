# Examples

Five evals, one of each common shape. Each file is laid out the way your project's `evals/` folder would be, so copy them into `evals/` to use them:

- `coding-agent.eval.yaml`: a coding agent changes `fixtures/todo-app` over two turns, and `checks/run_tests.py` runs its tests. Shows pass@k with `checks/pass_at_k.py`.
- `invoice-extraction.eval.yaml`: an extractor reads `fixtures/acme-march.pdf`, and `checks/close_enough.py` checks the total within a cent.
- `ticket-triage.eval.yaml`: a classifier, with built-in checks only.
- `refund-agent.eval.yaml`: an agent that uses tools, checked by its tool calls and final state.
- `wifi-help.eval.yaml`: a support chat with a simulated user and an LLM judge (`judges/goal-completion.judge.yaml`).

Every file passes `oes validate`. To run one, point its `target` at your agent.
