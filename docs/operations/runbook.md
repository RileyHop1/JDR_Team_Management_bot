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

Debian 13's `postgresql` metapackage is PostgreSQL 17. Install `postgresql-16` from the PostgreSQL apt repository. Do not install the `postgresql` metapackage or `postgresql-17`. That metapackage creates a `17/main` cluster, and `pg_wrapper` defaults to the highest installed cluster. The official instructions are at [PostgreSQL: Linux downloads (Debian)](https://www.postgresql.org/download/linux/debian/). On this Pi the architecture is arm64 and the suite is trixie. The helper `/usr/share/postgresql-common/pgdg/apt.postgresql.org.sh` is shipped by `postgresql-client-common`. `postgresql-common` depends on that package, so the install below provides the script. Pass `-y`. Without it the helper waits on `Press Enter to continue`.

```sh
sudo apt install -y postgresql-common
sudo /usr/share/postgresql-common/pgdg/apt.postgresql.org.sh -y
sudo apt update
sudo apt install -y postgresql-16
if pg_lsclusters --no-header | awk '{ if ($1 == 17) found=1 } END { exit !found }'; then
  pg_lsclusters --no-header | awk '$1 == 17 { print $2 }' | while IFS= read -r cluster; do
    sudo pg_dropcluster --stop 17 "$cluster"
  done
fi
if dpkg-query -W -f '${Status}' postgresql 2>/dev/null | grep -q 'install ok installed'; then
  sudo apt purge -y postgresql
fi
if dpkg-query -W -f '${Status}' postgresql-17 2>/dev/null | grep -q 'install ok installed'; then
  sudo apt purge -y postgresql-17
fi
sudo systemctl enable --now postgresql
```

`pg_dropcluster` deletes that cluster's data. Use it here only for a leftover default 17 cluster. This project does not use PostgreSQL 17. After the block, `pg_lsclusters` must show `16/main` and must not show a 17 cluster.

Confirm the cluster before you create the application role. `--cluster 16/main` selects the version this project runs. An unqualified `psql` would read a leftover 17 cluster:

```sh
pg_lsclusters
sudo -u postgres psql --cluster 16/main -c 'SHOW server_version;'
sudo -u postgres psql --cluster 16/main -c 'SHOW listen_addresses;'
```

`server_version` must start with `16.`. `listen_addresses` must be `localhost` or `127.0.0.1`.

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

Create the service account, clone the repository, and install the lockfile as that account. The nologin shell blocks interactive login. `sudo -u jdrbot` can still run `bash` for these steps. `/opt` is `root:root` mode `0755`, so `jdrbot` cannot create `/opt/jdr-bot`. Root creates that directory and gives it to `jdrbot`. The clone runs as `jdrbot`.

```sh
sudo adduser --system --group --home /var/lib/jdr-bot --shell /usr/sbin/nologin jdrbot
sudo install -d -o jdrbot -g jdrbot -m 0755 /opt/jdr-bot
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

`Restart=on-failure` with a start limit brings the process back after a crash or a transient `database_unreachable` (exit 1). `RestartPreventExitStatus=2` leaves invalid configuration stopped. Exit 2 will not succeed until the env file changes. Invalid configuration and an invalid Jira group exit 2. Every other startup failure exits 1. Five failures in five minutes stop the restart loop. `StartLimitIntervalSec=` and `StartLimitBurst=` belong in `[Unit]`. In `[Service]` systemd ignores them, and the default interval is 10 seconds, so the five-minute cap never applies. Read the journal, fix the cause, then `sudo systemctl reset-failed jdr-bot` and start again.

Write `/etc/systemd/system/jdr-bot.service`:

```ini
[Unit]
Description=JDR Team Management Bot
After=network-online.target postgresql.service postgresql@16-main.service
Wants=network-online.target postgresql.service
PartOf=postgresql@16-main.service
RequiresMountsFor=/var/lib/postgresql
StartLimitIntervalSec=300
StartLimitBurst=5

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

