# Contributing

## Get oriented

Read the [overview](docs/PROJECT_OVERVIEW.md), [architecture](docs/ARCHITECTURE.md), [prerequisites](docs/PREREQUISITES.md), [security policy](SECURITY.md), and [code standards](CODE_STANDARDS.md) before implementation. Merged behavior covers basic commands, storage, durable meeting reminders, a read-only Jira morning brief, operator-managed guild settings, and secret-safe startup failure categories. Pull requests and CI results are in [implementation issues](docs/ISSUES.md). Transcripts ([JDR-004](docs/ISSUES.md#jdr-004-meeting-capture-and-transcripts), issue [#8](https://github.com/RileyHop1/JDR_Team_Management_bot/issues/8)) and the hosting runbook ([JDR-007](docs/ISSUES.md#jdr-007-hosting-decision-and-production-deployment-runbook), issue [#12](https://github.com/RileyHop1/JDR_Team_Management_bot/issues/12)) are still outstanding. Issue and pull request templates for [JDR-009](docs/ISSUES.md#jdr-009-github-issue-and-pull-request-templates) are described below. The live Discord and Jira checks have not been completed. Decisions [0002](docs/decisions/0002-meeting-reminders.md), [0003](docs/decisions/0003-jira-morning-brief.md), and [0004](docs/decisions/0004-guild-configuration.md) are provisional and need team confirmation. Decisions [0001](docs/decisions/0001-development-foundation.md) and [0005](docs/decisions/0005-startup-failures.md) are accepted for the merged implementation. Follow [development instructions](docs/DEVELOPMENT.md) to set up and verify changes.

## Where work is tracked

Track work in GitHub issues, using the backlog in [implementation issues](docs/ISSUES.md). Each `JDR-00N` label is a planning ID for a GitHub issue. It is not a Jira ticket key. Jira is the external tracker the morning brief reads. It is not the board for this repository.

Put the planning ID in the branch name, for example `feat/JDR-004-meeting-transcripts` or `fix/JDR-002-duplicate-reminders`. Link the pull request to the GitHub issue number (`#8` for JDR-004). Do not put a Jira key in the branch name. An isolated cloud task may be required to use a `cursor/<description>-<suffix>` branch. When that happens, put the `JDR-00N` ID in the pull request title or body.

Open a GitHub issue from the [feature or task template](.github/ISSUE_TEMPLATE/feature_task.md). Title it `JDR-00N: Title`. The template asks for the user outcome, scope, acceptance criteria, dependencies, how to verify the result, and the delivery workflow. Open a pull request from the [pull request template](.github/pull_request_template.md). Do not post secrets or real meeting content in either. If you cannot open a GitHub issue, ask a maintainer through the team's existing communication channel.

## Development workflow

1. Agree on the issue scope and any missing design decision before introducing infrastructure or an external service.
2. Use a focused branch named with the planning ID, as above. In an isolated cloud task, use the existing checkout; do not create a worktree unless requested.
3. Set up dependencies with the commands in [development instructions](docs/DEVELOPMENT.md). Keep personal credentials in approved secret storage or a local ignored `.env`, never in Git.
4. Implement a small, coherent change with appropriate tests and update affected documentation.
5. Run the formatter, linter, type checker, and relevant tests listed in the [README](README.md). Report commands and results honestly; mark checks that could not run and explain why.
6. Open a pull request from the [pull request template](.github/pull_request_template.md). Include the linked issue, behavior change, validation evidence, configuration or migration requirements, and any known limitations.
7. Keep only one implementation PR open at a time for this project. Merge or close it before opening the next.
8. Obtain review from at least one teammate before merging. Resolve correctness, security, and readability concerns; do not bypass failing checks to merge.

## Remaining implementation tasks

- Confirm [decision 0002](docs/decisions/0002-meeting-reminders.md), [decision 0003](docs/decisions/0003-jira-morning-brief.md), and [decision 0004](docs/decisions/0004-guild-configuration.md) with the team before treating those policies as final. Record any replacement in `docs/decisions/`.
- Complete the live Discord foundation smoke check for issue [#5](https://github.com/RileyHop1/JDR_Team_Management_bot/issues/5), the meeting-reminder smoke check for issue [#6](https://github.com/RileyHop1/JDR_Team_Management_bot/issues/6), and the Jira morning-brief smoke check for issue [#7](https://github.com/RileyHop1/JDR_Team_Management_bot/issues/7). Also complete the guild-configuration smoke check. Those commands are merged and issue [#11](https://github.com/RileyHop1/JDR_Team_Management_bot/issues/11) is closed; the live `/config` check is still outstanding. Steps are in [development instructions](docs/DEVELOPMENT.md).
- Implement meeting capture and transcripts ([JDR-004](docs/features/meeting-transcripts.md), issue [#8](https://github.com/RileyHop1/JDR_Team_Management_bot/issues/8)). [PR #4](https://github.com/RileyHop1/JDR_Team_Management_bot/pull/4) merged the planning document only. Prove voice capture and transcription feasibility first, using synthetic audio and a private test server with consenting participants.
- Write the hosting decision and production runbook (issue [#12](https://github.com/RileyHop1/JDR_Team_Management_bot/issues/12)).
- Maintain the pinned toolchain, dependency manifest, lockfile, and reproducible setup instructions.
- Run Ruff, strict mypy, and pytest before opening a PR. Keep CI green; add relevant tests for each feature.
- Extend the validated configuration model and placeholder-only example as features require.

## Review checklist

- Does the change meet the issue's acceptance criteria, including failure cases?
- Is the code readable without tracing unrelated modules or hidden side effects?
- Are external calls, permissions, time zones, duplicate delivery, and cancellation handled?
- Do tests verify behavior rather than merely copy the implementation?
- Are secrets and meeting content absent from logs, fixtures, and commits?
- Are setup, operations, and user-visible behavior documented accurately?

Keep pull requests focused. Explain necessary follow-up work with an issue rather than leaving vague TODOs. Documentation-only changes need relevant link/content checks; they do not require artificial code tests.
