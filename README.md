# Nginx Log Analyzer

**[Македонски](#македонски)** · **[English](#english)**

Анализатор на Nginx `access` и `error` логови. Покажува која IP каде одела и што правела, плус детални грешки по страна и апликација.

Nginx access/error log analyzer. Shows which IP went where and what it did, plus a detailed error breakdown per site and upstream app.

---

# Македонски

Анализатор на Nginx `access` и `error` логови. Покажува **која IP каде одела и што правела**, плус детални грешки по страна, патека и upstream апликација.

Работи само со Python стандардна библиотека. Ги чита тековните логови и ротираните `.gz` датотеки. Извештаите се на македонски.

## Можности

- Парсер за `combined` access формат, со пофлексибилен fallback
- Парсер за error лог што вади `client`, `server`, `request`, `host`, `upstream`
- По IP: прво/последно барање, бајти, методи, статуси, патеки
- Сообраќај по ден, најбарани патеки, распределба на статус кодови
- Ознака за типични скенери / експлойти (`.env`, `wp-login.php`, `.git`, phpMyAdmin, …)
- Текстуален извештај за терминал и самостоен HTML извештај
- Дневна автоматизација преку cron или systemd timer
- Опционална `logs` команда за zsh

## Барања

- Python 3.8+
- Без дополнителни пакети
- Право на читање на `/var/log/nginx/` (обично `sudo`, или група `adm`)

Очекуван access формат (nginx `combined`):

```
$remote_addr - $remote_user [$time_local] "$request" $status $body_bytes_sent "$http_referer" "$http_user_agent"
```

## Структура на проектот

```
.
├── nginx_log_analyzer.py    # главен анализатор
├── nginx-daily-report.sh    # дневен wrapper (датирани извештаи + чистење)
├── nginx-report.service     # systemd oneshot
├── nginx-report.timer       # секој ден во 00:20
├── nginx-logs.zsh           # zsh помошник: logs, logs f, logs report
├── install.sh               # преносна инсталација за повеќе дистрибуции
├── LICENSE
└── README.md
```

## Поддржани дистрибуции

Скриптата е чист Python 3 (стандардна библиотека) и работи насекаде каде има `python3`:

- Debian, Ubuntu, Linux Mint
- Fedora, RHEL, CentOS, Rocky, AlmaLinux, Amazon Linux
- Arch Linux, Manjaro
- openSUSE Leap / Tumbleweed
- Alpine
- Nginx/OpenResty инсталиран од source (`/usr/local/nginx/logs`, `/opt/nginx/logs`)

Ако `access.log` не е во `/var/log/nginx`, анализаторот сам ги пробува вообичаените патеки. Инаку: `--dir /патека`.

Ги препознава и имињата `access.log`, `access_log`, `nginx-access.log` (исто за error).

## Инсталација

Препорачано (сите дистрибуции):

```bash
sudo ./install.sh
```

`install.sh` ги копира датотеките во `/usr/local/bin`, ги става systemd unit-ите ако постојат и кажува која група да ја користиш за дозволи.

Рачно:

```bash
sudo cp nginx_log_analyzer.py nginx-daily-report.sh /usr/local/bin/
sudo cp nginx-logs.zsh /usr/local/bin/
sudo chmod 755 /usr/local/bin/nginx_log_analyzer.py /usr/local/bin/nginx-daily-report.sh
sudo mkdir -p /var/log/nginx-reports
```

Брза проверка:

```bash
sudo python3 /usr/local/bin/nginx_log_analyzer.py --current-only
```

## Примери за конфигурација

### 1. Nginx — препорачан `combined` формат

Анализаторот очекува стандарден `combined` ред. Во `/etc/nginx/nginx.conf` (во блокот `http`):

```nginx
http {
    log_format combined '$remote_addr - $remote_user [$time_local] '
                        '"$request" $status $body_bytes_sent '
                        '"$http_referer" "$http_user_agent"';

    access_log /var/log/nginx/access.log combined;
    error_log  /var/log/nginx/error.log warn;

    # ...
}
```

По промена:

```bash
sudo nginx -t && sudo systemctl reload nginx
```

### 2. Посебен лог по страна / апликација

Ако имаш повеќе сајтови, секој `server` може да пишува во своја датотека. Анализаторот чита сè што почнува со `access.log` / `error.log` во истиот директориум, **или** пушти го со `-d` на конкретна папка.

```nginx
# /etc/nginx/sites-available/app.example.com
server {
    listen 443 ssl;
    server_name app.example.com;

    access_log /var/log/nginx/access.log combined;
    error_log  /var/log/nginx/error.log warn;

    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Засебни логови по апликација:

```nginx
server {
    server_name api.example.com;
    access_log /var/log/nginx/api.access.log combined;
    error_log  /var/log/nginx/api.error.log warn;
    # ...
}
```

Засебните имиња (`api.access.log`) **не** се детектираат автоматски. Или држи го стандардното `access.log` / `error.log`, или копирај/симлинкувај ги во посебен директориум и повикај:

```bash
sudo python3 nginx_log_analyzer.py -d /var/log/nginx-api
```

Покорисен пристап: остави ги сите сајтови во истиот `access.log` — `host` / `server` од error логот и патеките ќе ги разделат апликациите во извештајот.

### 3. Побогат access формат (дополнителни полиња на крај)

Парсерот го игнорира она што доаѓа **после** combined полињата. Безбедно е да додадеш `$request_time`, `$upstream_addr` и сл. на крај:

```nginx
log_format combined_ext '$remote_addr - $remote_user [$time_local] '
                        '"$request" $status $body_bytes_sent '
                        '"$http_referer" "$http_user_agent" '
                        'rt=$request_time ua=$upstream_addr';

access_log /var/log/nginx/access.log combined_ext;
```

Ако го смениш редоследот на полињата (на пр. JSON лог), стандардниот парсер нема да ги препознае редовите.

### 4. `logrotate` за Nginx

Пример `/etc/logrotate.d/nginx`:

```
/var/log/nginx/*.log {
    daily
    missingok
    rotate 14
    compress
    delaycompress
    notifempty
    create 0640 www-data adm
    # Fedora/RHEL/Arch/SUSE:  create 0640 nginx nginx
    # Arch (http user):       create 0640 http http
    sharedscripts
    postrotate
        if [ -f /run/nginx.pid ]; then
            kill -USR1 "$(cat /run/nginx.pid)"
        fi
        # опционално: извештај веднаш после ротација
        # /usr/local/bin/nginx-daily-report.sh
    endscript
}
```

`delaycompress` го остава `access.log.1` некомпресиран еден ден — анализаторот ги чита и `.1` и `.gz`.

### 5. Променливи за `nginx-daily-report.sh`

| Променлива | Стандардно | Опис |
|---|---|---|
| `ANALYZER` | `/usr/local/bin/nginx_log_analyzer.py` | Патека до Python скриптата |
| `LOG_DIR` | `/var/log/nginx` | Директориум со логови |
| `REPORT_DIR` | `/var/log/nginx-reports` | Каде се чуваат извештаите |
| `KEEP_DAYS` | `30` | По колку дена се бришат старите извештаи |
| `MAIL_TO` | празно | Е-пошта; празно = без праќање |
| `TOP_IPS` | `40` | Колку IP во извештајот |
| `PATHS_PER_IP` | `25` | Колку патеки по IP |

Пример рачно:

```bash
sudo env \
  LOG_DIR=/var/log/nginx \
  REPORT_DIR=/var/log/nginx-reports \
  KEEP_DAYS=14 \
  TOP_IPS=50 \
  PATHS_PER_IP=30 \
  MAIL_TO=admin@example.com \
  /usr/local/bin/nginx-daily-report.sh
```

Пример во `crontab`:

```cron
MAIL_TO=admin@example.com
TOP_IPS=50
KEEP_DAYS=14
20 0 * * * /usr/local/bin/nginx-daily-report.sh >/var/log/nginx-reports/cron.log 2>&1
```

### 6. systemd drop-in (без менување на unit датотеката)

```bash
sudo systemctl edit nginx-report.service
```

```ini
[Service]
Environment=KEEP_DAYS=14
Environment=TOP_IPS=50
Environment=PATHS_PER_IP=30
Environment=MAIL_TO=admin@example.com
Environment=REPORT_DIR=/var/log/nginx-reports
```

Потоа:

```bash
sudo systemctl daemon-reload
sudo systemctl start nginx-report.service
```

### 7. zsh / `.zshrc`

```zsh
# патеки ако не ги инсталираш во /usr/local/bin
export NGINX_ANALYZER="$HOME/src/nginx-log-analyzer/nginx_log_analyzer.py"
export NGINX_LOG_DIR="/var/log/nginx"
export NGINX_TOP_IPS=20
export PAGER="less"

source /usr/local/bin/nginx-logs.zsh
# или: source "$HOME/src/nginx-log-analyzer/nginx-logs.zsh"
```

### 8. Преглед на HTML извештајот преку Nginx (basic auth)

```bash
# Debian/Ubuntu:     sudo apt-get install -y apache2-utils
# Fedora/RHEL:       sudo dnf install -y httpd-tools
# Arch:              sudo pacman -S --needed apache
# openSUSE:          sudo zypper install apache2-utils
# Alpine:            sudo apk add apache2-utils

sudo htpasswd -c /etc/nginx/.htpasswd-reports admin
sudo chmod 640 /etc/nginx/.htpasswd-reports
# Nginx group: www-data (Debian), nginx (RHEL/SUSE), http (Arch)
sudo chown root:www-data /etc/nginx/.htpasswd-reports
```

```nginx
server {
    listen 443 ssl;
    server_name reports.example.com;

    root /var/log/nginx-reports;
    autoindex on;

    auth_basic "Nginx reports";
    auth_basic_user_file /etc/nginx/.htpasswd-reports;

    location / {
        default_type text/html;
    }
}
```

Отвори `https://reports.example.com/latest.html`. Не го прави овој location јавен без лозинка — извештаите содржат IP адреси и патеки.

## Употреба

```bash
# полн извештај во терминал (тековни + ротирани + .gz)
sudo python3 nginx_log_analyzer.py

# само денешните access.log / error.log
sudo python3 nginx_log_analyzer.py --current-only

# топ 50 IP, повеќе патеки по IP, зачувај датотеки
sudo python3 nginx_log_analyzer.py -n 50 -p 40 \
  -o /tmp/nginx-report.txt \
  --html /tmp/nginx-report.html

# само грешки
sudo python3 nginx_log_analyzer.py --error-only

# најнови 2 датотеки по тип (access.log + access.log.1, …)
sudo python3 nginx_log_analyzer.py --max-files 2
```

### CLI опции

| Опција | Стандардно | Опис |
|---|---|---|
| `-d`, `--dir` | `/var/log/nginx` | Директориум со логови |
| `-n`, `--top-ips` | `30` | Колку IP да се прикажат детално |
| `-p`, `--paths-per-ip` | `20` | Колку патеки по IP |
| `--access-only` | | Без error логови |
| `--error-only` | | Без access логови |
| `--current-only` | | Само `access.log` и `error.log` |
| `--max-files N` | `0` (сите) | Ограничи датотеки по тип, најнови прво |
| `-o`, `--output` | stdout | Зачувај текстуален извештај |
| `--html PATH` | | Зачувај HTML извештај |
| `-q`, `--quiet` | | Без прогрес (за cron) |

HTML датотеката отвори ја во прелистувач. Текстуалниот извештај е UTF-8 и е за терминал / `less`.

## zsh помошник (`logs`)

Ако користиш zsh, вчитај го помошникот од `~/.zshrc`:

```bash
sudo cp nginx-logs.zsh /usr/local/bin/nginx-logs.zsh
```

```zsh
# ~/.zshrc
source /usr/local/bin/nginx-logs.zsh
# ако анализаторот не е во /usr/local/bin:
# export NGINX_ANALYZER="$HOME/src/nginx-log-analyzer/nginx_log_analyzer.py"
```

Превчитај:

```bash
source ~/.zshrc
```

| Команда | Што прави |
|---|---|
| `logs` | Го отвора `access.log` во `less` (скока на крај) |
| `logs e` | `error.log` |
| `logs f` | Live follow на access + error (`tail -F`) |
| `logs fa` / `logs fe` | Live само access или само error |
| `logs today` | Анализа само на тековните логови |
| `logs report` | Полна анализа, низ `less` |
| `logs last` | Последниот зачуван дневен извештај |
| `logs grep wp-login` | Пребарување низ access логови |
| `logs help` | Листа на команди |

Функцијата сама повикува `sudo` кога датотеките не се читливи за тековниот корисник.

Во `less`: `q` излез, `/текст` пребарување, `G` крај, `g` почеток.

## Автоматски дневни извештаи

Извештаите се запишуваат во `/var/log/nginx-reports/`:

- `nginx-report-YYYY-MM-DD.txt`
- `nginx-report-YYYY-MM-DD.html`
- симболички линкови `latest.txt` / `latest.html`
- датотеки постари од 30 дена се бришат (`KEEP_DAYS`)

Пушти еднаш после logrotate (кај Nginx ротацијата често е околу 00:10):

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

Испрати го текстуалниот извештај на е-пошта (треба `mail`/`mailx` и локален MTA):

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

Тајмерот се пали секој ден во **00:20**. `Persistent=true` ќе ја изврши пропуштената задача после рестарт.

```bash
sudo systemctl start nginx-report.service
journalctl -u nginx-report.service -n 30
```

За е-пошта, откоментирај во service датотеката:

```ini
Environment=MAIL_TO=admin@example.com
```

### logrotate hook

Наместо cron/timer, извештајот може да се генерира веднаш после ротација. Во `/etc/logrotate.d/nginx`:

```
postrotate
    /usr/local/bin/nginx-daily-report.sh
endscript
```

Избери **или** cron/systemd **или** logrotate hook, не обајцата во иста минута.

## Што содржи извештајот

**Access**

- број на барања, уникатни IP и патеки
- сообраќај по ден
- методи и статус кодови
- најбарани патеки и User-Agent
- за секоја топ IP: посетени патеки, методи, статуси, бајти, прво/последно, User-Agent, referer
- локалните/LAN IP се означени
- примерок од сомнителни барања

**Error**

- број по ниво (`error`, `warn`, `crit`, …)
- грешки по `host` / `server_name` (виртуелен хост / страна)
- грешки по патека
- грешки по `upstream` (backend апликацијата зад Nginx)
- грешки по клиентска IP
- групирани/нормализирани пораки
- сурови примероци

Празен `error.log` е нормален веднаш после ротација. Постарите `error.log.1` и `error.log.N.gz` сепак се читаат, освен ако не дадеш `--current-only`.

## Дозволи

Логовите обично се `640` и не се читливи за обичен корисник. Сопственикот зависи од дистрибуцијата:

| Дистрибуција | Корисник | Група | Патека |
|---|---|---|---|
| Debian, Ubuntu | `www-data` | `adm` | `/var/log/nginx` |
| Fedora, RHEL, Rocky, Alma | `nginx` | `nginx` | `/var/log/nginx` |
| Arch | `http` или `nginx` | `http` / `nginx` | `/var/log/nginx` |
| openSUSE | `nginx` | `nginx` | `/var/log/nginx` |
| Alpine | `nginx` | `nginx` | `/var/log/nginx` |
| Source / OpenResty | зависи | зависи | `/usr/local/nginx/logs` и сл. |

Најбезбедно: пушти го анализаторот со `sudo` / root.

Или додај се во групата што ги чита логовите (провери со `ls -l /var/log/nginx`):

```bash
# Debian/Ubuntu
sudo usermod -aG adm "$USER"

# Fedora / RHEL фамилија / SUSE / многу други
sudo usermod -aG nginx "$USER"

# Arch
sudo usermod -aG http "$USER"

# Alpine
sudo adduser "$USER" nginx
```

Потоа одјави се и најави се повторно.

## Лиценца

MIT — користи, форкни, менувај.

---

# English

Parse Nginx `access` and `error` logs and produce a terminal + HTML report:

- which IP visited which paths
- HTTP methods, status codes, user-agents, referrers
- suspicious scanner / exploit probes
- error-log breakdown by host, URI, and upstream backend

Uses the Python standard library only. Reads live logs and rotated `.gz` files. Report text is in Macedonian.

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
├── nginx-logs.zsh           # zsh helper: logs, logs f, logs report
├── install.sh               # portable installer for multiple distros
├── LICENSE
└── README.md
```

## Supported distributions

The analyzer is plain Python 3 (stdlib only) and runs anywhere `python3` exists:

- Debian, Ubuntu, Linux Mint
- Fedora, RHEL, CentOS, Rocky, AlmaLinux, Amazon Linux
- Arch Linux, Manjaro
- openSUSE Leap / Tumbleweed
- Alpine
- Nginx/OpenResty built from source (`/usr/local/nginx/logs`, `/opt/nginx/logs`)

If `access.log` is not in `/var/log/nginx`, the analyzer tries the usual locations. Otherwise pass `--dir /path`.

It also recognizes `access.log`, `access_log`, and `nginx-access.log` (same for error logs).

## Install

Recommended (all distros):

```bash
sudo ./install.sh
```

`install.sh` copies files to `/usr/local/bin`, installs the systemd units when systemd is present, and prints the correct log-file group for your OS.

Manual:

```bash
sudo cp nginx_log_analyzer.py nginx-daily-report.sh /usr/local/bin/
sudo cp nginx-logs.zsh /usr/local/bin/
sudo chmod 755 /usr/local/bin/nginx_log_analyzer.py /usr/local/bin/nginx-daily-report.sh
sudo mkdir -p /var/log/nginx-reports
```

Quick test:

```bash
sudo python3 /usr/local/bin/nginx_log_analyzer.py --current-only
```

## Configuration examples

### 1. Nginx — recommended `combined` format

The analyzer expects a standard `combined` line. In `/etc/nginx/nginx.conf` (inside the `http` block):

```nginx
http {
    log_format combined '$remote_addr - $remote_user [$time_local] '
                        '"$request" $status $body_bytes_sent '
                        '"$http_referer" "$http_user_agent"';

    access_log /var/log/nginx/access.log combined;
    error_log  /var/log/nginx/error.log warn;

    # ...
}
```

After changing the config:

```bash
sudo nginx -t && sudo systemctl reload nginx
```

### 2. Separate log per site / app

Each `server` block can write its own files. The analyzer picks up anything named `access.log*` / `error.log*` in the same directory, **or** you can point `-d` at a dedicated folder.

```nginx
# /etc/nginx/sites-available/app.example.com
server {
    listen 443 ssl;
    server_name app.example.com;

    access_log /var/log/nginx/access.log combined;
    error_log  /var/log/nginx/error.log warn;

    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Per-app files:

```nginx
server {
    server_name api.example.com;
    access_log /var/log/nginx/api.access.log combined;
    error_log  /var/log/nginx/api.error.log warn;
    # ...
}
```

Custom names such as `api.access.log` are **not** auto-discovered. Keep the default `access.log` / `error.log` names, or put copies/symlinks in a dedicated directory:

```bash
sudo python3 nginx_log_analyzer.py -d /var/log/nginx-api
```

Usually it is better to keep every site in the shared `access.log` — error-log `host` / `server` fields and request paths already split apps in the report.

### 3. Richer access format (extra fields at the end)

The parser ignores anything **after** the combined fields. You can append `$request_time`, `$upstream_addr`, and similar:

```nginx
log_format combined_ext '$remote_addr - $remote_user [$time_local] '
                        '"$request" $status $body_bytes_sent '
                        '"$http_referer" "$http_user_agent" '
                        'rt=$request_time ua=$upstream_addr';

access_log /var/log/nginx/access.log combined_ext;
```

If you reorder fields (for example JSON logging), the default parser will not recognize the lines.

### 4. Nginx `logrotate`

Example `/etc/logrotate.d/nginx`:

```
/var/log/nginx/*.log {
    daily
    missingok
    rotate 14
    compress
    delaycompress
    notifempty
    create 0640 www-data adm
    # Fedora/RHEL/Arch/SUSE:  create 0640 nginx nginx
    # Arch (http user):       create 0640 http http
    sharedscripts
    postrotate
        if [ -f /run/nginx.pid ]; then
            kill -USR1 "$(cat /run/nginx.pid)"
        fi
        # optional: generate a report right after rotation
        # /usr/local/bin/nginx-daily-report.sh
    endscript
}
```

`delaycompress` leaves `access.log.1` uncompressed for one day — the analyzer reads both `.1` and `.gz`.

### 5. Environment variables for `nginx-daily-report.sh`

| Variable | Default | Meaning |
|---|---|---|
| `ANALYZER` | `/usr/local/bin/nginx_log_analyzer.py` | Path to the Python script |
| `LOG_DIR` | `/var/log/nginx` | Log directory |
| `REPORT_DIR` | `/var/log/nginx-reports` | Where reports are stored |
| `KEEP_DAYS` | `30` | Delete reports older than this |
| `MAIL_TO` | empty | Email recipient; empty = no mail |
| `TOP_IPS` | `40` | How many IPs in the report |
| `PATHS_PER_IP` | `25` | How many paths per IP |

Manual run:

```bash
sudo env \
  LOG_DIR=/var/log/nginx \
  REPORT_DIR=/var/log/nginx-reports \
  KEEP_DAYS=14 \
  TOP_IPS=50 \
  PATHS_PER_IP=30 \
  MAIL_TO=admin@example.com \
  /usr/local/bin/nginx-daily-report.sh
```

`crontab` example:

```cron
MAIL_TO=admin@example.com
TOP_IPS=50
KEEP_DAYS=14
20 0 * * * /usr/local/bin/nginx-daily-report.sh >/var/log/nginx-reports/cron.log 2>&1
```

### 6. systemd drop-in (leave the unit file untouched)

```bash
sudo systemctl edit nginx-report.service
```

```ini
[Service]
Environment=KEEP_DAYS=14
Environment=TOP_IPS=50
Environment=PATHS_PER_IP=30
Environment=MAIL_TO=admin@example.com
Environment=REPORT_DIR=/var/log/nginx-reports
```

Then:

```bash
sudo systemctl daemon-reload
sudo systemctl start nginx-report.service
```

### 7. zsh / `.zshrc`

```zsh
# paths if you do not install into /usr/local/bin
export NGINX_ANALYZER="$HOME/src/nginx-log-analyzer/nginx_log_analyzer.py"
export NGINX_LOG_DIR="/var/log/nginx"
export NGINX_TOP_IPS=20
export PAGER="less"

source /usr/local/bin/nginx-logs.zsh
# or: source "$HOME/src/nginx-log-analyzer/nginx-logs.zsh"
```

### 8. Serve the HTML report through Nginx (basic auth)

```bash
# Debian/Ubuntu:     sudo apt-get install -y apache2-utils
# Fedora/RHEL:       sudo dnf install -y httpd-tools
# Arch:              sudo pacman -S --needed apache
# openSUSE:          sudo zypper install apache2-utils
# Alpine:            sudo apk add apache2-utils

sudo htpasswd -c /etc/nginx/.htpasswd-reports admin
sudo chmod 640 /etc/nginx/.htpasswd-reports
# Nginx group: www-data (Debian), nginx (RHEL/SUSE), http (Arch)
sudo chown root:www-data /etc/nginx/.htpasswd-reports
```

```nginx
server {
    listen 443 ssl;
    server_name reports.example.com;

    root /var/log/nginx-reports;
    autoindex on;

    auth_basic "Nginx reports";
    auth_basic_user_file /etc/nginx/.htpasswd-reports;

    location / {
        default_type text/html;
    }
}
```

Open `https://reports.example.com/latest.html`. Do not expose this location without a password — reports contain client IPs and request paths.

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

In `less`: `q` quit, `/text` search, `G` end, `g` start.

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

Log files are usually mode `640` and not world-readable. The owner depends on the distro:

| Distro | User | Group | Path |
|---|---|---|---|
| Debian, Ubuntu | `www-data` | `adm` | `/var/log/nginx` |
| Fedora, RHEL, Rocky, Alma | `nginx` | `nginx` | `/var/log/nginx` |
| Arch | `http` or `nginx` | `http` / `nginx` | `/var/log/nginx` |
| openSUSE | `nginx` | `nginx` | `/var/log/nginx` |
| Alpine | `nginx` | `nginx` | `/var/log/nginx` |
| Source / OpenResty | varies | varies | `/usr/local/nginx/logs`, etc. |

Safest option: run the analyzer with `sudo` / as root.

Or add yourself to the group that can read the logs (check with `ls -l /var/log/nginx`):

```bash
# Debian/Ubuntu
sudo usermod -aG adm "$USER"

# Fedora / RHEL family / SUSE / many others
sudo usermod -aG nginx "$USER"

# Arch
sudo usermod -aG http "$USER"

# Alpine
sudo adduser "$USER" nginx
```

Then log out and back in.

## License

MIT — use it, fork it, change it.
