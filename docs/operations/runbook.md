# Production runbook

Operate the single Raspberry Pi host from [decision 0006](../decisions/0006-raspberry-pi-hosting.md). That decision is provisional. A Discord gateway session and voice UDP have not been verified on the Pi. Issue [#12](https://github.com/RileyHop1/JDR_Team_Management_bot/issues/12) stays open until the verification procedure in that decision is recorded.

The commands below are the repository's. Configuration names are the `Settings` fields in `src/jdr_bot/config.py` and the keys in [`.env.example`](../../.env.example). The process entry point is `jdr-bot` (`jdr_bot.__main__:main`). Migrations are Alembic, and they read `DATABASE_URL` from the environment. Alembic does not load a dotenv file by itself.

Development still uses the disposable Docker database in [development instructions](../DEVELOPMENT.md). The password in that Docker command is not a production credential.

## Before you start

- One Pi, one bot process, one PostgreSQL 16 cluster. Two bot processes against this database can post the same reminder or brief twice.
- Secrets live in `/etc/jdr-bot/env` and nowhere in Git. The file mode is `0600`, owner `root:root`.
- The service account is `jdrbot`. It is not an administrator and it has no login shell.
- Do not open an inbound port for Discord or for PostgreSQL.

## Operating system and hardening

Install Raspberry Pi OS Lite 64-bit (Debian 13 / trixie) and boot it from the SSD when the board supports USB or NVMe boot. Create the administrator in the Imager, with an SSH key. Do not keep a shared default password.

Apply updates, then keep security updates installing:

```sh
sudo apt update
sudo apt full-upgrade
sudo apt install -y unattended-upgrades
sudo dpkg-reconfigure -f noninteractive unattended-upgrades
```

Confirm the clock before relying on reminders or the brief. `timedatectl` must show that NTP is synchronized and that the time zone is what you expect. The bot's schedule uses the IANA zone in configuration, and the host clock has to be correct UTC.

SSH, if you use it, is the only inbound service. Keep the session you already have open, and open a second SSH session after `ufw enable` before you close the first one. In `/etc/ssh/sshd_config`, set `PermitRootLogin no` and `PasswordAuthentication no`, then reload `ssh`. Restrict the OpenSSH rule to the network you administer from when you know that network. Do not allow TCP 5432.

```sh
sudo apt install ufw
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow OpenSSH
sudo ufw enable
```

`ufw` default outgoing-allow is a starting point on a home router you do not otherwise filter. When you do filter egress, use the allowlist in decision 0006. Do not invent a broader rule as a shortcut.

## Disk for PostgreSQL

Prefer booting the whole OS from the SSD. PostgreSQL's data directory is then already off the SD card.

If the OS stays on the SD card, put an ext4 filesystem on the SSD and mount it at `/var/lib/postgresql` before you install PostgreSQL. Format only a disk you mean to erase. Use the filesystem UUID from `blkid` in `/etc/fstab`:

```text
UUID=<uuid> /var/lib/postgresql ext4 defaults,noatime,nofail,x-systemd.device-timeout=10s 0 2
```

`nofail` keeps a missing disk from blocking boot. It must not let PostgreSQL create a new empty cluster on the SD card. After the package is installed, add a drop-in so PostgreSQL refuses to start when that mount is absent:

```text
# /etc/systemd/system/postgresql.service.d/require-data-disk.conf
[Unit]
RequiresMountsFor=/var/lib/postgresql
```

The bot unit below has the same `RequiresMountsFor` line. When the SSD is the only disk, skip the fstab entry and this drop-in. The bot unit can keep the line: on a root filesystem it only requires `/`, which is already mounted.

## PostgreSQL 16

Debian 13's `postgresql` metapackage is PostgreSQL 17. Install `postgresql-16` from the PostgreSQL apt repository. The official instructions are at [PostgreSQL: Linux downloads (Debian)](https://www.postgresql.org/download/linux/debian/). On this Pi the architecture is arm64 and the suite is trixie. The automated helper detects both:

```sh
sudo apt install -y postgresql-common
sudo /usr/share/postgresql-common/pgdg/apt.postgresql.org.sh
sudo apt update
sudo apt install -y postgresql-16
sudo systemctl enable --now postgresql
```

Confirm the cluster before you create the application role. `--cluster 16/main` selects the version this project runs, including when another cluster exists:

```sh
pg_lsclusters
sudo -u postgres psql --cluster 16/main -c 'SHOW server_version;'
sudo -u postgres psql --cluster 16/main -c 'SHOW listen_addresses;'
```

`server_version` must start with `16.`. `listen_addresses` must be `localhost` or `127.0.0.1`. If a `postgresql` (17) cluster was also installed, do not point `DATABASE_URL` at it.

Create a role and a database whose names do not end in `_test`. The examples use `jdr_bot`. Generate a password with `openssl rand -hex 24` so it is safe inside a URL, type it into `createuser` when prompted, and store the same value only in `/etc/jdr-bot/env`. The password will be visible in your terminal while you copy it. Do not put it in the shell history file, a chat, or a command argument.

```sh
sudo -u postgres createuser --cluster 16/main --pwprompt --no-superuser --no-createdb --no-createrole jdr_bot
sudo -u postgres createdb --cluster 16/main --owner=jdr_bot jdr_bot
```

On a new PostgreSQL 16 database the `public` schema is owned by `pg_database_owner`, which follows the database owner, so `jdr_bot` can create the tables Alembic needs. If the migrate unit later fails because the role cannot create in `public`, run `sudo -u postgres psql --cluster 16/main -d jdr_bot -c 'ALTER SCHEMA public OWNER TO jdr_bot;'` and start the migrate unit again.

`sudo -u postgres psql --cluster 16/main -d jdr_bot -c 'SELECT 1;'` must succeed through peer authentication. The application itself connects with TCP and the URL below.

In `/etc/postgresql/16/main/pg_hba.conf`, keep TCP authentication on loopback only. A specific line is enough:

```text
host jdr_bot jdr_bot 127.0.0.1/32 scram-sha-256
host jdr_bot jdr_bot ::1/128 scram-sha-256
```

Remove any `host` line that listens beyond loopback. Reload with `sudo systemctl reload postgresql`.

## Python 3.12 and the checkout

Install uv 0.12.23 for arm64 into `/usr/local/bin`. `UV_UNMANAGED_INSTALL` keeps the installer from editing shell startup files and from later replacing this pin:

```sh
curl --proto '=https' --tlsv1.2 -LsSf \
  https://releases.astral.sh/github/uv/releases/download/0.12.23/uv-installer.sh \
  | sudo env UV_UNMANAGED_INSTALL=/usr/local/bin sh
uv --version
```

`uv --version` must report `0.12.23`.

Create the service account, clone the repository, and install the lockfile as that account. The nologin shell blocks interactive login. `sudo -u jdrbot` can still run `bash` for these steps.

```sh
sudo adduser --system --group --home /var/lib/jdr-bot --shell /usr/sbin/nologin jdrbot
sudo -u jdrbot -H git clone https://github.com/RileyHop1/JDR_Team_Management_bot.git /opt/jdr-bot
sudo -u jdrbot -H bash -c 'cd /opt/jdr-bot && uv python install && uv sync --locked'
```

`uv python install` reads `.python-version` and must install Python 3.12.14. `uv sync --locked` installs the locked runtime and the dev group (Ruff, mypy, pytest). The service does not run the dev tools. It runs `/opt/jdr-bot/.venv/bin/jdr-bot`, which is the `jdr-bot` script from `pyproject.toml`.

Check the interpreter before you continue:

```sh
sudo -u jdrbot -H bash -c 'cd /opt/jdr-bot && uv run python -c "import platform; print(platform.python_version(), platform.machine())"'
```

The required line is `3.12.14 aarch64`.

## Secrets

Create `/etc/jdr-bot/env` as root, mode `0600`. Copy the keys from `.env.example`. systemd reads this file as `EnvironmentFile` and injects the variables. The bot user does not need to read the file. Do not commit it, do not copy it into `/opt/jdr-bot/.env`, and do not put the values in the unit file. Unit files under `/etc/systemd/system` are world-readable.

`Settings` also looks for a `.env` in the working directory (`env_file=".env"` in `src/jdr_bot/config.py`). Leave that file absent. The locked pydantic-settings 2.16.0 skips a missing env file and uses the process environment. [Development instructions](../DEVELOPMENT.md) say environment variables take precedence over `.env`.

Use this shape. Replace every `replace-with-` value. A token that still starts with `replace-` is rejected at startup (`invalid_configuration` or `invalid_jira_configuration`, exit 2).

```text
DISCORD_BOT_TOKEN=replace-with-bot-token
DISCORD_GUILD_ID=123456789012345678
DISCORD_OPERATOR_ROLE_ID=123456789012345679
DATABASE_URL=postgresql+psycopg://jdr_bot:replace-with-database-password@127.0.0.1:5432/jdr_bot
BOT_TIMEZONE=UTC
```

`DATABASE_URL` must use the driver `postgresql+psycopg`, must name the database, and must point at `127.0.0.1`. `BOT_TIMEZONE` is an IANA name. `UTC` matches `.env.example` until the team confirms the zone in decision 0002.

Leave the morning-brief keys unset until that feature is turned on. If you set any of `BRIEF_CHANNEL_ID`, `BRIEF_TIME`, `JIRA_BASE_URL`, `JIRA_PROJECT_KEY`, `JIRA_STATUS_NAMES`, `JIRA_JQL`, `JIRA_USER_EMAIL`, or `JIRA_API_TOKEN`, you must set the whole group. `JIRA_STATUS_NAMES` is required unless `JIRA_JQL` is set. `JIRA_BASE_URL` is `https://<site>.atlassian.net`. The token and the email stay in this file. They are not stored in PostgreSQL. `MEETINGS_CHANNEL_ID` is optional. `TRANSCRIPTION_API_KEY` is not read. Do not add it.

systemd's `EnvironmentFile` is not a shell script. Do not prefix lines with `export`. A value that contains `#` will be read as a comment unless you quote it using systemd's rules. A hex database password and a normal Discord token do not need quotes.

```sh
sudo install -d -m 0755 /etc/jdr-bot
sudo install -m 0600 -o root -g root /dev/null /etc/jdr-bot/env
sudoedit /etc/jdr-bot/env
sudo chmod 0600 /etc/jdr-bot/env
stat -c '%a %U %G' /etc/jdr-bot/env
```

`stat` must print `600 root root`.

## systemd

`jdr-bot` handles `SIGTERM` and `SIGINT` in `src/jdr_bot/__main__.py`. systemd's default stop signal is `SIGTERM`. The unit stays in the foreground (`Type=simple`).

`Restart=on-failure` with a start limit brings the process back after a crash or a transient `database_unreachable` (exit 1). `RestartPreventExitStatus=2` leaves invalid configuration stopped. Exit 2 will not succeed until the env file changes. Five failures in five minutes stop the restart loop. Read the journal, fix the cause, then `sudo systemctl reset-failed jdr-bot` and start again.

Write `/etc/systemd/system/jdr-bot.service`:

```ini
[Unit]
Description=JDR Team Management Bot
After=network-online.target postgresql.service
Wants=network-online.target
Requires=postgresql.service
RequiresMountsFor=/var/lib/postgresql

[Service]
Type=simple
User=jdrbot
Group=jdrbot
WorkingDirectory=/opt/jdr-bot
EnvironmentFile=/etc/jdr-bot/env
ExecStart=/opt/jdr-bot/.venv/bin/jdr-bot
Restart=on-failure
RestartSec=5
RestartPreventExitStatus=2
StartLimitIntervalSec=300
StartLimitBurst=5
TimeoutStopSec=30
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=strict
UMask=0077
StandardOutput=journal
StandardError=journal
SyslogIdentifier=jdr-bot

[Install]
WantedBy=multi-user.target
```

`RequiresMountsFor=/var/lib/postgresql` is safe when that path is on the root filesystem: systemd then only requires `/`. `ProtectSystem=strict` makes the checkout read-only to the process. Durable state is PostgreSQL, not a file in the checkout. `ProtectHome=true` hides `/root` and `/home`. The service account's home is `/var/lib/jdr-bot`, which is where `uv python install` stores CPython, so the virtualenv's interpreter remains readable.

When the Pi uses NetworkManager, enable its wait service so `network-online.target` means a configured link:

```sh
sudo systemctl enable NetworkManager-wait-online.service
```

Migrations are a separate oneshot. It uses the same env file and the virtualenv's `alembic`, which is what `uv run --env-file .env alembic upgrade head` runs in development. The oneshot gets `DATABASE_URL` from systemd, so the env file can stay mode `0600`.

Write `/etc/systemd/system/jdr-bot-migrate.service`:

```ini
[Unit]
Description=Apply JDR bot Alembic migrations
Requires=postgresql.service
After=postgresql.service

[Service]
Type=oneshot
User=jdrbot
Group=jdrbot
WorkingDirectory=/opt/jdr-bot
EnvironmentFile=/etc/jdr-bot/env
ExecStart=/opt/jdr-bot/.venv/bin/alembic upgrade head
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=strict
UMask=0077
```

```sh
sudo systemctl daemon-reload
```

Do not enable the migrate unit. Run it only when you intend to change the schema.

## First migration and start

Install `/usr/local/sbin/jdr-pg-dump`, `/var/backups/jdr`, and the timer from the next section before you migrate. Run `sudo systemctl start jdr-pg-dump.service` and confirm a dump file exists. On a new database the dump has no meetings yet. Then:

```sh
sudo systemctl start jdr-bot-migrate.service
sudo systemctl status jdr-bot-migrate.service
sudo -u postgres psql --cluster 16/main -d jdr_bot -c 'SELECT version_num FROM alembic_version;'
sudo systemctl enable --now jdr-bot.service
```

Alembic's own log is not the secret-safe startup logger. A failed migration can print the driver message, and that message can include `DATABASE_URL`. Read `journalctl -u jdr-bot-migrate` on the Pi. Do not copy it into a chat or an issue. If it includes the URL, rotate the database password and update `/etc/jdr-bot/env`.

`version_num` must be `0004` (`SCHEMA_REVISION` in `src/jdr_bot/storage.py`). The bot journal must include `scheduler_started`. When the brief group is unset it also includes `brief_scheduler_disabled`. It must not include a token, a database URL, or a Jira email.

Then run the gateway session check in decision 0006. That check is still pending.

## Backups and a restore test

Dump as the `postgres` OS user so the password never appears on a command line. Install `/usr/local/sbin/jdr-pg-dump` mode `0755`, owner `root:root`:

```sh
#!/bin/sh
set -eu
umask 077
dest=/var/backups/jdr
stamp=$(date -u +%Y%m%dT%H%M%SZ)
pg_dump --cluster 16/main --format=custom --file="$dest/jdr_bot-$stamp.dump" jdr_bot
find "$dest" -type f -name 'jdr_bot-*.dump' -mtime +7 -delete
```

```sh
sudo install -d -o postgres -g postgres -m 0700 /var/backups/jdr
```

The directory is on the same machine as the database. A dump that never leaves the Pi is lost with the disk. Copy the newest file to storage that is not this Pi, with `scp` or `rsync` over SSH, using a key that is not stored in the repository. Dumps contain meeting titles and other rows. Treat them as meeting data: mode `0600`, no public share, no attachment in a chat. The local `find` deletes files older than seven days. Copy them off the Pi before that.

Write `/etc/systemd/system/jdr-pg-dump.service`:

```ini
[Unit]
Description=Dump the JDR bot database
Requires=postgresql.service
After=postgresql.service

[Service]
Type=oneshot
User=postgres
Group=postgres
ExecStart=/usr/local/sbin/jdr-pg-dump
```

Write `/etc/systemd/system/jdr-pg-dump.timer`:

```ini
[Unit]
Description=Daily JDR bot database dump

[Timer]
OnCalendar=daily
Persistent=true
RandomizedDelaySec=1h

[Install]
WantedBy=timers.target
```

```sh
sudo systemctl daemon-reload
sudo systemctl enable --now jdr-pg-dump.timer
```

`Persistent=true` runs a missed dump after a power cut. Run one dump by hand before you rely on the timer: `sudo systemctl start jdr-pg-dump.service`.

Restore test, into a database that is not `jdr_bot` and does not end in `_test`. The integration tests refuse a database whose name does not end in `_test`, and they delete rows when they run. Do not point `DATABASE_URL` or `TEST_DATABASE_URL` at `jdr_bot` or at the restore database.

```sh
sudo systemctl start jdr-pg-dump.service
sudo -u postgres createdb --cluster 16/main jdr_restore_check
sudo -u postgres pg_restore --cluster 16/main --dbname=jdr_restore_check /var/backups/jdr/jdr_bot-<stamp>.dump
sudo -u postgres psql --cluster 16/main -d jdr_restore_check -c 'SELECT version_num FROM alembic_version;'
sudo -u postgres dropdb --cluster 16/main jdr_restore_check
```

`version_num` must match the source database. Record the date of the test. Repeat it after the first real backup and after any upgrade that changes the schema. Drop `jdr_restore_check` when the check is finished.

## Later migrations

The application expects revision `0004`. A newer checkout can expect a newer revision. Order:

1. Record `git -C /opt/jdr-bot rev-parse HEAD`.
2. `sudo systemctl start jdr-pg-dump.service` and copy that dump off the Pi.
3. `sudo systemctl stop jdr-bot.service`. Confirm no second process: `pgrep -a -f '/opt/jdr-bot/.venv/bin/jdr-bot'` prints nothing.
4. Update the checkout and the virtualenv as `jdrbot` (see upgrades below).
5. `sudo systemctl start jdr-bot-migrate.service` and confirm it exited 0.
6. Confirm `alembic_version` with `sudo -u postgres psql --cluster 16/main -d jdr_bot -c 'SELECT version_num FROM alembic_version;'`, then `sudo systemctl start jdr-bot.service`.
7. Confirm `scheduler_started` and the absence of `schema_outdated`.

If `DATABASE_URL` is missing, Alembic exits before connecting and names `uv run --env-file .env alembic upgrade head`. It does not print a URL. On the Pi, fix `/etc/jdr-bot/env` and rerun the oneshot. The oneshot is the production form of that command. A connection error from Alembic can still include the URL. Keep that journal on the Pi.

Downgrading revision `0004` to `0003` deletes stored guild settings. A downgrade can delete other data too. Restore the dump from step 2 and check out the previous commit. Do not use `alembic downgrade` on this database as the rollback.

## One scheduler

Reminders and the morning brief run in one background task inside this process ([decision 0002](../decisions/0002-meeting-reminders.md), [architecture](../ARCHITECTURE.md)). The only supervised start is `jdr-bot.service`.

Before a manual `uv run jdr-bot`, stop the service and confirm the process list is empty. Start the service again when the manual run is finished. Do not run a second checkout, a second Pi, or a developer laptop against `jdr_bot`. There is no database lease.

## Logs

The process configures logging in `main()`:

```text
%(levelname)s %(name)s %(message)s
```

Level `INFO`. systemd sends stdout and stderr to the journal. Read them with:

```sh
journalctl -u jdr-bot -n 100 --no-pager
```

Startup failures use the fixed categories in [decision 0005](../decisions/0005-startup-failures.md) and the troubleshooting list in [development instructions](../DEVELOPMENT.md). Configuration failures exit 2. Other startup failures exit 1. The lines name categories and field names. They omit exception text, driver messages, the revision value, tokens, database URLs, Jira email, and JQL.

Job lines include ids and categories (`reminder_delivered`, `brief_delivered`, `meeting_created`, `guild_config_updated`). They do not include meeting titles, issue titles, assignee names, transcript text, or audio. Voice transcripts are not implemented. Do not turn on discord.py debug logging, and do not wrap the service in a shell that prints the environment. Either change can put a secret in the journal.

If a journal line contains a token or meeting content, stop the service, rotate that credential, and report it to the contact in [SECURITY.md](../../SECURITY.md). Do not paste the line into a public issue.

Cap journal growth on a small disk. In `/etc/systemd/journald.conf` set `SystemMaxUse=200M`, then `sudo systemctl restart systemd-journald`.

## Upgrades and rollback

Stop the bot before replacing code. Record the current SHA first.

```sh
git -C /opt/jdr-bot rev-parse HEAD
sudo systemctl stop jdr-bot.service
sudo -u jdrbot -H git -C /opt/jdr-bot fetch origin
sudo -u jdrbot -H git -C /opt/jdr-bot checkout <recorded-sha>
sudo -u jdrbot -H bash -c 'cd /opt/jdr-bot && uv sync --locked'
```

Take a dump, run `jdr-bot-migrate.service` if the new checkout changes the schema, then start `jdr-bot.service`. Deploy a commit you can name. Do not leave the checkout on an unrecorded local edit.

Rollback when the new process fails before a migration has been applied: `git checkout` the recorded SHA, `uv sync --locked`, and start the service.

Rollback when a migration has been applied: stop the bot, restore the dump taken before the migration, check out the old SHA, `uv sync --locked`, and start.

```sh
sudo systemctl stop jdr-bot.service
sudo -u postgres psql --cluster 16/main -d postgres -c 'DROP DATABASE jdr_bot;'
sudo -u postgres psql --cluster 16/main -d postgres -c 'CREATE DATABASE jdr_bot OWNER jdr_bot;'
sudo -u postgres pg_restore --cluster 16/main --dbname=jdr_bot /var/backups/jdr/jdr_bot-<stamp>.dump
```

Confirm `alembic_version`, then start the service on the old SHA. `DROP DATABASE` destroys the current rows. Use it only to replace them with the dump you just verified.

## Gateway and voice checks

Follow [verification on the Pi](../decisions/0006-raspberry-pi-hosting.md#verification-on-the-pi). Outbound TLS to `gateway.discord.gg:443` and `GET https://discord.com/api/v10/gateway` are the reachability checks. `guild_commands_registered` is the session check. Voice UDP stays pending until a voice-capable build receives a UDP discovery reply on this network. Do not treat a successful HTTPS check as a voice result.

When the brief is enabled, confirm the Jira host answers TLS without sending the token:

```sh
curl --silent --output /dev/null --show-error --max-time 20 \
  --write-out '%{http_code}\n' "https://<site>.atlassian.net/"
```

Any HTTP status means TCP 443 reached that host. A timeout or a DNS error means it did not. The status is not a successful brief. The brief smoke check in [development instructions](../DEVELOPMENT.md) is still a separate live test.
