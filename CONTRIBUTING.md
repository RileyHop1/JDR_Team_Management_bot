# Contributing

## Get oriented

Read the [overview](docs/PROJECT_OVERVIEW.md), [architecture](docs/ARCHITECTURE.md), [prerequisites](docs/PREREQUISITES.md), [security policy](SECURITY.md), and [code standards](CODE_STANDARDS.md) before implementation. The foundation supports basic commands, storage, durable meeting reminders, and a read-only Jira morning brief. Transcripts are still outstanding, and the live Discord and Jira checks have not been completed. Follow [development instructions](docs/DEVELOPMENT.md) to set up and verify changes.

Coordinate work using Jira. Each issue should state the user outcome, scope, acceptance criteria, dependencies, and how to verify the result. Link your pull request to its issue. If you do not have board access, ask a maintainer through the team's existing communication channel.

## Development workflow

1. Agree on the issue scope and any missing design decision before introducing infrastructure or an external service.
2. Use a focused branch such as `feat/JDR-123-meeting-reminders` or `fix/JDR-124-duplicate-briefs`; substitute the actual Jira project key. In an isolated cloud task, use the existing checkout; do not create a worktree unless requested.
3. Set up the dependencies using the documented commands once they exist. Keep personal credentials in approved secret storage or a local ignored `.env`, never in Git.
4. Implement a small, coherent change with appropriate tests and update affected documentation.
5. Run the project's formatter, linter, type checker, and relevant tests once configured. Report commands and results honestly; mark checks that could not run and explain why.
6. Open a pull request with the linked issue, behavior change, validation evidence, configuration or migration requirements, and any known limitations.
7. Keep only one implementation PR open at a time for this project. Merge or close it before opening the next.
8. Obtain review from at least one teammate before merging. Resolve correctness, security, and readability concerns; do not bypass failing checks to merge.

## Remaining implementation tasks

- Confirm the decisions listed in the prerequisites and record significant choices as architecture decision records under `docs/decisions/`.
- Maintain the pinned toolchain, dependency manifest, lockfile, and reproducible setup instructions.
- Run Ruff, strict mypy, and pytest before opening a PR. Keep CI green; add relevant tests for each feature.
- Extend the validated configuration model and placeholder-only example as features require.
- Confirm [decision 0002](docs/decisions/0002-meeting-reminders.md) with the team before treating the reminder policy as final.
- Confirm [decision 0003](docs/decisions/0003-jira-morning-brief.md) with the team before treating the Jira query, weekday schedule, or brief recovery policy as final.
- Complete the live Discord foundation smoke check and the meeting-reminder smoke check in [development instructions](docs/DEVELOPMENT.md).
- Prove voice capture and transcription feasibility separately, using synthetic audio and a private test server with consenting participants.

## Review checklist

- Does the change meet the issue's acceptance criteria, including failure cases?
- Is the code readable without tracing unrelated modules or hidden side effects?
- Are external calls, permissions, time zones, duplicate delivery, and cancellation handled?
- Do tests verify behavior rather than merely copy the implementation?
- Are secrets and meeting content absent from logs, fixtures, and commits?
- Are setup, operations, and user-visible behavior documented accurately?

Keep pull requests focused. Explain necessary follow-up work with an issue rather than leaving vague TODOs. Documentation-only changes need relevant link/content checks; they do not require artificial code tests.