`Wants=postgresql.service` and `After=` start PostgreSQL before the bot. They do not stop the bot when PostgreSQL restarts. `Requires=postgresql.service` would: a restart of `postgresql.service` stops `jdr-bot`, the handled `SIGTERM` exits 0, and `Restart=on-failure` does not start an exit 0. `PartOf=postgresql@16-main.service` propagates stop and restart from the cluster unit, so the bot returns when that unit restarts. `unattended-upgrades` can restart `postgresql@16-main.service` when it installs a PostgreSQL security update. After that upgrade, confirm `systemctl is-active jdr-bot.service` prints `active` and that the current invocation logged `has connected to Gateway`. The migrate and dump oneshots keep `Requires=postgresql.service` because they should fail immediately when PostgreSQL is not up, and they are not left running across a later restart.

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

Install `/usr/local/sbin/jdr-pg-dump`, `/usr/local/sbin/jdr-backup-rotate`, `/var/backups/jdr`, and both timers from the next section before you migrate. Run `sudo systemctl start jdr-pg-dump.service` and confirm a dump file exists. On a new database the dump has no meetings yet. Enable the rotation timer as well: a failed dump must not be what deletes old files. Then:

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
umask 027
dest=/var/backups/jdr
stamp=$(date -u +%Y%m%dT%H%M%SZ)
pg_dump --cluster 16/main --format=custom --file="$dest/jdr_bot-$stamp.dump" jdr_bot
```

`set -eu` stops this script when `pg_dump` fails. Rotation is not in the script. A stretch of failed dumps still deletes old files, because `jdr-backup-rotate.timer` is a separate unit and does not follow this oneshot. The filename stamp is the UTC instant just before `pg_dump`. [Decision 0007](../decisions/0007-meeting-data-retention.md) uses that stamp as the age of the copy.

```sh
if ! getent group jdrbackup >/dev/null; then
  sudo groupadd --system jdrbackup
fi
sudo usermod -aG jdrbackup "$USER"
sudo install -d -o postgres -g jdrbackup -m 2750 /var/backups/jdr
```

Run that block from the administrator's shell so `$USER` is that account. Log in again so the new group is active. `id` must list `jdrbackup`. The directory is setgid `2750`, owner `postgres`, group `jdrbackup`. `umask 027` makes each dump mode `0640`. `stat -c '%a %U %G'` on the new dump must print `640 postgres jdrbackup`. The file is not world-readable. Do not use mode `0644` or `0666`.

The directory is on the same machine as the database. A dump that never leaves the Pi is lost with the disk. A file mode `0600` owned by `postgres` cannot be read by an off-Pi `scp` or `rsync` as the administrator. Membership in `jdrbackup` is what makes the `0640` dump readable. After the new login, copy the newest file with the administrator's own SSH key. `stamp` is the UTC stamp in the filename. Dumps contain meeting titles and other rows. Once meeting capture stores content, a dump contains that content too. Treat every dump as meeting data: no public share, no attachment in a chat. Copy a dump off the Pi before the local rotation deletes it. Both copies expire from the filename stamp, not from the time of the copy, and both are deleted before the file is 7 days old ([decision 0007](../decisions/0007-meeting-data-retention.md)). A dump kept for rollback lives in the same directory tree and keeps that stamp in its name. The live database still keeps meeting titles, reminders, and guild settings. This rotation does not expire those rows.

```sh
backup_host=${backup_host:?set backup_host to the off-Pi SSH host}
backup_dir=${backup_dir:?set backup_dir to the destination directory}
stamp=${stamp:?set stamp to the UTC stamp in the dump filename}
rsync -a --chmod=F640 "/var/backups/jdr/jdr_bot-${stamp}.dump" "${backup_host}:${backup_dir}/"
```

`--chmod=F640` keeps the remote file non-world-readable. If the SSH session is not in `jdrbackup` yet, root can read the dump and push it with the same mode. That uses root's SSH key:

```sh
backup_host=${backup_host:?set backup_host to the off-Pi SSH host}
backup_dir=${backup_dir:?set backup_dir to the destination directory}
stamp=${stamp:?set stamp to the UTC stamp in the dump filename}
sudo rsync -a --chmod=F640 "/var/backups/jdr/jdr_bot-${stamp}.dump" "${backup_host}:${backup_dir}/"
```

Delete every dump file before it is 7 days old. That includes the Pi copy, the off-Pi copy, and a dump kept for rollback. [Decision 0007](../decisions/0007-meeting-data-retention.md) splits the 30-day total into a 23-day live purge and this dump cap, so a dump taken just before the live purge is gone by day 30. The age is the filename stamp, not the modification time. `rsync -a` still preserves modification time and mode. Rotation does not read that time, so a later copy that resets it does not extend the file's life. Do not keep another copy outside the rotated directory. A restore loads whatever the file still holds. Do not restore a dump to recover meeting-capture content after its deletion deadline. After a restore, content past that deadline has to be purged again before the database matches decision 0007.

Install `/usr/local/sbin/jdr-backup-rotate` mode `0755`, owner `root:root`, on the Pi and on the backup host. The script is POSIX `sh`. It does not use GNU `find -mmin`, `find -mtime`, or `find -delete`. The backup host is not required to have GNU find. It deletes a file whose name ends in `.dump` once the embedded `jdr_bot-YYYYMMDDTHHMMSSZ` stamp is 6 days (8640 minutes) old, at any depth under the directory you pass. A rollback name such as `jdr_bot-20261023T004730Z.rollback.dump` carries the same stamp and is included. A `.dump` file with no stamp is deleted on the next run.

```sh
#!/bin/sh
# Delete JDR pg_dump files before they are 7 days old.
# POSIX sh: no GNU find -mmin, -mtime, or -delete.
# A day is 24 hours. The filename stamp is the UTC instant just before pg_dump.
# Files are deleted once that stamp is 6 days (8640 minutes) old.
set -eu

