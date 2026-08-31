# Nginx Log Analyzer

Анализатор на Nginx `access` и `error` логови. Покажува **која IP каде одела и што правела**, плус детални грешки по страна, патека и upstream апликација.

Работи само со Python стандардна библиотека. Ги чита тековните логови и ротираните `.gz` датотеки.

---

Parse Nginx access/error logs (including rotated `.gz` files) and produce a terminal + HTML report:

- which IP visited which paths
- HTTP methods, status codes, user-agents, referrers
- suspicious scanner / exploit probes
- error-log breakdown by host, URI, and upstream backend

## Features

- Combined-format access log parser with a looser fallback
- Error log parser that extracts `client`, `server`, `request`, `host`, `upstream`
- Per-IP timeline: first/last seen, bytes, methods, statuses, paths
- Daily traffic, top paths, status distribution
- Heuristic flags for common probe paths (`.env`, `wp-login.php`, `.git`, phpMyAdmin, …)
- Text report for the terminal and a self-contained HTML report
- Daily automation via cron or systemd timer
- Optional `logs` helper for zsh

## Requirements

- Python 3.8+
- No third-party packages
- Permission to read `/var/log/nginx/` (usually `sudo`, or membership in the `adm` group)

Expected access log format (nginx `combined`):

```
$remote_addr - $remote_user [$time_local] "$request" $status $body_bytes_sent "$http_referer" "$http_user_agent"
```

## Project layout

```
.
├── nginx_log_analyzer.py    # main analyzer
├── nginx-daily-report.sh    # daily wrapper (dated reports + cleanup)
├── nginx-report.service     # systemd oneshot
├── nginx-report.timer       # run every day at 00:20
├── nginx-logs.zsh           # zsh helper: `logs`, `logs f`, `logs report`
└── README.md
```

## Install

```bash
sudo cp nginx_log_analyzer.py /usr/local/bin/nginx_log_analyzer.py
sudo cp nginx-daily-report.sh /usr/local/bin/nginx-daily-report.sh
sudo chmod 755 /usr/local/bin/nginx_log_analyzer.py /usr/local/bin/nginx-daily-report.sh
sudo mkdir -p /var/log/nginx-reports
```

Quick test:

```bash
sudo python3 /usr/local/bin/nginx_log_analyzer.py --current-only
```

## Usage

```bash
# full report in the terminal (current + rotated + .gz)
sudo python3 nginx_log_analyzer.py

# only today's access.log / error.log
sudo python3 nginx_log_analyzer.py --current-only

# top 50 IPs, more paths per IP, save files
sudo python3 nginx_log_analyzer.py -n 50 -p 40 \
  -o /tmp/nginx-report.txt \
  --html /tmp/nginx-report.html

# errors only
sudo python3 nginx_log_analyzer.py --error-only

# newest 2 files per type (access.log + access.log.1, etc.)
sudo python3 nginx_log_analyzer.py --max-files 2
```

### CLI flags

| Flag | Default | Description |
|---|---|---|
| `-d`, `--dir` | `/var/log/nginx` | Log directory |
| `-n`, `--top-ips` | `30` | How many IPs to expand |
| `-p`, `--paths-per-ip` | `20` | How many paths to list per IP |
| `--access-only` | | Skip error logs |
| `--error-only` | | Skip access logs |
| `--current-only` | | Only `access.log` and `error.log` |
| `--max-files N` | `0` (all) | Cap files per type, newest first |
| `-o`, `--output` | stdout | Write text report to a file |
| `--html PATH` | | Write HTML report |
| `-q`, `--quiet` | | No progress lines (for cron) |

Open the HTML file in a browser. The text report is UTF-8 and intended for a terminal / `less`.

## zsh helper (`logs`)

If you use zsh, source the helper from `~/.zshrc`:

```bash
sudo cp nginx-logs.zsh /usr/local/bin/nginx-logs.zsh
```

```zsh
# ~/.zshrc
source /usr/local/bin/nginx-logs.zsh
# optional, if the analyzer is not in /usr/local/bin:
# export NGINX_ANALYZER="$HOME/src/nginx-log-analyzer/nginx_log_analyzer.py"
```

Reload:

```bash
source ~/.zshrc
```

| Command | Action |
|---|---|
| `logs` | Open `access.log` in `less` (jump to end) |
| `logs e` | Open `error.log` |
| `logs f` | Follow access + error (`tail -F`) |
| `logs fa` / `logs fe` | Follow only access or only error |
| `logs today` | Analyze current logs only |
| `logs report` | Full analysis, piped to `less` |
| `logs last` | Last saved daily report |
| `logs grep wp-login` | Search access logs |
| `logs help` | Command list |

The function calls `sudo` automatically when the files are not readable by your user.

## Automate daily reports

Reports are written to `/var/log/nginx-reports/`:

- `nginx-report-YYYY-MM-DD.txt`
- `nginx-report-YYYY-MM-DD.html`
- `latest.txt` / `latest.html` symlinks
- files older than 30 days are deleted (`KEEP_DAYS`)

Run it once after logrotate (typical nginx rotate time is ~00:10):

```bash
sudo /usr/local/bin/nginx-daily-report.sh
```

### cron

```bash
sudo crontab -e
```

```cron
20 0 * * * /usr/local/bin/nginx-daily-report.sh >/var/log/nginx-reports/cron.log 2>&1
```

Email the text report (requires `mail`/`mailx` and a local MTA):

```cron
20 0 * * * MAIL_TO=admin@example.com /usr/local/bin/nginx-daily-report.sh
```

### systemd timer

```bash
sudo cp nginx-report.service nginx-report.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now nginx-report.timer
systemctl list-timers | grep nginx
```

The timer fires daily at **00:20**. `Persistent=true` runs a missed job after boot.

```bash
sudo systemctl start nginx-report.service
journalctl -u nginx-report.service -n 30
```

To enable mail, uncomment in the service file:

```ini
Environment=MAIL_TO=admin@example.com
```

### logrotate hook

Instead of cron/timer, you can generate a report right after rotation. In `/etc/logrotate.d/nginx`:

```
postrotate
    /usr/local/bin/nginx-daily-report.sh
endscript
```

Pick **either** cron/systemd **or** the logrotate hook, not both at the same minute.

## What the report contains

**Access**

- request counts, unique IPs and paths
- traffic per day
- methods and status codes
- top paths and user-agents
- for each top IP: paths hit, methods, statuses, bytes, first/last seen, user-agent, referrer
- private/LAN IPs are marked
- sample of suspicious requests

**Error**

- counts by level (`error`, `warn`, `crit`, …)
- errors by `host` / `server_name` (vhost / site)
- errors by request path
- errors by `upstream` (the backend app Nginx proxies to)
- errors by client IP
- normalized message groups
- raw sample lines

Empty `error.log` is normal right after rotation; older `error.log.1` and `error.log.N.gz` are still parsed unless you pass `--current-only`.

## Permissions

Typical Debian/Ubuntu layout:

```
-rw-r-----  www-data adm  /var/log/nginx/access.log
```

Run the analyzer as root, or add your user to `adm`:

```bash
sudo usermod -aG adm "$USER"
```

Then log out and back in.

## License

MIT — use it, fork it, change it.
