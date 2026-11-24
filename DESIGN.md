# Open Eval design

## What it is

Open Eval is a simple way to write tests for AI apps. These tests are called evals.

An eval is a file. It lists questions or situations to give your app, says what a good answer looks like, and says how good the app has to be to pass. A program called a runner reads the file, tries each one on your app, scores the answers and writes down what happened.

## Why

Every project that uses AI ends up inventing its own way to test it. The tests live in one-off scripts, each in a different shape, and they're hard to reuse or compare. Each new project starts from zero.

Open Eval is one shape that fits most AI apps: chatbots, agents that use tools, classifiers and single model calls. Write evals the same way in every project, and any runner, or any coding agent, can work with them.

## The pieces

There are five.

1. **The eval file.** One YAML file per eval, kept in the app's own repository.
2. **Test cases.** Each one is something to send the app, plus what we expect.
3. **The target.** How the runner reaches the app: a command it runs, or a URL it calls. The app sends back its reply, and anything else useful, like which tools it used.
4. **Scorers.** How each answer is graded, from 0 to 1. A **check** is a bit of code ("did it pick the billing queue?"). A **judge** asks an AI model ("did it solve the problem?"). Each scorer can have a **pass rule**, such as "90% of answers must be right".
5. **The result.** What the run produced: the scores, whether it passed, how long it took and what it cost. It's saved as plain files in the project.

## How a run works

1. The runner reads the eval file.
2. For each test case, it sends the input to the app and collects the reply. For a conversation, it keeps going turn by turn.
3. It scores every reply with every scorer.
4. It checks the pass rules and writes the result.

## Three kinds of test case

Every test case uses the same fields. What you put in the input decides how it runs.

- **One turn.** Send one message, or a piece of data, and score the reply. This covers most apps, including an agent that does a lot of work inside one request.
- **Scripted.** Send a fixed list of user messages, one after another. Good for replaying a real conversation.
- **Simulated.** An AI model plays the user from a short description ("a calm adult whose laptop won't connect to wifi"). Good when the user's replies need to react to what the app says. It's the least predictable kind, so run these a few times each.

## Design choices

**Plain files.** Evals are YAML, and results are JSON. You can read them, review them in a pull request and keep them in git. No service is needed.

**Works with anything.** The format never names a model provider, a language or a framework. The runner decides which models play judges and users. The app only needs a command or a URL that takes JSON and returns JSON.

**The app doesn't change.** You add a small entry point. The app itself stays as it is.

**Code before AI.** Use a check when code can tell if an answer is right. Use a judge only when it can't. Checks are fast, free and never change their minds.

**Each scorer reads its own expectations.** In a test case, `expected` has one entry per scorer, under the scorer's name. So one eval can have several scorers of the same kind, each with its own rule.

**One run stands alone.** A result describes one run of one version of the app. To compare two versions, compare their results, but only when the eval and the judges are the same in both.

**Not evaluated is not a pass.** If something didn't run, the result says so. Nothing is allowed to turn that into a pass.

**An eval must be able to fail.** Before trusting an eval, run it once against an app that says nothing. If it still passes, it isn't testing anything.

## Left out on purpose

- **A runner.** The format comes first. A coding agent can write a small runner for any project from the spec, and a shared one can come later.
- **Voice-specific fields** like interruptions or background noise. Voice apps that work turn by turn fit already. The rest can live in `metadata` until there's a clear pattern.
- **A list of every eval across projects**, and **a record of whether a change was adopted.** Useful for teams, but not needed to test one app.
- **Side-by-side judging**, where a judge sees two versions' answers at once. It needs care to be fair, and it can be added later.

## How it grows

The core stays small. New uses go in docs and cookbooks first, built from what's already there:

- **Custom checks**, in any language. A check is a command or URL that gets JSON and returns a score.
- **Judges** for any quality that's easier to describe than to code.
- **Whole-run scores**, like accuracy across all test cases or the slowest 5% of replies.
- **`metadata`, `data` and `state`**, open fields for anything specific to one app.

Cookbook ideas: search-based apps (RAG), structured output, tool-using agents, voice, images and documents, and turning real failures into test cases.

A new field joins the format only when a real use case can't be covered by these.

## Where things are

- `skills/open-eval/SPEC.md`: the full format.
- `skills/open-eval/eval.schema.json`: checks that an eval file is valid.
- `skills/open-eval/examples/`: a classifier, a tool-using agent and a simulated conversation.
- `skills/open-eval/SKILL.md`: the instructions a coding agent follows to add evals to a project.
