# Contributing

OES stays small on purpose. Before proposing a change, check whether what you need already works with `metadata`, a custom check or a judge. Most things do.

**To propose a change to the standard,** open an issue first, with:
- the use case, and a real eval that can't be written today
- the smallest change that would allow it

If it can be covered by a custom check or a judge, it usually goes in a cookbook page instead.

**When a change is agreed,** one pull request updates all of these together:
- `skills/oes/SPEC.md`
- the schemas
- the examples
- `conformance/`
- both reference runners
- `CHANGELOG.md`

Every example must validate, and both runners must pass the conformance suite.

**Versioning.** A change that breaks existing evals raises the `oes` version. A new optional field, or a new built-in check, does not.

**No vendor names** in the spec, schemas, examples or runners. Model access goes through `OES_LLM_COMMAND`.
