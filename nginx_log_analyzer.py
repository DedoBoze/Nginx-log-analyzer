#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Nginx Log Analyzer
Чита access и error логови од /var/log/nginx/ (вклучувајќи ротирани .gz)
и прикажува која IP каде одела и што правела, плус детална анализа на грешки.
"""

from __future__ import annotations

import argparse
import gzip
import html
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, TextIO

# ---------------------------------------------------------------------------
# Конфигурација
# ---------------------------------------------------------------------------

DEFAULT_LOG_DIR = "/var/log/nginx"
DEFAULT_TOP_IPS = 30
DEFAULT_PATHS_PER_IP = 20

# Чести локации по дистрибуција / начин на инсталација
LOG_DIR_CANDIDATES = [
    "/var/log/nginx",                 # Debian, Ubuntu, Fedora, RHEL, Arch, SUSE, Alpine
    "/usr/local/nginx/logs",          # инсталација од source
    "/opt/nginx/logs",
    "/usr/local/openresty/nginx/logs",
    "/var/log/openresty",
    "/usr/local/etc/nginx/logs",
]

# Combined / common access log
# 1.2.3.4 - - [31/Aug/2026:00:32:10 +0200] "GET /path HTTP/1.1" 200 1234 "ref" "ua"
ACCESS_RE = re.compile(
    r"^(?P<ip>\S+)\s+\S+\s+\S+\s+\[(?P<time>[^\]]+)\]\s+"
    r'"(?P<method>\S+)\s+(?P<path>\S+)(?:\s+(?P<proto>[^"]*))?"\s+'
    r"(?P<status>\d{3})\s+(?P<size>\S+)"
    r'(?:\s+"(?P<referer>[^"]*)"\s+"(?P<ua>[^"]*)")?'
    r"(?:\s+(?P<extra>.*))?$"
)

# Пофлексибилен fallback ако форматот е малку различен
ACCESS_LOOSE_RE = re.compile(
    r"^(?P<ip>\d{1,3}(?:\.\d{1,3}){3}|[0-9a-fA-F:]+)\s+"
    r".*\[(?P<time>[^\]]+)\].*"
    r'"(?P<method>GET|POST|PUT|DELETE|HEAD|OPTIONS|PATCH|PROPFIND|CONNECT)\s+'
    r'(?P<path>\S+)[^"]*"\s+(?P<status>\d{3})'
)

# Nginx error log
# 2026/08/30 22:00:11 [error] 1234#1234: *55 message, client: 1.2.3.4, ...
ERROR_RE = re.compile(
    r"^(?P<time>\d{4}/\d{2}/\d{2}\s+\d{2}:\d{2}:\d{2})\s+"
    r"\[(?P<level>\w+)\]\s+(?P<pid>\d+)#(?P<tid>\d+):\s+"
    r"(?:\*(?P<cid>\d+)\s+)?(?P<message>.*)$"
)

ERROR_CLIENT_RE = re.compile(r"client:\s*(?P<ip>\S+?)(?:,|$)")
ERROR_SERVER_RE = re.compile(r"server:\s*(?P<server>\S+?)(?:,|$)")
ERROR_REQUEST_RE = re.compile(r'request:\s*"(?P<method>\S+)\s+(?P<path>\S+)[^"]*"')
ERROR_HOST_RE = re.compile(r'host:\s*"(?P<host>[^"]+)"')
ERROR_UPSTREAM_RE = re.compile(r"upstream:\s*\"(?P<upstream>[^\"]+)\"")
ERROR_REFERRER_RE = re.compile(r'referrer:\s*"(?P<referrer>[^"]*)"')

SUSPICIOUS_PATH_PATTERNS = [
    r"wp-admin",
    r"wp-login",
    r"xmlrpc\.php",
    r"\.env",
    r"\.git",
    r"phpmyadmin",
    r"pma",
    r"/admin",
    r"wp-content",
    r"\.php$",
    r"eval-stdin",
    r"shell",
    r"cmd=",
    r"passwd",
    r"etc/shadow",
    r"actuator",
    r"\.aws",
    r"vendor/phpunit",
    r"cgi-bin",
    r"manager/html",
    r"boaform",
    r"setup\.cgi",
    r"HNAP1",
    r"solr",
    r"jenkins",
    r"console",
]

SUSPICIOUS_RE = re.compile("|".join(SUSPICIOUS_PATH_PATTERNS), re.IGNORECASE)

TIME_FORMATS = [
    "%d/%b/%Y:%H:%M:%S %z",
    "%d/%b/%Y:%H:%M:%S",
]


# ---------------------------------------------------------------------------
# Помошни функции
# ---------------------------------------------------------------------------

def open_log(path: Path) -> TextIO:
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8", errors="replace")
    return open(path, "rt", encoding="utf-8", errors="replace")


def parse_access_time(s: str) -> Optional[datetime]:
    for fmt in TIME_FORMATS:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def parse_error_time(s: str) -> Optional[datetime]:
    try:
        return datetime.strptime(s, "%Y/%m/%d %H:%M:%S")
    except ValueError:
        return None


def shorten(s: str, n: int = 80) -> str:
    s = s or ""
    return s if len(s) <= n else s[: n - 1] + "…"


def is_private_ip(ip: str) -> bool:
    if ip.startswith(("10.", "192.168.", "127.", "169.254.")):
        return True
    if ip.startswith("172."):
        try:
            second = int(ip.split(".")[1])
            return 16 <= second <= 31
        except (IndexError, ValueError):
            return False
    return False


def resolve_log_dir(requested: str) -> Path:
    """Најди директориум со логови. Ако бараната патека постои, користи ја.
    Инаку пробај чести патеки на различни дистрибуции."""
    req = Path(requested)
    if req.is_dir():
        return req

    for candidate in LOG_DIR_CANDIDATES:
        p = Path(candidate)
        if p.is_dir() and any(p.iterdir()):
            return p

    searched = [str(req)] + [c for c in LOG_DIR_CANDIDATES if c != str(req)]
    raise FileNotFoundError(
        "Не е најден директориум со Nginx логови. Пробано:\n  - "
        + "\n  - ".join(searched)
        + "\nЗадај експлицитно: --dir /патека/до/логови"
    )


def _is_access_log(name: str) -> bool:
    return (
        name.startswith("access.log")
        or name.startswith("access_log")
        or name.startswith("nginx-access.log")
        or name.startswith("nginx_access.log")
    )


def _is_error_log(name: str) -> bool:
    return (
        name.startswith("error.log")
        or name.startswith("error_log")
        or name.startswith("nginx-error.log")
        or name.startswith("nginx_error.log")
    )


def discover_logs(log_dir: Path) -> tuple[List[Path], List[Path]]:
    access, error = [], []
    if not log_dir.is_dir():
        raise FileNotFoundError(f"Директориумот не постои: {log_dir}")

    for p in sorted(log_dir.iterdir(), key=lambda x: x.name):
        name = p.name
        if not p.is_file() and not p.is_symlink():
            continue
        if not p.exists():
            continue
        if _is_access_log(name):
            access.append(p)
        elif _is_error_log(name):
            error.append(p)
    return access, error


def sort_logs_newest_first(paths: List[Path]) -> List[Path]:
    """access.log, access.log.1, access.log.2.gz ... (и access_log варијанти)"""

    current_names = {
        "access.log",
        "error.log",
        "access_log",
        "error_log",
        "nginx-access.log",
        "nginx-error.log",
        "nginx_access.log",
        "nginx_error.log",
    }

    def key(p: Path) -> tuple:
        name = p.name
        if name in current_names:
            return (0, 0)
        m = re.search(r"\.(\d+)(?:\.gz)?$", name)
        if m:
            return (1, int(m.group(1)))
        return (2, 0)

    return sorted(paths, key=key)


# ---------------------------------------------------------------------------
# Парсери
# ---------------------------------------------------------------------------

class AccessRecord:
    __slots__ = ("ip", "time", "method", "path", "proto", "status", "size", "referer", "ua")

    def __init__(self, ip, time, method, path, proto, status, size, referer, ua):
        self.ip = ip
        self.time = time
        self.method = method
        self.path = path
        self.proto = proto
        self.status = status
        self.size = size
        self.referer = referer
        self.ua = ua


def parse_access_line(line: str) -> Optional[AccessRecord]:
    line = line.rstrip("\n")
    if not line or line.startswith("#"):
        return None
    m = ACCESS_RE.match(line)
    if not m:
        m = ACCESS_LOOSE_RE.match(line)
        if not m:
            return None
        gd = m.groupdict()
        return AccessRecord(
            ip=gd["ip"],
            time=parse_access_time(gd["time"]),
            method=gd["method"],
            path=gd.get("path", "/"),
            proto="",
            status=int(gd["status"]),
            size=0,
            referer="",
            ua="",
        )
    gd = m.groupdict()
    try:
        size = int(gd["size"]) if gd["size"] not in ("-", "") else 0
    except ValueError:
        size = 0
    return AccessRecord(
        ip=gd["ip"],
        time=parse_access_time(gd["time"]),
        method=gd["method"],
        path=gd["path"],
        proto=gd.get("proto") or "",
        status=int(gd["status"]),
        size=size,
        referer=gd.get("referer") or "",
        ua=gd.get("ua") or "",
    )


class ErrorRecord:
    __slots__ = (
        "time",
        "level",
        "message",
        "ip",
        "server",
        "method",
        "path",
        "host",
        "upstream",
        "referrer",
    )

    def __init__(self, **kw):
        for k in self.__slots__:
            setattr(self, k, kw.get(k))


def parse_error_line(line: str) -> Optional[ErrorRecord]:
    line = line.rstrip("\n")
    if not line:
        return None
    m = ERROR_RE.match(line)
    if not m:
        return None
    gd = m.groupdict()
    msg = gd["message"] or ""
    ip_m = ERROR_CLIENT_RE.search(msg)
    srv_m = ERROR_SERVER_RE.search(msg)
    req_m = ERROR_REQUEST_RE.search(msg)
    host_m = ERROR_HOST_RE.search(msg)
    up_m = ERROR_UPSTREAM_RE.search(msg)
    ref_m = ERROR_REFERRER_RE.search(msg)
    return ErrorRecord(
        time=parse_error_time(gd["time"]),
        level=gd["level"],
        message=msg,
        ip=ip_m.group("ip") if ip_m else None,
        server=srv_m.group("server") if srv_m else None,
        method=req_m.group("method") if req_m else None,
        path=req_m.group("path") if req_m else None,
        host=host_m.group("host") if host_m else None,
        upstream=up_m.group("upstream") if up_m else None,
        referrer=ref_m.group("referrer") if ref_m else None,
    )


# ---------------------------------------------------------------------------
# Агрегација
# ---------------------------------------------------------------------------

class Analyzer:
    def __init__(self):
        self.access_total = 0
        self.access_unparsed = 0
        self.error_total = 0
        self.error_unparsed = 0

        self.by_ip: Dict[str, dict] = defaultdict(
            lambda: {
                "count": 0,
                "bytes": 0,
                "methods": Counter(),
                "statuses": Counter(),
                "paths": Counter(),
                "uas": Counter(),
                "referers": Counter(),
                "first": None,
                "last": None,
                "suspicious": 0,
                "hosts_hint": Counter(),
            }
        )
        self.status_all = Counter()
        self.method_all = Counter()
        self.path_all = Counter()
        self.ua_all = Counter()
        self.hourly = Counter()
        self.daily = Counter()
        self.suspicious_hits: List[tuple] = []

        self.err_level = Counter()
        self.err_by_ip = Counter()
        self.err_by_path = Counter()
        self.err_by_host = Counter()
        self.err_by_server = Counter()
        self.err_by_upstream = Counter()
        self.err_messages = Counter()
        self.err_samples: List[ErrorRecord] = []
        self.err_by_app: Dict[str, Counter] = defaultdict(Counter)

    def add_access(self, rec: AccessRecord) -> None:
        self.access_total += 1
        self.status_all[rec.status] += 1
        self.method_all[rec.method] += 1
        # нормализирај патека без query за агрегација, чувај целосна за детали
        path_full = rec.path
        path_base = rec.path.split("?", 1)[0]
        self.path_all[path_base] += 1
        if rec.ua:
            self.ua_all[rec.ua] += 1

        if rec.time:
            self.hourly[rec.time.strftime("%Y-%m-%d %H:00")] += 1
            self.daily[rec.time.strftime("%Y-%m-%d")] += 1

        ipd = self.by_ip[rec.ip]
        ipd["count"] += 1
        ipd["bytes"] += rec.size
        ipd["methods"][rec.method] += 1
        ipd["statuses"][rec.status] += 1
        ipd["paths"][path_full] += 1
        if rec.ua:
            ipd["uas"][rec.ua] += 1
        if rec.referer and rec.referer != "-":
            ipd["referers"][rec.referer] += 1
        if rec.time:
            if ipd["first"] is None or rec.time < ipd["first"]:
                ipd["first"] = rec.time
            if ipd["last"] is None or rec.time > ipd["last"]:
                ipd["last"] = rec.time

        if SUSPICIOUS_RE.search(path_full):
            ipd["suspicious"] += 1
            if len(self.suspicious_hits) < 500:
                self.suspicious_hits.append((rec.ip, rec.method, path_full, rec.status, rec.time))

    def add_error(self, rec: ErrorRecord) -> None:
        self.error_total += 1
        self.err_level[rec.level] += 1
        if rec.ip:
            self.err_by_ip[rec.ip] += 1
        if rec.path:
            self.err_by_path[rec.path.split("?", 1)[0]] += 1
        if rec.host:
            self.err_by_host[rec.host] += 1
        if rec.server:
            self.err_by_server[rec.server] += 1
        if rec.upstream:
            self.err_by_upstream[rec.upstream] += 1
            self.err_by_app[rec.upstream][rec.level] += 1

        # скратена порака за групирање
        short_msg = rec.message
        # отстрани променливи броеви/пидови за подобро групирање
        short_msg = re.sub(r"\b\d+\.\d+\.\d+\.\d+\b", "<IP>", short_msg)
        short_msg = re.sub(r"upstream:\s*\"[^\"]+\"", "upstream:\"<UP>\"", short_msg)
        short_msg = re.sub(r"request:\s*\"[^\"]+\"", 'request:"<REQ>"', short_msg)
        short_msg = re.sub(r"host:\s*\"[^\"]+\"", 'host:"<HOST>"', short_msg)
        short_msg = re.sub(r"client:\s*\S+", "client:<IP>", short_msg)
        short_msg = shorten(short_msg, 180)
        self.err_messages[short_msg] += 1

        if len(self.err_samples) < 200:
            self.err_samples.append(rec)

    def ingest_access_file(self, path: Path) -> None:
        try:
            with open_log(path) as fh:
                for line in fh:
                    rec = parse_access_line(line)
                    if rec:
                        self.add_access(rec)
                    else:
                        if line.strip():
                            self.access_unparsed += 1
        except PermissionError:
            print(f"[!] Нема дозвола за читање: {path}  (пробај со sudo)", file=sys.stderr)
        except OSError as e:
            print(f"[!] Грешка при читање {path}: {e}", file=sys.stderr)

    def ingest_error_file(self, path: Path) -> None:
        try:
            with open_log(path) as fh:
                for line in fh:
                    rec = parse_error_line(line)
                    if rec:
                        self.add_error(rec)
                    else:
                        if line.strip():
                            self.error_unparsed += 1
        except PermissionError:
            print(f"[!] Нема дозвола за читање: {path}  (пробај со sudo)", file=sys.stderr)
        except OSError as e:
            print(f"[!] Грешка при читање {path}: {e}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Излез
# ---------------------------------------------------------------------------

def fmt_dt(dt: Optional[datetime]) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S") if dt else "-"


def fmt_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024
    return f"{n:.1f} PB"


def print_bar(count: int, total: int, width: int = 24) -> str:
    if total <= 0:
        return ""
    filled = int(width * count / total)
    return "█" * filled + "░" * (width - filled)


def dump_text(az: Analyzer, top_ips: int, paths_per_ip: int, out: TextIO) -> None:
    p = out.write

    p("=" * 88 + "\n")
    p("  NGINX LOG ANALYZER  —  извештај\n")
    p(f"  Генерирано: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    p("=" * 88 + "\n\n")

    p("── ACCESS ЛОГОВИ ──────────────────────────────────────────────────────────\n")
    p(f"  Вкупно барања:          {az.access_total:,}\n")
    p(f"  Непрепознаени линии:    {az.access_unparsed:,}\n")
    p(f"  Уникатни IP адреси:     {len(az.by_ip):,}\n")
    p(f"  Уникатни патеки:        {len(az.path_all):,}\n\n")

    if az.daily:
        p("  Сообраќај по ден:\n")
        for day, c in sorted(az.daily.items()):
            p(f"    {day}  {c:7,}  {print_bar(c, max(az.daily.values()))}\n")
        p("\n")

    p("  HTTP методи:\n")
    for m, c in az.method_all.most_common():
        p(f"    {m:10} {c:8,}  {print_bar(c, az.access_total)}\n")
    p("\n")

    p("  HTTP статус кодови:\n")
    for s, c in sorted(az.status_all.items()):
        kind = (
            "OK" if 200 <= s < 300 else
            "Redirect" if 300 <= s < 400 else
            "Client err" if 400 <= s < 500 else
            "Server err" if s >= 500 else
            "?"
        )
        p(f"    {s}  {kind:12} {c:8,}  {print_bar(c, az.access_total)}\n")
    p("\n")

    p("  Најбарани патеки:\n")
    for path, c in az.path_all.most_common(25):
        p(f"    {c:7,}  {shorten(path, 70)}\n")
    p("\n")

    p("  Топ User-Agent:\n")
    for ua, c in az.ua_all.most_common(10):
        p(f"    {c:7,}  {shorten(ua, 70)}\n")
    p("\n")

    p("=" * 88 + "\n")
    p(f"  IP АДРЕСИ — што правеле (топ {top_ips})\n")
    p("=" * 88 + "\n\n")

    ranked = sorted(az.by_ip.items(), key=lambda kv: kv[1]["count"], reverse=True)
    for i, (ip, d) in enumerate(ranked[:top_ips], 1):
        priv = " [локална]" if is_private_ip(ip) else ""
        p(f"▶ {i:02d}. {ip}{priv}\n")
        p(f"     Барања: {d['count']:,}   Сообраќај: {fmt_bytes(d['bytes'])}   "
          f"Сомнителни: {d['suspicious']}\n")
        p(f"     Прво: {fmt_dt(d['first'])}    Последно: {fmt_dt(d['last'])}\n")

        methods = ", ".join(f"{m}={c}" for m, c in d["methods"].most_common())
        p(f"     Методи: {methods}\n")

        statuses = ", ".join(f"{s}={c}" for s, c in d["statuses"].most_common())
        p(f"     Статуси: {statuses}\n")

        p("     Каде одела (патеки):\n")
        for path, c in d["paths"].most_common(paths_per_ip):
            p(f"       {c:5}×  {shorten(path, 72)}\n")

        if d["uas"]:
            p("     User-Agent:\n")
            for ua, c in d["uas"].most_common(3):
                p(f"       {c:5}×  {shorten(ua, 72)}\n")

        if d["referers"]:
            p("     Referer:\n")
            for ref, c in d["referers"].most_common(3):
                p(f"       {c:5}×  {shorten(ref, 72)}\n")
        p("\n")

    if az.suspicious_hits:
        p("=" * 88 + "\n")
        p("  СОМНИТЕЛНИ БАРАЊА (скенери, експлойти, админ панели…)\n")
        p("=" * 88 + "\n")
        for ip, method, path, status, t in az.suspicious_hits[:80]:
            p(f"  {fmt_dt(t):19}  {ip:16}  {status}  {method:6}  {shorten(path, 50)}\n")
        if len(az.suspicious_hits) > 80:
            p(f"  … уште {len(az.suspicious_hits) - 80} (ограничено во извештајот)\n")
        p("\n")

    p("=" * 88 + "\n")
    p("  ERROR ЛОГОВИ — детали за страни и апликации\n")
    p("=" * 88 + "\n\n")
    p(f"  Вкупно грешки:          {az.error_total:,}\n")
    p(f"  Непрепознаени линии:    {az.error_unparsed:,}\n\n")

    if az.error_total == 0:
        p("  Нема грешки во обработените error.log датотеки "
          "(тековниот error.log може да е празен).\n\n")
        return

    p("  Нивоа:\n")
    for lvl, c in az.err_level.most_common():
        p(f"    {lvl:12} {c:7,}\n")
    p("\n")

    if az.err_by_host:
        p("  Грешки по Host / виртуелен хост (страна):\n")
        for h, c in az.err_by_host.most_common(20):
            p(f"    {c:7,}  {h}\n")
        p("\n")

    if az.err_by_server:
        p("  Грешки по server_name:\n")
        for s, c in az.err_by_server.most_common(20):
            p(f"    {c:7,}  {s}\n")
        p("\n")

    if az.err_by_path:
        p("  Грешки по патека (страна / endpoint):\n")
        for path, c in az.err_by_path.most_common(25):
            p(f"    {c:7,}  {shorten(path, 70)}\n")
        p("\n")

    if az.err_by_upstream:
        p("  Грешки по upstream (апликација / backend):\n")
        for up, c in az.err_by_upstream.most_common(20):
            p(f"    {c:7,}  {up}\n")
            levels = az.err_by_app.get(up, {})
            if levels:
                detail = ", ".join(f"{k}={v}" for k, v in levels.most_common())
                p(f"             нивоа: {detail}\n")
        p("\n")

    if az.err_by_ip:
        p("  Грешки по клиентска IP:\n")
        for ip, c in az.err_by_ip.most_common(20):
            p(f"    {c:7,}  {ip}\n")
        p("\n")

    p("  Најчести типови на пораки (нормализирани):\n")
    for msg, c in az.err_messages.most_common(25):
        p(f"    {c:7,}  {msg}\n")
    p("\n")

    p("  Примери на сурови error записи:\n")
    for rec in az.err_samples[:30]:
        p(f"    [{fmt_dt(rec.time)}] [{rec.level}] ")
        bits = []
        if rec.ip:
            bits.append(f"ip={rec.ip}")
        if rec.host:
            bits.append(f"host={rec.host}")
        if rec.path:
            bits.append(f"{rec.method or '?'} {shorten(rec.path, 40)}")
        if rec.upstream:
            bits.append(f"upstream={shorten(rec.upstream, 40)}")
        p("  ".join(bits) + "\n")
        p(f"      {shorten(rec.message, 140)}\n")
    p("\n")


def dump_html(az: Analyzer, top_ips: int, paths_per_ip: int, dest: Path) -> None:
    def esc(s) -> str:
        return html.escape("" if s is None else str(s))

    rows_ip = []
    ranked = sorted(az.by_ip.items(), key=lambda kv: kv[1]["count"], reverse=True)
    for i, (ip, d) in enumerate(ranked[:top_ips], 1):
        paths_html = "<br>".join(
            f"<code>{esc(shorten(path, 90))}</code> <small>×{c}</small>"
            for path, c in d["paths"].most_common(paths_per_ip)
        )
        ua_html = "<br>".join(esc(shorten(ua, 90)) for ua, _ in d["uas"].most_common(2))
        st = ", ".join(f"{s}={c}" for s, c in d["statuses"].most_common())
        methods = ", ".join(f"{m}={c}" for m, c in d["methods"].most_common())
        cls = "sus" if d["suspicious"] else ""
        rows_ip.append(
            f"<tr class='{cls}'>"
            f"<td>{i}</td><td><strong>{esc(ip)}</strong></td>"
            f"<td>{d['count']:,}</td><td>{esc(fmt_bytes(d['bytes']))}</td>"
            f"<td>{d['suspicious']}</td>"
            f"<td>{esc(fmt_dt(d['first']))}<br>{esc(fmt_dt(d['last']))}</td>"
            f"<td>{esc(methods)}<br><small>{esc(st)}</small></td>"
            f"<td>{paths_html}</td><td><small>{ua_html}</small></td>"
            f"</tr>"
        )

    status_rows = "".join(
        f"<tr><td>{s}</td><td>{c:,}</td></tr>"
        for s, c in sorted(az.status_all.items())
    )
    path_rows = "".join(
        f"<tr><td><code>{esc(shorten(p, 80))}</code></td><td>{c:,}</td></tr>"
        for p, c in az.path_all.most_common(30)
    )
    err_path_rows = "".join(
        f"<tr><td><code>{esc(shorten(p, 80))}</code></td><td>{c:,}</td></tr>"
        for p, c in az.err_by_path.most_common(30)
    )
    err_up_rows = "".join(
        f"<tr><td><code>{esc(u)}</code></td><td>{c:,}</td></tr>"
        for u, c in az.err_by_upstream.most_common(20)
    )
    err_host_rows = "".join(
        f"<tr><td>{esc(h)}</td><td>{c:,}</td></tr>"
        for h, c in az.err_by_host.most_common(20)
    )
    err_msg_rows = "".join(
        f"<tr><td>{c:,}</td><td><code>{esc(m)}</code></td></tr>"
        for m, c in az.err_messages.most_common(30)
    )
    err_sample_rows = "".join(
        "<tr>"
        f"<td>{esc(fmt_dt(r.time))}</td><td>{esc(r.level)}</td>"
        f"<td>{esc(r.ip or '')}</td><td>{esc(r.host or r.server or '')}</td>"
        f"<td><code>{esc((r.method or '') + ' ' + (r.path or ''))}</code></td>"
        f"<td><small>{esc(shorten(r.message, 200))}</small></td>"
        "</tr>"
        for r in az.err_samples[:80]
    )
    sus_rows = "".join(
        f"<tr><td>{esc(fmt_dt(t))}</td><td>{esc(ip)}</td>"
        f"<td>{status}</td><td>{esc(method)}</td>"
        f"<td><code>{esc(shorten(path, 90))}</code></td></tr>"
        for ip, method, path, status, t in az.suspicious_hits[:150]
    )

    page = f"""<!DOCTYPE html>
