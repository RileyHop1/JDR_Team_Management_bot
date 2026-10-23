# Meeting capture and transcripts

Status: planning document merged; implementation not started. [PR #4](https://github.com/RileyHop1/JDR_Team_Management_bot/pull/4) merged this planning document on 2026-10-15 and included no application code. [PR #22](https://github.com/RileyHop1/JDR_Team_Management_bot/pull/22) records the retention decision. Retention is approved by the maintainer in [decision 0007](../decisions/0007-meeting-data-retention.md): meeting content is deleted within 30 days of capture end, in UTC. Live copies are purged at capture end plus 23 days, and every dump file is deleted before it is 7 days old. GitHub issue [#8](https://github.com/RileyHop1/JDR_Team_Management_bot/issues/8) stays open. Voice UDP on the Pi has not been verified ([decision 0006](../decisions/0006-raspberry-pi-hosting.md)). Implementation and validation are outstanding.

Backlog item: [JDR-004](../ISSUES.md#jdr-004-meeting-capture-and-transcripts).

Prove voice capture feasibility, then implement consent controls, bounded recording, transcription, private delivery, and cleanup. The retention period is no longer an open decision. Consent details, late-arrival handling, stop-control details, who may access transcripts or request deletion, duration limits, budget, language, and the transcription provider remain open in the [prerequisites](../PREREQUISITES.md).

## Retention

[Decision 0007](../decisions/0007-meeting-data-retention.md) is the approved policy. No copy of meeting content remains more than 30 days after capture end. A day is 24 hours. The live deadline is capture end plus 23 days, stored in UTC. Capture end is the instant the recording session leaves `recording`. If that timestamp is missing, the deadline is the session's immutable creation time plus 23 days, which is always at or before capture end. The transcript uses that same live deadline. Finishing transcription or delivery does not start a new clock. Every `pg_dump` file is deleted before it is 7 days old, which is why the live purge is at 23 days rather than 30: a dump taken just before the purge expires by day 30.

The architecture already deletes temporary audio after successful processing or cancellation, which is earlier than 23 days. Failed-job audio may remain until the same live deadline. The documents do not set a shorter failed-job period, and they do not require discarding that audio immediately.

Transcript text, local transcript files, database transcript text, and Discord messages and attachments the bot posted are deleted by the live deadline. A missing Discord receipt does not keep the database copy. The row is marked purged with a fixed category after bounded retries. A copy a recipient saved is outside the bot. The start notice says content is deleted within 30 days of capture end.

Summaries and derived notes are not stored. The [project overview](../PROJECT_OVERVIEW.md) leaves them as a later decision. The documents do not set a period for them. If that later decision stores them, this same 30-day total applies.

Session and artifact metadata that is not meeting content stays. It is limited to non-personal ids, timestamps, fixed tokens, an opaque provider job id, and a fixed failure category. It must not hold audio, transcript text, a Discord user id, a credential, or error text. Logs never contain meeting content or a Discord user id. Only `meeting_content_purge_failed` carries a category.

The future implementation deletes due content with an idempotent purge on the existing scheduler. Deletion on request uses that same path and does not wait for the deadline. Who may request it is still the open access question.

`pg_dump` copies follow the [production runbook](../operations/runbook.md). Rotation is its own timer and does not run inside the `pg_dump` script. Local dumps, off-Pi copies, and rollback dumps are deleted once the filename stamp is 6 days old, which is inside the 7-day cap after the hourly timer's delay.

Participants receive a start notice that says meeting content is deleted within 30 days of capture end. The rest of the consent policy is still open. If notice or authorization cannot be maintained, capture stops.

## Implementation sequence

1. Confirm feature-specific prerequisites and dependencies in the backlog and architecture. The retention decision is [decision 0007](../decisions/0007-meeting-data-retention.md).
2. Implement the smallest complete path with isolated adapters and meaningful tests.
3. Exercise failure cases and complete the backlog acceptance criteria.
4. Document setup and operation; provide controlled integration evidence before marking ready for review.

Follow the [code standards](../../CODE_STANDARDS.md) and [security policy](../../SECURITY.md). This planning document does not satisfy the feature acceptance criteria.
