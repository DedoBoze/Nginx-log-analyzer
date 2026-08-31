#!/usr/bin/env bash
# Преносна инсталација за Debian/Ubuntu, Fedora/RHEL/CentOS/Rocky/Alma,
# Arch, openSUSE и Alpine. Не инсталира Nginx — само анализаторот.
set -euo pipefail

PREFIX="${PREFIX:-/usr/local}"
BIN_DIR="${BIN_DIR:-$PREFIX/bin}"
REPORT_DIR="${REPORT_DIR:-/var/log/nginx-reports}"

ROOT="$(cd "$(dirname "$0")" && pwd)"

die() { echo "[!] $*" >&2; exit 1; }
info() { echo "[*] $*"; }

need_root() {
  if [[ "$(id -u)" -ne 0 ]]; then
    die "Пушти со root/sudo: sudo $0"
  fi
}

detect_os() {
  if [[ -f /etc/os-release ]]; then
    # shellcheck disable=SC1091
    . /etc/os-release
    echo "${ID_LIKE:-} ${ID:-unknown}"
  else
    echo "unknown"
  fi
}

nginx_user_guess() {
  if getent passwd www-data >/dev/null 2>&1; then
    echo "www-data"
  elif getent passwd nginx >/dev/null 2>&1; then
    echo "nginx"
  elif getent passwd wwwrun >/dev/null 2>&1; then
    echo "wwwrun"
  elif getent passwd http >/dev/null 2>&1; then
    echo "http"
  else
    echo "nginx"
  fi
}

nginx_group_guess() {
  if getent group adm >/dev/null 2>&1 && getent passwd www-data >/dev/null 2>&1; then
    echo "adm"
  elif getent group nginx >/dev/null 2>&1; then
    echo "nginx"
  elif getent group www >/dev/null 2>&1; then
    echo "www"
  elif getent group adm >/dev/null 2>&1; then
    echo "adm"
  else
    echo "root"
  fi
}

need_root

[[ -f "$ROOT/nginx_log_analyzer.py" ]] || die "nginx_log_analyzer.py не е до овој скрипт"

info "Инсталирам во $BIN_DIR"
mkdir -p "$BIN_DIR" "$REPORT_DIR"
install -m 0755 "$ROOT/nginx_log_analyzer.py" "$BIN_DIR/nginx_log_analyzer.py"
install -m 0755 "$ROOT/nginx-daily-report.sh" "$BIN_DIR/nginx-daily-report.sh"
install -m 0644 "$ROOT/nginx-logs.zsh" "$BIN_DIR/nginx-logs.zsh"

if [[ -d /etc/systemd/system ]]; then
  install -m 0644 "$ROOT/nginx-report.service" /etc/systemd/system/nginx-report.service
  install -m 0644 "$ROOT/nginx-report.timer" /etc/systemd/system/nginx-report.timer
  if command -v systemctl >/dev/null 2>&1; then
    systemctl daemon-reload || true
  fi
fi

OS="$(detect_os)"
NUSER="$(nginx_user_guess)"
NGROUP="$(nginx_group_guess)"

# Извештаите треба да ги чита root (анализатор) и по желба админот
chmod 0750 "$REPORT_DIR" 2>/dev/null || true

info "ОС: $OS"
info "Nginx корисник/група (погаѓање): $NUSER / $NGROUP"
info "Бинарки: $BIN_DIR/nginx_log_analyzer.py"
info "Извештаи: $REPORT_DIR"
echo
echo "Следни чекори:"
echo "  1) Тест:     sudo python3 $BIN_DIR/nginx_log_analyzer.py --current-only"
echo "  2) zsh:      source $BIN_DIR/nginx-logs.zsh"
echo "  3) Тајмер:   sudo systemctl enable --now nginx-report.timer"
echo
echo "Дозволи за логови — додај се во групата што ги чита:"
case " $OS " in
  *"debian"*|*"ubuntu"*|*"linuxmint"*)
    echo "  sudo usermod -aG adm \"\$USER\"    # Debian/Ubuntu: www-data:adm"
    ;;
  *"rhel"*|*"fedora"*|*"centos"*|*"rocky"*|*"almalinux"*|*"amzn"*)
    echo "  sudo usermod -aG $NGROUP \"\$USER\"    # Fedora/RHEL фамилија: обично nginx:nginx"
    echo "  # или читај ги логовите само со sudo"
    ;;
  *"arch"*|*"manjaro"*|*"endeavouros"*)
    echo "  sudo usermod -aG $NGROUP \"\$USER\"    # Arch: обично http или nginx"
    ;;
  *"suse"*|*"opensuse"*)
    echo "  sudo usermod -aG $NGROUP \"\$USER\"    # openSUSE: nginx или www"
    ;;
  *"alpine"*)
    echo "  sudo adduser \$USER $NGROUP           # Alpine"
    ;;
  *)
    echo "  sudo usermod -aG $NGROUP \"\$USER\""
    echo "  ls -l /var/log/nginx   # провери сопственик/група кај тебе"
    ;;
esac
echo
echo "Ако логовите не се во /var/log/nginx:"
echo "  sudo python3 $BIN_DIR/nginx_log_analyzer.py --dir /патека/до/логови"
echo "  # или: export LOG_DIR=/патека/до/логови"
