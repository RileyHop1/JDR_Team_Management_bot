---
name: Feature or task
about: User outcome, scope, acceptance criteria, dependencies, and how to verify.
title: "JDR-00N: "
---

Do not post secrets, tokens, credential-bearing URLs, real transcripts, or other real meeting content.

<!-- Keep the title in the form `JDR-00N: Title`. Replace `N` and `Title`. -->

## User outcome

<!-- Who can do what when this issue is done. -->

## Scope

<!-- What this issue includes, and what it leaves out. -->

## Acceptance criteria

<!-- Add one checkbox per observable result, including failure cases. -->

- [ ] Describe an observable result that must be true when this issue is done.

## Dependencies

None.

<!-- Replace "None." with the issues, decisions, or services this work needs. -->

## How to verify

For code, record `uv run ruff format --check .`, `uv run ruff check .`, `uv run mypy`, and `uv run pytest -v` against a disposable PostgreSQL database whose name ends in `_test`. For documentation only, record link and content checks instead of code tests.

<!-- Add any issue-specific smoke check or other proof here. -->

## Delivery workflow

Keep only one implementation PR open at a time across this project. Complete and merge or close the current PR before opening the next. Documentation-only changes need link/content checks, not artificial code tests.

Follow the repository code standards, contributing guide, and security policy.
