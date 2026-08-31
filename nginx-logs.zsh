# Nginx helper за zsh.
# Во ~/.zshrc додај:  source /usr/local/bin/nginx-logs.zsh
# или само копирај ја функцијата logs() подолу.

nginx-logs-need-sudo() {
  local f="${1:-/var/log/nginx/access.log}"
  [[ -r "$f" ]] && return 1
  return 0
}

logs() {
  local logdir="${NGINX_LOG_DIR:-/var/log/nginx}"
  local analyzer="${NGINX_ANALYZER:-/usr/local/bin/nginx_log_analyzer.py}"
  local pager="${PAGER:-less}"
  local sudo_cmd=()
  local cmd="${1:-}"

  if nginx-logs-need-sudo "$logdir/access.log" || nginx-logs-need-sudo "$logdir/error.log"; then
    sudo_cmd=(sudo)
  fi

  case "$cmd" in
    -h|--help|help)
      cat <<'EOF'
logs                  access.log во less (најново горе ако користиш +G)
logs a|access         истото
logs e|err|error      error.log
logs f|follow         live: access + error (tail -F)
logs fa               live само access
logs fe               live само error
logs today            само тековните логови низ анализаторот
logs report [args]    полн извештај (сите ротации, вкл. .gz)
logs last             последниот зачуван извештај од /var/log/nginx-reports
logs gz               листа ротирани .gz логови
logs grep <текст>     бара низ access.log (и access.log.1)

Примери:
  logs
  logs f
  logs report -n 20
  logs grep wp-login
EOF
      return 0
      ;;
    ""|a|access)
      "${sudo_cmd[@]}" "$pager" +G "$logdir/access.log"
      ;;
    e|err|error)
      "${sudo_cmd[@]}" "$pager" +G "$logdir/error.log"
      ;;
    f|follow)
      "${sudo_cmd[@]}" tail -F "$logdir/access.log" "$logdir/error.log"
      ;;
    fa)
      "${sudo_cmd[@]}" tail -F "$logdir/access.log"
      ;;
    fe)
      "${sudo_cmd[@]}" tail -F "$logdir/error.log"
      ;;
    today)
      if [[ ! -f "$analyzer" ]]; then
        echo "Нема анализатор: $analyzer" >&2
        echo "Стави ја скриптата таму или: export NGINX_ANALYZER=/патека/nginx_log_analyzer.py" >&2
        return 1
      fi
      "${sudo_cmd[@]}" python3 "$analyzer" --current-only -n "${NGINX_TOP_IPS:-20}" | "$pager" -R
      ;;
    report)
      shift
      if [[ ! -f "$analyzer" ]]; then
        echo "Нема анализатор: $analyzer" >&2
        return 1
      fi
      "${sudo_cmd[@]}" python3 "$analyzer" -n "${NGINX_TOP_IPS:-30}" "$@" | "$pager" -R
      ;;
    last)
      local latest="/var/log/nginx-reports/latest.txt"
      if [[ -r "$latest" ]]; then
        "$pager" "$latest"
      elif nginx-logs-need-sudo "$latest" && [[ -f "$latest" ]]; then
        sudo "$pager" "$latest"
      else
        echo "Нема $latest — прво пушти nginx-daily-report.sh или: logs report" >&2
        return 1
      fi
      ;;
    gz)
      "${sudo_cmd[@]}" ls -lah "$logdir"/access.log* "$logdir"/error.log*
      ;;
    grep)
      shift
      if [[ -z "${1:-}" ]]; then
        echo "Употреба: logs grep <текст>" >&2
        return 1
      fi
      "${sudo_cmd[@]}" grep -n --color=always -i -- "$@" \
        "$logdir/access.log" "$logdir/access.log.1" 2>/dev/null | "$pager" -R
      ;;
    *)
      echo "Непознато: $cmd   (logs help)" >&2
      return 1
      ;;
  esac
}

# tab completion
_logs() {
  local -a opts
  opts=(
    'help:помош'
    'access:access.log'
    'error:error.log'
    'follow:live access+error'
    'fa:live access'
    'fe:live error'
    'today:анализа само денес'
    'report:полн извештај'
    'last:последен зачуван извештај'
    'gz:листај ги сите лог датотеки'
    'grep:барај во access логови'
  )
  _describe 'logs' opts
}
compdef _logs logs
