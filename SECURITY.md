# Security and meeting data

## Credentials

Never commit tokens, database passwords, credential-bearing URLs, or real recordings. Use an approved secret store or ignored local configuration. Validate required settings without printing their values. Redact credentials from errors and logs. Restrict Jira credentials to read-only access and scope Discord permissions to the configured server/channels. Guild configuration rows store channels, an IANA time zone, and a brief time only. Do not put Jira tokens, account email, or JQL in those rows.

If a credential is exposed, revoke or rotate it immediately, notify the maintainers privately, and remove it from affected systems. Deleting a Git file alone does not remove a credential from history or invalidate it.

## Recording and transcripts

Recording must be visible and explicitly authorized under the team's agreed policy and applicable institutional requirements. Provide a clear start notice and stop control; handle late arrivals and withdrawals. The start notice includes the retention period in [decision 0007](docs/decisions/0007-meeting-data-retention.md). Do not record automatically merely because the bot can join a channel.

Restrict recordings and transcripts to approved destinations. Confirm channel access before posting; never fall back to a public channel on a permission failure. The retention and deletion policy is approved in [decision 0007](docs/decisions/0007-meeting-data-retention.md). No copy of meeting content exists more than 30 days after capture end, in UTC. Live content (temporary audio, transcripts, Discord attachments the bot posted, and provider copies) is purged at capture end plus 23 days. Every `pg_dump` file, including an off-Pi copy and a rollback dump, is deleted before it is 7 days old, so a dump taken just before that live purge is gone by day 30. The start notice says meeting content is deleted within 30 days of capture end. Temporary audio is deleted earlier after successful processing or cancellation, which the [architecture](docs/ARCHITECTURE.md) already requires. Deletion on request uses that same deletion path and does not wait for the deadline. A posted transcript may be copied by recipients; communicate that limitation. Logs never contain meeting content or a Discord user id. Recording stays off until the remaining capture prerequisites are decided and the feature is implemented. Issue [#8](https://github.com/RileyHop1/JDR_Team_Management_bot/issues/8) stays open.

Treat Jira descriptions, Discord input, and transcript text as untrusted content. Escape or suppress mentions and avoid executing embedded instructions. Future summarization must not grant transcript or issue text authority to run commands or change configuration.

## Reporting a vulnerability

Report a vulnerability privately to Daniil at daniil.nahl@protonmail.com. Do not post secrets, real transcripts, or exploitable details in public issues.
