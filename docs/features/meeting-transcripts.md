# Meeting capture and transcripts

Status: planning document merged; implementation not started. [PR #4](https://github.com/RileyHop1/JDR_Team_Management_bot/pull/4) merged this planning document on 2026-10-15 and included no application code. Retention is approved by the maintainer in [decision 0007](../decisions/0007-meeting-data-retention.md): meeting content is kept for at most 30 days from capture end, in UTC, and then deleted. GitHub issue [#8](https://github.com/RileyHop1/JDR_Team_Management_bot/issues/8) stays open. Voice UDP on the Pi has not been verified ([decision 0006](../decisions/0006-raspberry-pi-hosting.md)). Implementation and validation are outstanding.

Backlog item: [JDR-004](../ISSUES.md#jdr-004-meeting-capture-and-transcripts).

Prove voice capture feasibility, then implement consent controls, bounded recording, transcription, private delivery, and cleanup. The retention period is no longer an open decision. Consent details, late-arrival handling, stop-control details, who may access transcripts or request deletion, duration limits, budget, language, and the transcription provider remain open in the [prerequisites](../PREREQUISITES.md).

## Retention

[Decision 0007](../decisions/0007-meeting-data-retention.md) is the approved policy. The period is a maximum of 30 days. A day is 24 hours. The deadline is capture end plus 30 days, stored in UTC. Capture end is the instant the recording session leaves `recording`. The transcript uses that same deadline. Finishing transcription or delivery does not start a new clock.

The architecture already deletes temporary audio after successful processing or cancellation, which is earlier than 30 days. Failed-job audio may remain until the same deadline. The documents do not set a shorter failed-job period, and they do not require discarding that audio immediately, so the approved bound is the same 30 days.

Transcript text, local transcript files, and Discord messages and attachments the bot posted are deleted by the deadline. A copy a recipient saved is outside the bot. The start notice says so.

Summaries and derived notes are not stored. The [project overview](../PROJECT_OVERVIEW.md) leaves them as a later decision. The documents do not set a period for them. If that later decision stores them, this same 30-day maximum applies.

Session and artifact metadata that is not meeting content stays, and it must not hold audio or transcript text. Logs never contain meeting content.

The future implementation deletes due content with an idempotent purge on the existing scheduler, and it logs identifiers and fixed categories only. Deletion on request uses that same path and does not wait for the deadline. Who may request it is still the open access question.

`pg_dump` copies follow the [production runbook](../operations/runbook.md). Local dumps stay on the existing `find -mtime +7` rotation, which removes them once they are eight days old. Off-Pi copies, including dumps kept for rollback, are deleted once they are 30 days old.

Participants receive a start notice that includes this period. The rest of the consent policy is still open. If notice or authorization cannot be maintained, capture stops.

## Implementation sequence

1. Confirm feature-specific prerequisites and dependencies in the backlog and architecture. The retention decision is [decision 0007](../decisions/0007-meeting-data-retention.md).
2. Implement the smallest complete path with isolated adapters and meaningful tests.
3. Exercise failure cases and complete the backlog acceptance criteria.
4. Document setup and operation; provide controlled integration evidence before marking ready for review.

Follow the [code standards](../../CODE_STANDARDS.md) and [security policy](../../SECURITY.md). This planning document does not satisfy the feature acceptance criteria.