classify() {
  # Print "delete" or "keep". Empty output is a failure.
  printf '%s\n%s\n' "$1" "$2" | awk '
    NR == 1 { name = $0 }
    NR == 2 {
      cutoff = $0
      s = name
      n = length(s)
      i = 1
      stamp = ""
      while (i + 23 <= n) {
        if (substr(s, i, 8) == "jdr_bot-") {
          cand = substr(s, i + 8, 16)
          if (cand ~ /^[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]T[0-9][0-9][0-9][0-9][0-9][0-9]Z$/) {
            stamp = cand
            break
          }
        }
        i++
      }
      if (stamp == "" || stamp <= cutoff) {
        print "delete"
      } else {
        print "keep"
      }
    }
  '
}

if [ "${1:-}" = "--apply" ]; then
  cutoff=${2:?missing cutoff}
  shift 2
  for path do
    name=${path##*/}
    decision=$(classify "$name" "$cutoff") || decision=
    if [ "$decision" != "delete" ] && [ "$decision" != "keep" ]; then
      printf '%s\n' "jdr-backup-rotate: classify failed" >&2
      exit 1
    fi
    if [ "$decision" = "delete" ]; then
      rm -f -- "$path"
    fi
  done
  exit 0
fi

dest=${1:?set dest to the dump directory}
if [ ! -d "$dest" ]; then
  printf '%s\n' "jdr-backup-rotate: not a directory" >&2
  exit 1
fi

now=$(date -u +%Y%m%d%H%M%S)
cutoff=$(printf '%s\n' "$now" | awk '
  BEGIN { split("31 28 31 30 31 30 31 31 30 31 30 31", md) }
  {
    y = substr($0, 1, 4) + 0
    mo = substr($0, 5, 2) + 0
    d = substr($0, 7, 2) + 0
    rest = substr($0, 9, 6)
    d -= 6
    while (d < 1) {
      mo -= 1
      if (mo < 1) {
        mo = 12
        y -= 1
      }
      dim = md[mo] + 0
      if (mo == 2 && (y % 4 == 0 && (y % 100 != 0 || y % 400 == 0))) {
        dim = 29
      }
      d += dim
    }
    printf "%04d%02d%02dT%sZ\n", y, mo, d, rest
  }
')

find "$dest" -type f -name '*.dump' -exec "$0" --apply "$cutoff" {} +
```

Six days is the eligibility point, not the cap. The cap is 7 days (10080 minutes). `jdr-backup-rotate.timer` can be late by two hourly slots, plus `RandomizedDelaySec=5min`, plus `AccuracySec=1min`: 126 minutes. The latest deletion is 8640 + 126 = 8766 minutes of age (6 days, 2 hours, and 6 minutes), which is 1314 minutes (21 hours and 54 minutes) before the cap. GNU `find -mtime +6` would not become true until 7 days, and GNU `-mmin` is not portable to the backup host. This script is the command both hosts run.

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

`Persistent=true` runs a missed dump after a power cut. Run one dump by hand before you rely on the timer: `sudo systemctl start jdr-pg-dump.service`. The dump timer does not rotate files.

Write `/etc/systemd/system/jdr-backup-rotate.service`. It does not `Require=` or `After=` `jdr-pg-dump.service` or `postgresql.service`. Rotation runs when `pg_dump` has been failing and when PostgreSQL is stopped.

```ini
[Unit]
Description=Delete JDR database dumps before they are 7 days old
After=local-fs.target

[Service]
Type=oneshot
User=postgres
Group=postgres
ExecStart=/usr/local/sbin/jdr-backup-rotate /var/backups/jdr
```

Write `/etc/systemd/system/jdr-backup-rotate.timer`:

```ini
[Unit]
Description=Hourly deletion of old JDR database dumps

[Timer]
OnCalendar=hourly
AccuracySec=1min
Persistent=true
RandomizedDelaySec=5min

[Install]
WantedBy=timers.target
```

```sh
sudo systemctl daemon-reload
sudo systemctl enable --now jdr-backup-rotate.timer
```

`Persistent=true` runs one missed deletion after a power cut. The randomized delay still applies to that catch-up, and the 126-minute budget above includes it. Confirm a run by hand: `sudo systemctl start jdr-backup-rotate.service`. A failed `jdr-pg-dump.service` does not stop this timer.

On the backup host, install the same script and point it at the backup directory, including any `rollback/` subdirectory. Replace the path and the account below with the account that owns those files. This unit is independent of the Pi's `pg_dump` timer.

```ini
[Unit]
Description=Delete off-Pi JDR database dumps before they are 7 days old
After=local-fs.target

[Service]
Type=oneshot
User=backup
Group=backup
ExecStart=/usr/local/sbin/jdr-backup-rotate /var/backups/jdr-remote
```

```ini
[Unit]
Description=Hourly deletion of off-Pi JDR database dumps

[Timer]
OnCalendar=hourly
AccuracySec=1min
Persistent=true
RandomizedDelaySec=5min

[Install]
WantedBy=timers.target
```

If the backup host has no systemd, run the same script from cron. The hourly line is the steady schedule. `@reboot` is the catch-up for a missed hour, which is the cron form of `Persistent=true`. Cron has no randomized delay, so it deletes sooner than the Pi timer, still before 7 days.

```text
0 * * * * /usr/local/sbin/jdr-backup-rotate /var/backups/jdr-remote
@reboot /usr/local/sbin/jdr-backup-rotate /var/backups/jdr-remote
```

Restore test, into a database that is not `jdr_bot` and does not end in `_test`. The integration tests refuse a database whose name does not end in `_test`, and they delete rows when they run. Do not point `DATABASE_URL` or `TEST_DATABASE_URL` at `jdr_bot` or at the restore database.

```sh
stamp=${stamp:?set stamp to the UTC stamp in the dump filename}
sudo systemctl start jdr-pg-dump.service
sudo -u postgres createdb --cluster 16/main jdr_restore_check
sudo -u postgres pg_restore --cluster 16/main --dbname=jdr_restore_check "/var/backups/jdr/jdr_bot-${stamp}.dump"
sudo -u postgres psql --cluster 16/main -d jdr_restore_check -c 'SELECT version_num FROM alembic_version;'
sudo -u postgres dropdb --cluster 16/main jdr_restore_check
```

`version_num` must match the source database. Record the date of the test. Repeat it after the first real backup and after any upgrade that changes the schema. Drop `jdr_restore_check` when the check is finished.

## Later migrations

The application expects revision `0004`. A newer checkout can expect a newer revision. Order:

1. Record the deployed SHA in `previous` with `previous=$(sudo -u jdrbot -H git -C /opt/jdr-bot rev-parse HEAD)`. That value is the rollback target. Do not check it out as the upgrade.
2. `sudo systemctl start jdr-pg-dump.service` and copy that dump off the Pi into the rotated backup directory. Keep the `jdr_bot-YYYYMMDDTHHMMSSZ` stamp in the filename, including a rollback suffix such as `.rollback.dump`. The off-Pi rotation deletes it before the file is 7 days old, with every other dump in that directory.
3. `sudo systemctl stop jdr-bot.service`. Confirm no second process: `pgrep -a -f '/opt/jdr-bot/.venv/bin/jdr-bot'` prints nothing.
4. Check out the new commit and update the virtualenv as `jdrbot`, using the upgrade block below. Set `TARGET_REF` to that new commit SHA or tag. The block checks out `TARGET_REF`. It leaves `previous` for rollback.
5. `sudo systemctl start jdr-bot-migrate.service` and confirm it exited 0.
6. Confirm `alembic_version` with `sudo -u postgres psql --cluster 16/main -d jdr_bot -c 'SELECT version_num FROM alembic_version;'`, then `sudo systemctl start jdr-bot.service`.
7. Confirm `scheduler_started` and the absence of `schema_outdated`.

If `DATABASE_URL` is missing, Alembic exits before connecting and names `uv run --env-file .env alembic upgrade head`. It does not print a URL. On the Pi, fix `/etc/jdr-bot/env` and rerun the oneshot. The oneshot is the production form of that command. A connection error from Alembic can still include the URL. Keep that journal on the Pi.

Downgrading revision `0004` to `0003` deletes stored guild settings. A downgrade can delete other data too. Restore the dump from step 2 and check out `previous`, the SHA recorded in step 1. Do not use `alembic downgrade` on this database as the rollback.

## One scheduler

Reminders and the morning brief run in one background task inside this process ([decision 0002](../decisions/0002-meeting-reminders.md), [architecture](../ARCHITECTURE.md)). The only supervised start is `jdr-bot.service`.

`/etc/jdr-bot/env` is mode `0600` and owner `root:root`. systemd reads it as root before it starts `jdrbot`. A shell command `uv run jdr-bot`, including `sudo -u jdrbot`, cannot read that file and exits `invalid_configuration` (exit 2). Do not change the file to a world-readable mode and do not add `jdrbot` to a group that can read it. Stop the service and confirm the process list is empty before a foreground run, then let systemd load the env file:

```sh
sudo systemctl stop jdr-bot.service
pgrep -a -f '/opt/jdr-bot/.venv/bin/jdr-bot' || true
sudo systemd-run --collect --wait --pty \
  --uid=jdrbot --gid=jdrbot \
  --working-directory=/opt/jdr-bot \
  --property=EnvironmentFile=/etc/jdr-bot/env \
  /opt/jdr-bot/.venv/bin/jdr-bot
```

`pgrep` prints nothing when no second process is running. `systemd-run` reads `EnvironmentFile` as root and then runs the program as `jdrbot`. Start `jdr-bot.service` again when the foreground run is finished. Do not run a second checkout, a second Pi, or a developer laptop against `jdr_bot`. There is no database lease.

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

Job lines include ids and categories (`reminder_delivered`, `brief_delivered`, `meeting_created`, `guild_config_updated`). They do not include meeting titles, issue titles, assignee names, transcript text, or audio. Voice transcripts are not implemented. When capture exists, `meeting_content_purged` and `meeting_content_deleted_on_request` log the session id and the artifact id only. `meeting_content_purge_failed` logs those ids and one fixed category (`discord_receipt_missing`, `provider_delete_unsupported`, `provider_delete_failed`, or `local_delete_failed`). The two success events do not carry a category, and none of the three logs a Discord user id. [Decision 0007](../decisions/0007-meeting-data-retention.md) is the source of that shape. Those lines omit meeting content. Do not turn on discord.py debug logging, and do not wrap the service in a shell that prints the environment. Either change can put a secret in the journal.

If a journal line contains a token or meeting content, stop the service, rotate that credential, and report it to the contact in [SECURITY.md](../../SECURITY.md). Do not paste the line into a public issue.

Cap journal growth on a small disk. In `/etc/systemd/journald.conf` set `SystemMaxUse=200M`, then `sudo systemctl restart systemd-journald`.

## Upgrades and rollback

Stop the bot before replacing code. Set `TARGET_REF` to the new commit SHA or tag to deploy. A local branch name can still point at the old commit after `fetch`. Record the SHA that is running now in `previous`. The checkout below deploys `TARGET_REF`. Later migrations step 4 uses this block for the update.

```sh
previous=$(sudo -u jdrbot -H git -C /opt/jdr-bot rev-parse HEAD)
printf '%s\n' "$previous"
sudo systemctl stop jdr-bot.service
sudo -u jdrbot -H git -C /opt/jdr-bot fetch origin
sudo -u jdrbot -H git -C /opt/jdr-bot checkout "${TARGET_REF:?set TARGET_REF to the new commit SHA or tag}"
sudo -u jdrbot -H bash -c 'cd /opt/jdr-bot && uv sync --locked'
```

Keep the printed `previous` value. Take a dump, run `jdr-bot-migrate.service` if the new checkout changes the schema, then start `jdr-bot.service`. Deploy a commit you can name. Do not leave the checkout on an unrecorded local edit.

Rollback when the new process fails before a migration has been applied: set `previous` to the SHA printed above, check out that SHA, run `uv sync --locked`, and start the service.

```sh
previous=${previous:?set previous to the SHA recorded before the upgrade}
sudo systemctl stop jdr-bot.service
sudo -u jdrbot -H git -C /opt/jdr-bot checkout "$previous"
sudo -u jdrbot -H bash -c 'cd /opt/jdr-bot && uv sync --locked'
sudo systemctl start jdr-bot.service
```

Rollback when a migration has been applied: stop the bot, restore the dump taken before the migration, check out that same `previous` SHA, `uv sync --locked`, and start. That dump is deleted before it is 7 days old, with every other dump, under [decision 0007](../decisions/0007-meeting-data-retention.md). A restore is not a way to keep meeting-capture content past its deletion deadline.

```sh
previous=${previous:?set previous to the SHA recorded before the upgrade}
stamp=${stamp:?set stamp to the UTC stamp in the dump filename}
sudo systemctl stop jdr-bot.service
sudo -u postgres psql --cluster 16/main -d postgres -c 'DROP DATABASE jdr_bot;'
sudo -u postgres psql --cluster 16/main -d postgres -c 'CREATE DATABASE jdr_bot OWNER jdr_bot;'
sudo -u postgres pg_restore --cluster 16/main --dbname=jdr_bot "/var/backups/jdr/jdr_bot-${stamp}.dump"
sudo -u postgres psql --cluster 16/main -d jdr_bot -c 'SELECT version_num FROM alembic_version;'
```

`version_num` must match the dump before the next block. `DROP DATABASE` destroys the current rows. Use it only to replace them with the dump you just verified. The checkout is `previous`, the SHA recorded before the upgrade.

```sh
previous=${previous:?set previous to the SHA recorded before the upgrade}
sudo -u jdrbot -H git -C /opt/jdr-bot checkout "$previous"
sudo -u jdrbot -H bash -c 'cd /opt/jdr-bot && uv sync --locked'
sudo systemctl start jdr-bot.service
```

## Gateway and voice checks

Follow [verification on the Pi](../decisions/0006-raspberry-pi-hosting.md#verification-on-the-pi). Outbound TLS to `gateway.discord.gg:443` and `GET https://discord.com/api/v10/gateway` are the reachability checks. They are not a gateway session.

The session check is the current service invocation. `systemctl is-active jdr-bot.service` must print `active`. Then:

```sh
sudo journalctl -u jdr-bot.service \
  _SYSTEMD_INVOCATION_ID="$(systemctl show -p InvocationID --value jdr-bot.service)" \
  --no-pager
```

`_SYSTEMD_INVOCATION_ID` is this start only. An unbounded `journalctl -u jdr-bot`, or `-b` alone, mixes earlier boots and earlier starts. This invocation must include a `discord.gateway` line containing `has connected to Gateway`. discord.py 2.7.1 writes `Shard ID %s has connected to Gateway (Session ID: %s).` from `discord/gateway.py` when the WebSocket receives READY. The same invocation must not include `discord_login_failed`. Do not copy the session id into a chat or an issue.

`guild_commands_registered` is logged from `setup_hook` during HTTP login, before `Client.connect`. `on_ready` does not log a ready line of its own, and `scheduler_started` is logged from `setup_hook` before the socket opens. Neither line is the session check. The Discord smoke check in [development instructions](../DEVELOPMENT.md) is the operator-visible half: the bot shows online and answers the slash command. Voice UDP stays pending until a voice-capable build receives a UDP discovery reply on this network. Do not treat a successful HTTPS check as a voice result.

When the brief is enabled, confirm the Jira host answers TLS without sending the token:

```sh
curl --silent --output /dev/null --show-error --max-time 20 \
  --write-out '%{http_code}\n' "https://<site>.atlassian.net/"
```

Any HTTP status means TCP 443 reached that host. A timeout or a DNS error means it did not. The status is not a successful brief. The brief smoke check in [development instructions](../DEVELOPMENT.md) is still a separate live test.
