# 0006: Raspberry Pi hosting

Status: provisional. Recorded in [PR #21](https://github.com/RileyHop1/JDR_Team_Management_bot/pull/21). The maintainer (Daniil) chose a self-hosted Raspberry Pi as the continuous host. This record does not accept that choice as proof of a Discord gateway session or of voice UDP on that Pi. Neither check has been run here: this environment cannot reach the Pi. GitHub issue [#12](https://github.com/RileyHop1/JDR_Team_Management_bot/issues/12) stays open until the [verification procedure](#verification-on-the-pi) is run on the Pi and the result is recorded. That is the same rule as [decision 0002](0002-meeting-reminders.md), [decision 0003](0003-jira-morning-brief.md), and [decision 0004](0004-guild-configuration.md): a live check that has not been run keeps the decision provisional and the issue open. Operation of the Pi is the [production runbook](../operations/runbook.md).

## Choice

The bot runs as one Linux process on a Raspberry Pi the team owns. PostgreSQL 16 runs on the same Pi. The process dials out to Discord and, when the morning brief is enabled, to Jira Cloud. No inbound port is required for Discord or for PostgreSQL.

[Decision 0001](0001-development-foundation.md) already limits deployment to a single guild and a single process on Linux. This decision names the machine. It does not add a second scheduler, a lease, or a voice library.

## Hardware and operating system

Use a 64-bit board. A Raspberry Pi 4 or Raspberry Pi 5 with 4 GB of RAM is the recommended size. 2 GB is the smallest memory that should be considered for PostgreSQL and this process together. Use the official power supply for that board. Prefer wired Ethernet.

Use the 64-bit Raspberry Pi OS Lite image, which is Debian arm64. The image dated 6 October 2026 is Debian 13 (trixie), kernel 6.18, and is published for 64-bit boards including the Pi 4 and Pi 5 ([Raspberry Pi OS downloads](https://www.raspberrypi.com/software/operating-systems/)). Lite has no desktop. A 32-bit image is the wrong choice for the locked wheels, as recorded below.

Store PostgreSQL on a USB SSD (Pi 4) or NVMe SSD (Pi 5). Boot from that SSD when the board's bootloader supports it, so the SD card is not in the write path. An SD card as the only disk will wear out under PostgreSQL's write-ahead log.

## Python, uv, and locked packages on arm64

The baseline is Python 3.12.14, uv 0.12.23, and the lockfile. Debian 13 ships Python 3.13 as its default `python3` and does not publish a `python3.12` package in trixie ([Debian 13 release notes](https://www.debian.org/News/2025/20250809); [python3.12 is not in trixie](https://packages.debian.org/trixie/amd64/python3.12)). Do not point the service at `/usr/bin/python3`.

uv 0.12.23 publishes an `aarch64-unknown-linux-gnu` build ([uv 0.12.23 release](https://github.com/astral-sh/uv/releases/tag/0.12.23)). `uv python install` in this checkout reads `.python-version` and requests CPython 3.12.14. python-build-standalone release 20260814 publishes `cpython-3.12.14+20260814-aarch64-unknown-linux-gnu-install_only.tar.gz` ([release 20260814](https://github.com/astral-sh/python-build-standalone/releases/tag/20260814)). A later release moved the newest 3.12 build to 3.12.15. The Pi must still install 3.12.14. If `uv python install` cannot fetch that patch, stop and record the failure. Do not substitute 3.12.15 or Debian's Python 3.13 without a new decision.

Runtime and development wheels in `uv.lock` that contain native code include a manylinux aarch64 (or a pure Python) build. Checked in the lockfile: aiohttp 3.14.5, frozenlist 1.8.0, greenlet 3.5.6, librt 0.16.0, markupsafe 3.0.4, multidict 7.1.0, propcache 0.5.4, psycopg-binary 3.3.6, pydantic-core 2.50.1, SQLAlchemy 2.1.4, yarl 1.25.1, mypy 2.4.0, and ruff 0.17.1. discord.py 2.7.1, alembic, httpx, and pydantic-settings are pure Python. `uv sync --locked` is the install command from [development instructions](../DEVELOPMENT.md).

psycopg-binary 3.3.6, greenlet 3.5.6, and SQLAlchemy 2.1.4 have aarch64 wheels and no armv7/armhf wheel in the lockfile. A 32-bit Raspberry Pi OS install does not match those wheels.

No audio or voice package is locked. `pyproject.toml` depends on discord.py without a voice extra. discord.py 2.7.1 depends only on aiohttp. PyNaCl, libopus, and a DAVE library are not dependencies. This decision does not claim those future packages install on arm64. Voice capture remains unimplemented ([JDR-004](../ISSUES.md#jdr-004-meeting-capture-and-transcripts)).

## PostgreSQL 16

PostgreSQL 16 is the development and CI baseline (`postgres:16` in `.github/workflows/ci.yml`). Debian 13's default `postgresql` package is PostgreSQL 17 ([Debian 13 release notes](https://www.debian.org/News/2025/20250809)). Installing that metapackage does not satisfy the baseline.

PostgreSQL 16 for Debian trixie arm64 is published by the PostgreSQL apt repository. The trixie suite has a `binary-arm64` directory for major version 16 ([trixie-pgdg 16 arm64](https://apt.postgresql.org/pub/repos/apt/dists/trixie-pgdg/16/binary-arm64/)). The repository's own install instructions list arm64 as a supported architecture and trixie as a supported Debian release ([PostgreSQL Debian downloads](https://www.postgresql.org/download/linux/debian/)). The runbook installs the `postgresql-16` package from that repository. Confirm `server_version` starts with `16.` on the Pi. That package check has not been run on the team's Pi.

## Discord gateway

The current process needs the gateway. discord.py opens the WebSocket after calling Discord's gateway URL.

Discord's gateway documentation says an app fetches a WebSocket URL from Get Gateway or Get Gateway Bot, then connects to it. The documented example is `wss://gateway.discord.gg/?v=10&encoding=json`, and the documented Get Gateway response is `{"url": "wss://gateway.discord.gg/"}` ([Gateway](https://discord.com/developers/docs/topics/gateway)). That example has no explicit port. A `wss://` URL with no port uses TCP 443. The REST API base used by the same documentation set is `https://discord.com/api` ([API reference](https://discord.com/developers/docs/reference)), also TCP 443.

On a typical home NAT the Pi opens that outbound TLS connection. The router does not need an inbound forward for the gateway. A power loss or a WAN outage drops the socket. discord.py reconnects when the network returns. Reminder jobs older than the 60-second grace are skipped ([decision 0002](0002-meeting-reminders.md)). A morning brief is recovered only on the same local weekday ([decision 0003](0003-jira-morning-brief.md)).

A TLS handshake to `gateway.discord.gg:443` and an unauthenticated `GET https://discord.com/api/v10/gateway` show that outbound HTTPS works. They do not show that this bot identified. The live session check is the service log line `guild_commands_registered` after a real start, with no `discord_login_failed`. That start has not been run on the Pi.

## Discord voice

Voice is a separate transport. Discord's voice documentation says voice data uses UDP, and that the client must be able to receive UDP packets through a firewall or NAT, using UDP hole punching and the voice server's IP discovery. The voice server IP and UDP port arrive in the Ready payload. The documented example port is `1234`. The client then opens a UDP socket to that IP and port and selects the `udp` protocol. The voice WebSocket endpoint arrives in Voice Server Update, must not be cached, and does not include a URL scheme. The documented example endpoint is `sweetwater-12345.discord.media:2048`. Libraries prepend `wss://` ([Voice connections](https://discord.com/developers/docs/topics/voice-connections)).

That documentation does not fix voice media on UDP 50000-65535, and it does not put the voice WebSocket on port 443. The example WebSocket port is 2048, and the example UDP port is whatever Ready sends. A firewall that allows only outbound TCP 443 matches the gateway example and does not match the voice example. Treat "UDP 50000-65535" and "voice WebSocket on 443" as unverified operator shorthand, not as Discord's current specification.

No inbound port forward is the right home-NAT starting point: the Pi sends the outbound UDP packet, and the router's connection tracking must pass the reply back (the hole punch Discord documents). A router that drops that reply will fail voice even though HTTPS works. This repository cannot perform the punch. The process does not join a voice channel. Voice UDP support on the Pi is pending the live check below. Do not describe it as working.

## Outbound allowlist

Allow outbound traffic to the hosts the process and the install actually use. A wide-open egress rule is not a substitute. Addresses move, so allow names and the dynamic voice endpoint, and do not freeze a voice IP into this record. Discord says not to cache the voice server result.

Runtime, always:

| Purpose | Destination | Transport |
| --- | --- | --- |
| Discord REST API | `discord.com` ([API reference](https://discord.com/developers/docs/reference) base `https://discord.com/api`) | Outbound TCP 443 |
| Gateway WebSocket | The host in the Get Gateway URL. The documented example is `gateway.discord.gg` | Outbound TCP 443 (`wss`) |
| Gateway resume | The host in `resume_gateway_url` from Ready. It is chosen per session | Outbound TCP 443 (`wss`) |
| Discord CDN | `cdn.discordapp.com` (documented image base URL) and `media.discordapp.net` (documented sticker host) | Outbound TCP 443 |
| PostgreSQL | `127.0.0.1` only | TCP 5432 on the loopback interface |

Runtime, only while the morning-brief group is set: HTTPS to the host in `JIRA_BASE_URL`. [Decision 0003](0003-jira-morning-brief.md) requires `https://<site>.atlassian.net` with no userinfo, path, query, or fragment. `HttpJiraReader` calls `GET /rest/api/3/search/jql` on that host and does not follow redirects. Other Atlassian hosts are not used. Leave this row out while the brief group is unset.

Runtime, only for a future voice connection (not used by the current process):

| Purpose | Destination | Transport |
| --- | --- | --- |
| Voice WebSocket | The host and port in Voice Server Update. The documented example is `*.discord.media` port 2048 | Outbound TCP to that port (`wss`) |
| Voice media | The `ip` and `port` in the voice Ready payload | Outbound UDP, and the NAT reply to that flow |

Install time, from the Pi, when building or upgrading:

| Purpose | Destination |
| --- | --- |
| uv 0.12.23 installer | `releases.astral.sh` and the GitHub release assets for `astral-sh/uv` |
| CPython 3.12.14 | The host `uv python install` uses for python-build-standalone. The aarch64 archive is published on the GitHub release above |
| Locked wheels | `pypi.org` and `files.pythonhosted.org` (every wheel URL in `uv.lock` is on `files.pythonhosted.org`) |
| OS packages | The Raspberry Pi OS and Debian mirrors already configured on the image |
| PostgreSQL 16 | `apt.postgresql.org` and the key from `www.postgresql.org` |

NTP for `systemd-timesyncd` is part of the OS image, not a bot dependency. The schedules need a correct clock.

## Tradeoffs

The Pi is free of a hosting bill and the database stays on hardware the team controls. The costs are operational:

- A power cut stops PostgreSQL and the bot together. There is no second site. Use the official supply. A UPS is optional and is not assumed.
- A home internet outage, or a router reboot, drops the gateway. Jobs that fall outside the reminder grace or the brief's same-day window are not delivered later.
- SD card wear is a data-loss risk for PostgreSQL. An SSD is part of this decision, not an optional extra.
- The home router's public address can change and is visible to Discord and, when the brief is on, to Atlassian. Nothing in the bot configuration needs that address. Do not publish it, and do not forward ports toward the Pi.
- No inbound listener is required. PostgreSQL stays on loopback. SSH, if used for administration, is the only inbound service, and it is not part of the bot protocol.
- One Pi is one failure domain. A second process against the same database can deliver the same reminder or brief twice. Do not add one.

## Verification on the Pi

Run these steps on the Pi, from a checkout at the commit being deployed. Record the date, the command, and whether it passed. Do not record tokens, the database URL, Jira email, JQL, meeting titles, or audio.

1. Architecture and OS. `uname -m` must print `aarch64`. `dpkg --print-architecture` must print `arm64`. `/etc/os-release` must show a Debian 13 / trixie Raspberry Pi OS. A 32-bit result stops the install.
2. Python. In the checkout, as the service user, run `uv python install` and `uv run python -c 'import platform; print(platform.python_version(), platform.machine())'`. The required output is `3.12.14 aarch64`. Any other version stops the install.
3. PostgreSQL. `sudo -u postgres psql -c 'SHOW server_version;'` must start with `16.`. `SHOW listen_addresses;` must be `localhost` or `127.0.0.1`.
4. Gateway reachability, without a bot token. `curl --fail --silent --show-error --max-time 20 https://discord.com/api/v10/gateway` must return JSON containing a `wss://` URL. Then `openssl s_client -connect gateway.discord.gg:443 -servername gateway.discord.gg </dev/null` must show `Verify return code: 0`. This is outbound TLS 443 to the documented gateway host. It is not a gateway session.
5. Gateway session. Start the single systemd service in the runbook. `journalctl -u jdr-bot` must include `guild_commands_registered` and must not include `discord_login_failed`. Then run the Discord smoke check in [development instructions](../DEVELOPMENT.md). This step has not been run.
6. Voice UDP. This repository cannot open a voice connection. A local socket is not evidence: `python -c 'import socket; s=socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.bind(("0.0.0.0", 0)); print(s.getsockname()[1]); s.close()'` only prints an ephemeral local port. The Discord check, when a voice-capable build exists, is: join one private voice channel with consent; record the Voice Server Update host and port and the Ready UDP port; record whether IP discovery received a UDP reply; leave the channel. Do not record the voice token or any audio. Until that reply is observed on this Pi, voice UDP is unsupported for planning purposes. JDR-004 must not treat this host as proven.

Steps 1 through 4 can pass while step 6 is still pending. Passing steps 1 through 4 does not close issue #12. Step 5 is the live gateway check. Step 6 is the live voice check. Both are pending.

## What this does not decide

Which room the Pi sits in, whether a UPS is purchased, or the team's SSH source addresses. Whether a future voice library installs on arm64. Whether the home router's UDP state actually survives a voice flow. Whether Debian's PostgreSQL 17 could replace 16. Those stay out of this record until someone measures them.
