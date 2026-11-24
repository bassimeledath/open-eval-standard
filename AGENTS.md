# AGENTS.md

To add evals to a project, follow `skills/oes/SKILL.md`.

To change the standard itself:
- `skills/oes/SPEC.md` is the source of truth. Update `eval.schema.json` and `examples/` in the same change, and check every example against the schema.
- Keep it small. Add a field only when a real use case can't be covered with `metadata`, a custom check or a judge. Cover new use cases in `docs/` first.
- Keep it provider-agnostic. No model vendor names in the spec, the schema or the examples.