<html lang="mk">
<head>
<meta charset="utf-8">
<title>Nginx Log Analyzer</title>
<style>
  :root {{ --bg:#0f1419; --card:#1a2332; --fg:#e7ecf3; --muted:#8b9bb4; --acc:#3d8bfd; --sus:#ff6b6b; }}
  body {{ font-family: ui-sans-serif, system-ui, sans-serif; background:var(--bg); color:var(--fg);
         margin:0; padding:24px; line-height:1.45; }}
  h1,h2 {{ font-weight:650; }}
  h1 {{ margin-top:0; }}
  h2 {{ margin-top:2.2rem; border-bottom:1px solid #2a3548; padding-bottom:.4rem; }}
  .meta {{ color:var(--muted); }}
  .cards {{ display:flex; gap:12px; flex-wrap:wrap; margin:16px 0 8px; }}
  .card {{ background:var(--card); border-radius:10px; padding:14px 18px; min-width:140px; }}
  .card b {{ display:block; font-size:1.4rem; }}
  .card span {{ color:var(--muted); font-size:.85rem; }}
  table {{ border-collapse:collapse; width:100%; background:var(--card); border-radius:10px; overflow:hidden; font-size:.92rem; }}
  th,td {{ text-align:left; padding:8px 10px; vertical-align:top; border-bottom:1px solid #243044; }}
  th {{ background:#223049; position:sticky; top:0; }}
  tr.sus td:first-child, tr.sus td:nth-child(2) {{ color:var(--sus); }}
  code {{ font-size:.85em; word-break:break-all; }}
  small {{ color:var(--muted); }}
  .wrap {{ overflow-x:auto; }}
</style>
</head>
<body>
<h1>Nginx Log Analyzer</h1>
<p class="meta">Генерирано {esc(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))}</p>

<div class="cards">
  <div class="card"><b>{az.access_total:,}</b><span>access барања</span></div>
  <div class="card"><b>{len(az.by_ip):,}</b><span>уникатни IP</span></div>
  <div class="card"><b>{len(az.path_all):,}</b><span>уникатни патеки</span></div>
  <div class="card"><b>{az.error_total:,}</b><span>error записи</span></div>
  <div class="card"><b>{sum(1 for d in az.by_ip.values() if d['suspicious'])}</b><span>IP со сомнителни барања</span></div>
</div>

<h2>Статус кодови</h2>
<div class="wrap"><table><tr><th>Статус</th><th>Број</th></tr>{status_rows}</table></div>

<h2>Најбарани патеки</h2>
<div class="wrap"><table><tr><th>Патека</th><th>Барања</th></tr>{path_rows}</table></div>

<h2>IP адреси — каде оделе и што правеле</h2>
<div class="wrap"><table>
<tr><th>#</th><th>IP</th><th>Барања</th><th>Бајти</th><th>Сомнит.</th><th>Прво / Последно</th><th>Методи / статуси</th><th>Патеки</th><th>User-Agent</th></tr>
{''.join(rows_ip)}
</table></div>

<h2>Сомнителни барања</h2>
<div class="wrap"><table>
<tr><th>Време</th><th>IP</th><th>Статус</th><th>Метод</th><th>Патека</th></tr>
{sus_rows or '<tr><td colspan="5">Нема детектирани.</td></tr>'}
</table></div>

<h2>Error лог — страни (host)</h2>
<div class="wrap"><table><tr><th>Host</th><th>Грешки</th></tr>{err_host_rows or '<tr><td colspan="2">Нема.</td></tr>'}</table></div>

<h2>Error лог — патеки / endpoint-и</h2>
<div class="wrap"><table><tr><th>Патека</th><th>Грешки</th></tr>{err_path_rows or '<tr><td colspan="2">Нема.</td></tr>'}</table></div>

<h2>Error лог — апликации (upstream)</h2>
<div class="wrap"><table><tr><th>Upstream</th><th>Грешки</th></tr>{err_up_rows or '<tr><td colspan="2">Нема (или Nginx не е како reverse proxy).</td></tr>'}</table></div>

<h2>Најчести error пораки</h2>
<div class="wrap"><table><tr><th>Број</th><th>Порака</th></tr>{err_msg_rows or '<tr><td colspan="2">Нема.</td></tr>'}</table></div>

<h2>Примери од error.log</h2>
<div class="wrap"><table>
<tr><th>Време</th><th>Ниво</th><th>IP</th><th>Host</th><th>Барање</th><th>Порака</th></tr>
{err_sample_rows or '<tr><td colspan="6">Нема.</td></tr>'}
</table></div>
</body></html>
"""
    dest.write_text(page, encoding="utf-8")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Анализатор на Nginx access и error логови.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument("-d", "--dir", default=DEFAULT_LOG_DIR, help="Директориум со логови")
    ap.add_argument("-n", "--top-ips", type=int, default=DEFAULT_TOP_IPS, help="Колку IP да се прикажат")
    ap.add_argument("-p", "--paths-per-ip", type=int, default=DEFAULT_PATHS_PER_IP,
                    help="Колку патеки по IP")
    ap.add_argument("--access-only", action="store_true", help="Само access логови")
    ap.add_argument("--error-only", action="store_true", help="Само error логови")
    ap.add_argument("--current-only", action="store_true",
                    help="Само тековните access.log и error.log (без ротации)")
    ap.add_argument("--max-files", type=int, default=0,
                    help="Макс. број датотеки по тип (0 = сите)")
    ap.add_argument("-o", "--output", default="", help="Зачувај текстуален извештај во датотека")
    ap.add_argument("--html", default="", help="Зачувај HTML извештај во датотека")
    ap.add_argument("-q", "--quiet", action="store_true",
                    help="Без прогрес на stdout (за cron/systemd)")
    return ap


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        log_dir = resolve_log_dir(args.dir)
    except FileNotFoundError as e:
        print(f"[!] {e}", file=sys.stderr)
        return 1

    try:
        access_files, error_files = discover_logs(log_dir)
    except FileNotFoundError as e:
        print(f"[!] {e}", file=sys.stderr)
        return 1

    access_files = sort_logs_newest_first(access_files)
    error_files = sort_logs_newest_first(error_files)

    if args.current_only:
        current_access = {
            "access.log",
            "access_log",
            "nginx-access.log",
            "nginx_access.log",
        }
        current_error = {
            "error.log",
            "error_log",
            "nginx-error.log",
            "nginx_error.log",
        }
        access_files = [p for p in access_files if p.name in current_access]
        error_files = [p for p in error_files if p.name in current_error]
    if args.max_files:
        access_files = access_files[: args.max_files]
        error_files = error_files[: args.max_files]

    def log(msg: str) -> None:
        if not args.quiet:
            print(msg, flush=True)

    if str(log_dir) != args.dir:
        log(f"Лог директориум: {log_dir}  (автоматски најден, зададено беше {args.dir})")
    else:
        log(f"Лог директориум: {log_dir}")
    log("Датотеки што ќе се обработат:")
    if not args.error_only:
        for p in access_files:
            log(f"  ACCESS  {p}  ({p.stat().st_size:,} B)")
    if not args.access_only:
        for p in error_files:
            log(f"  ERROR   {p}  ({p.stat().st_size:,} B)")
    log("")

    az = Analyzer()
    if not args.error_only:
        for p in access_files:
            log(f"Читам {p.name} …")
            az.ingest_access_file(p)
    if not args.access_only:
        for p in error_files:
            log(f"Читам {p.name} …")
            az.ingest_error_file(p)
    log("")

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", encoding="utf-8") as fh:
            dump_text(az, args.top_ips, args.paths_per_ip, fh)
        log(f"Текстуален извештај: {out_path.resolve()}")
    else:
        dump_text(az, args.top_ips, args.paths_per_ip, sys.stdout)

    if args.html:
        html_path = Path(args.html)
        html_path.parent.mkdir(parents=True, exist_ok=True)
        dump_html(az, args.top_ips, args.paths_per_ip, html_path)
        log(f"HTML извештај: {html_path.resolve()}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
