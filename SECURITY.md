# Security and meeting data

## Credentials

Never commit tokens, database passwords, credential-bearing URLs, or real recordings. Use an approved secret store or ignored local configuration. Validate required settings without printing their values. Redact credentials from errors and logs. Restrict Jira credentials to read-only access and scope Discord permissions to the configured server/channels. Guild configuration rows store channels, an IANA time zone, and a brief time only. Do not put Jira tokens, account email, or JQL in those rows.

If a credential is exposed, revoke or rotate it immediately, notify the maintainers privately, and remove it from affected systems. Deleting a Git file alone does not remove a credential from history or invalidate it.

## Recording and transcripts

Recording must be visible and explicitly authorized under the team's agreed policy and applicable institutional requirements. Provide a clear start notice and stop control; handle late arrivals and withdrawals. Do not record automatically merely because the bot can join a channel.

Restrict recordings and transcripts to approved destinations. Confirm channel access before posting; never fall back to a public channel on a permission failure. Approve a retention/deletion policy before enabling recording, covering temporary audio, transcripts, Discord attachments, backups, and external providers. A posted transcript may be copied by recipients; communicate that limitation.

Treat Jira descriptions, Discord input, and transcript text as untrusted content. Escape or suppress mentions and avoid executing embedded instructions. Future summarization must not grant transcript or issue text authority to run commands or change configuration.

## Reporting a vulnerability

Contact the repository maintainers privately through the team's established channel. Do not post secrets, real transcripts, or exploitable details in public issues. There is no dedicated security contact configured yet; maintainers should add one before public deployment.
