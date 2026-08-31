#!/usr/bin/env bash
# Дневен Nginx извештај. Стави ја скриптата во cron или systemd timer.
set -euo pipefail

ANALYZER="${ANALYZER:-/usr/local/bin/nginx_log_analyzer.py}"
LOG_DIR="${LOG_DIR:-/var/log/nginx}"
REPORT_DIR="${REPORT_DIR:-/var/log/nginx-reports}"
KEEP_DAYS="${KEEP_DAYS:-30}"
MAIL_TO="${MAIL_TO:-}"          # пр. admin@example.com  (празно = без е-пошта)
TOP_IPS="${TOP_IPS:-40}"
PATHS_PER_IP="${PATHS_PER_IP:-25}"

DATE="$(date +%F)"
TXT="${REPORT_DIR}/nginx-report-${DATE}.txt"
HTML="${REPORT_DIR}/nginx-report-${DATE}.html"
LATEST_TXT="${REPORT_DIR}/latest.txt"
LATEST_HTML="${REPORT_DIR}/latest.html"

mkdir -p "${REPORT_DIR}"

python3 "${ANALYZER}" \
  --dir "${LOG_DIR}" \
  --top-ips "${TOP_IPS}" \
  --paths-per-ip "${PATHS_PER_IP}" \
  --quiet \
  -o "${TXT}" \
  --html "${HTML}"

ln -sfn "$(basename "${TXT}")" "${LATEST_TXT}"
ln -sfn "$(basename "${HTML}")" "${LATEST_HTML}"

# избриши извештаи постари од KEEP_DAYS
find "${REPORT_DIR}" -type f \( -name 'nginx-report-*.txt' -o -name 'nginx-report-*.html' \) -mtime +"${KEEP_DAYS}" -delete

if [[ -n "${MAIL_TO}" ]] && command -v mail >/dev/null 2>&1; then
  # краток преглед во телото, целиот txt како прилог ако mail поддржува -A
  SUBJECT="Nginx извештај ${DATE} ($(hostname -s))"
  if mail -A "${TXT}" -s "${SUBJECT}" "${MAIL_TO}" </dev/null 2>/dev/null; then
    :
  else
    mail -s "${SUBJECT}" "${MAIL_TO}" < "${TXT}"
  fi
fi
