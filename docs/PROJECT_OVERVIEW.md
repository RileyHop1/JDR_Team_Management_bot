# Project overview

## Purpose

Reduce coordination overhead for a senior computer engineering team by bringing meeting reminders, meeting records, and Jira work summaries into Discord.

## Initial scope

| Capability | Planned behavior | Acceptance criteria |
| --- | --- | --- |
| Meeting setup | Authorized members configure a meeting time, IANA time zone, destination text channel, voice channel, and reminder offsets. | Invalid schedules and inaccessible channels are rejected with useful messages. An authorized member can view, update, and cancel the meeting. |
| Reminders | Deliver notices at configured offsets before each meeting. | A fake-clock test verifies timing, cancellation, restart recovery, and duplicate handling. Delivery failures are visible to maintainers. |
| Meeting transcripts | Join a supported voice meeting following explicit authorization, capture permitted audio, transcribe it, and publish to the configured meetings channel. | The bot announces recording, offers a stop control, handles disconnects, and delivers a synthetic-audio transcript. Long transcripts use a private channel attachment with the same access restrictions. |
| Morning brief | At a configured local time, summarize Jira issues in the team's selected in-progress statuses. | Include issue key, title, assignee or “unassigned,” status, and issue URL; handle pagination, no matching work, and provider failure distinctly. |

The brief initially reflects current Jira state. Historical changes, blockers, or sprint progress require explicit query rules and additional data; the bot must not invent them. Transcript summaries and action-item extraction are optional later features, separate from faithful transcription.

## Proposed milestones

1. **Foundation:** confirm scope and providers; add tooling, CI, configuration, commands, persistence, and authorization.
2. **Reminders:** durable scheduled notifications are implemented offline. A private-server demonstration and team confirmation of [decision 0002](decisions/0002-meeting-reminders.md) are still required.
3. **Jira brief:** implement a read-only adapter and scheduled output with fixture-based tests.
4. **Transcription feasibility:** prove supported voice capture, audio processing, consent controls, and provider compatibility.
5. **Meeting records:** integrate transcription, delivery, deletion, failure recovery, and operational documentation.

Develop reminders and Jira independently of the voice feasibility spike. Do not promise the recording feature until that spike passes.

## Out of scope initially

Autonomous Jira edits, attendance grading, covert recording, general-purpose chat, and joining third-party conferencing platforms. Calendar synchronization, recurring meeting rules, and AI-generated summaries require separate decisions.

## Definition of done

A feature meets its acceptance criteria, passes the configured quality checks, has teammate review, documents configuration and operation, and has demonstrated failure handling. Integration features also need a controlled end-to-end check with test resources. Missing credentials or a mocked provider do not count as a successful live integration.
