# Changelog

## 1.0.0-rc.1 (unreleased)

The first release candidate of OES version 1.

- The spec, with the eval file, target protocol, scorers, judges, results and the runner command line.
- JSON Schemas for eval files, judge files and results (`skills/oes/*.schema.json`).
- The `oes` agent skill, with five examples: a coding agent, invoice extraction, a ticket classifier, a refund agent and a support chat.
- Reference runners in Python and TypeScript.
- A conformance suite that every runner must pass: 82 checks, passed by both reference runners.

Drafts 1 to 5 led up to this release. The main changes, from the reviews and stress tests:

- There are two kinds of test case, single-turn and multi-turn, and the input decides which. Multi-turn is scripted or simulated.
- Runner behavior is pinned down so independent runners agree: YAML 1.2, the command and HTTP protocol, retries, file copies, path and equality rules, unknown cost, an exact eval hash, and the runner recorded in each result.
