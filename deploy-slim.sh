#!/usr/bin/env bash
# =============================================================================
# Edu · 低配服务器部署（1–2 GB 内存，不用 Docker）
#
#   bash deploy-slim.sh                  # 加 swap → 建 venv → 装精简依赖 → systemd 常驻
#   bash deploy-slim.sh status | logs | restart | down | uninstall
#
# 与 deploy.sh（Docker 版）的区别：
#   - 不构建镜像，不需要 Docker，内存占用从 ~800 MB 降到 ~250 MB
#   - 代价：拍题 OCR 返回 503，检索退回 BM25（因为没有 onnxruntime / fastembed）
#   - 前端直接用仓库里的 web/dist，不需要 Node
#
# 适用：阿里云 / 腾讯云 1 GiB 入门机型、树莓派、闲置 NUC。
# =============================================================================
set -Eeuo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$APP_DIR"

CMD="up"
PORT="${EDU_PORT:-8000}"
MODE="bm25"
SWAP_MB=1024
PRINT_UNIT=0
SERVICE="/etc/systemd/system/edu.service"
PY="$APP_DIR/.venv/bin/python"

if [ -t 1 ]; then
  C_RED=$'\033[31m'; C_GRN=$'\033[32m'; C_YEL=$'\033[33m'; C_END=$'\033[0m'
else
  C_RED=""; C_GRN=""; C_YEL=""; C_END=""
fi
step() { printf '\n%s==>%s %s\n' "$C_GRN" "$C_END" "$*"; }
info() { printf '    %s\n' "$*"; }
warn() { printf '%s[注意]%s %s\n' "$C_YEL" "$C_END" "$*" >&2; }
die()  { printf '%s[失败]%s %s\n' "$C_RED" "$C_END" "$*" >&2; exit 1; }

trap 'code=$?; [ $code -ne 0 ] && printf "\n%s[失败]%s 第 %s 行（退出码 %s）\n" "$C_RED" "$C_END" "$LINENO" "$code" >&2; exit $code' ERR

usage() {
  cat <<'EOF'
Edu 低配部署（无 Docker）

用法：bash deploy-slim.sh [命令] [选项]

命令：
  up（默认）   安装依赖并注册 systemd 服务
  status       服务状态 + 健康检查 + 内存占用
  logs         跟踪日志（journalctl）
  restart      重启
  down         停止并取消开机自启（数据保留）
  uninstall    彻底删除服务与 .venv（data/ 保留）

选项：
  --port <端口>    监听端口，默认 8000
  --swap <MB>      小于 2.5 GB 内存时创建的 swap 大小，默认 1024，0 表示不建
  --print-unit     只打印 systemd 单元文件，不安装（用于检查）
  -h, --help       显示本帮助
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    up|status|logs|restart|down|uninstall) CMD="$1"; shift ;;
    --port)         PORT="${2:?--port 后面要跟端口}"; shift 2 ;;
    --port=*)       PORT="${1#*=}"; shift ;;
    --swap)         SWAP_MB="${2:?--swap 后面要跟 MB 数}"; shift 2 ;;
    --swap=*)       SWAP_MB="${1#*=}"; shift ;;
    --print-unit)   PRINT_UNIT=1; shift ;;
    -h|--help)      usage; exit 0 ;;
    *)              usage >&2; die "未知参数：$1" ;;
  esac
done

case "$PORT" in
  ''|*[!0-9]*) die "--port 只接受数字，收到：$PORT" ;;
esac
[ "$PORT" -ge 1 ] && [ "$PORT" -le 65535 ] || die "端口超出范围：$PORT"
case "$SWAP_MB" in ''|*[!0-9]*) die "--swap 只接受数字" ;; esac

unit_file() {
  cat <<EOF
[Unit]
Description=Edu AI Teaching Service (slim)
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=$APP_DIR
Environment=EDU_HOST=0.0.0.0
Environment=EDU_PORT=$PORT
Environment=EDU_OPEN_BROWSER=0
Environment=EDU_DATA_DIR=$APP_DIR/data
Environment=EDU_RETRIEVAL_MODE=$MODE
Environment=EDU_LOG_LEVEL=INFO
# 有 Key 就写在这里，或放到 $APP_DIR/.env（EnvironmentFile 会读）
EnvironmentFile=-$APP_DIR/.env
ExecStart=$PY -m server.main --host 0.0.0.0 --port $PORT --no-browser
Restart=always
RestartSec=3
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF
}

if [ "$PRINT_UNIT" -eq 1 ]; then
  unit_file
  exit 0
fi

[ "$(uname -s)" = "Linux" ] || die "本脚本要在 Linux 服务器上跑。"

SUDO=""
if [ "$(id -u)" -ne 0 ]; then
  command -v sudo >/dev/null 2>&1 || die "需要 root 或 sudo。"
  SUDO="sudo"
fi

ensure_swap() {
  local mem_mb
  mem_mb="$(awk '/MemTotal/{printf "%d", $2/1024}' /proc/meminfo)"
  if [ "$SWAP_MB" -eq 0 ]; then info "已按参数跳过 swap。"; return 0; fi
  if [ "$mem_mb" -ge 2500 ]; then info "内存 ${mem_mb} MB，不需要 swap。"; return 0; fi
  if [ -n "$(swapon --show --noheadings 2>/dev/null)" ]; then info "已存在 swap，跳过。"; return 0; fi

  step "内存 ${mem_mb} MB，加 ${SWAP_MB} MB swap（防止 pip 安装时被 OOM 杀掉）"
  $SUDO fallocate -l "${SWAP_MB}M" /swapfile 2>/dev/null \
    || $SUDO dd if=/dev/zero of=/swapfile bs=1M count="$SWAP_MB" status=none
  $SUDO chmod 600 /swapfile
  $SUDO mkswap /swapfile >/dev/null
  $SUDO swapon /swapfile
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' | $SUDO tee -a /etc/fstab >/dev/null
  info "swap 已启用：$(free -m | awk '/Swap/{print $2" MB"}')"
}

ensure_python() {
  step "检查 Python"
  if ! command -v python3 >/dev/null 2>&1; then
    info "安装 python3 / venv"
    $SUDO apt-get update -qq
    $SUDO apt-get install -y -qq python3 python3-venv python3-pip curl
  fi
  python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' \
    || die "需要 Python 3.10+，当前是 $(python3 -V 2>&1)"
  info "$(python3 -V 2>&1)"
}

install_deps() {
  step "创建虚拟环境并安装精简依赖（约 120 MB，不含 OCR/向量）"
  if [ -x "$PY" ] && ! "$PY" -c 'import fastapi' >/dev/null 2>&1; then
    warn "已有 .venv 但不完整，重建。"
    rm -rf "$APP_DIR/.venv"
  fi
  [ -x "$PY" ] || python3 -m venv "$APP_DIR/.venv"
  "$PY" -m pip install -q --upgrade pip

  # 大陆机器直连 pypi.org 经常超时，失败一次就换清华镜像
  local mirror="${EDU_PIP_INDEX:-https://pypi.tuna.tsinghua.edu.cn/simple}"
  if ! "$PY" -m pip install -q -r "$APP_DIR/requirements-slim.txt"; then
    warn "默认源失败，改用镜像重试：$mirror"
    "$PY" -m pip install -q -r "$APP_DIR/requirements-slim.txt" -i "$mirror"
  fi
  info "依赖装好了：$("$PY" -c 'import fastapi; print("fastapi", fastapi.__version__)')"
}

install_service() {
  step "注册 systemd 服务"
  unit_file | $SUDO tee "$SERVICE" >/dev/null
  $SUDO systemctl daemon-reload
  $SUDO systemctl enable edu >/dev/null 2>&1 || true
  $SUDO systemctl restart edu
  info "已写入 $SERVICE 并启动"
}

wait_health() {
  local i
  command -v curl >/dev/null 2>&1 || { info "没有 curl，跳过健康检查。"; return 0; }
  for i in $(seq 1 45); do
    if curl -fsS --max-time 2 "http://127.0.0.1:${PORT}/api/health" >/dev/null 2>&1; then
      info "健康检查通过"
      return 0
    fi
    [ $((i % 5)) -eq 0 ] && info "等待中… $((i * 2)) 秒" || true
    sleep 2
  done
  warn "90 秒没等到健康响应，看日志：bash deploy-slim.sh logs"
  $SUDO journalctl -u edu -n 30 --no-pager || true
  return 1
}

public_ip() {
  local ip
  ip="$(curl -fsS --max-time 2 http://100.100.100.200/latest/meta-data/eipv4 2>/dev/null || true)"
  [ -n "$ip" ] || ip="$(curl -fsS --max-time 4 https://api.ipify.org 2>/dev/null || true)"
  printf '%s' "${ip:-<服务器公网IP>}"
}

harden_demo() {
  local base token newpass code
  base="http://127.0.0.1:${PORT}/api"
  code="$(curl -s -o /tmp/edu_login.json -w '%{http_code}' --max-time 8 \
    -X POST "${base}/teacher/login" -H 'Content-Type: application/json' \
    -d '{"username":"demo","password":"demo1234"}' 2>/dev/null || echo 000)"
  [ "$code" = "200" ] || { info "demo 账号已不是默认密码，跳过。"; rm -f /tmp/edu_login.json; return 0; }

  token="$(sed -n 's/.*"token"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' /tmp/edu_login.json | head -n 1)"
  rm -f /tmp/edu_login.json
  [ -n "$token" ] || { warn "没解析到 token，请登录界面手动改密码。"; return 0; }

  if command -v openssl >/dev/null 2>&1; then newpass="$(openssl rand -hex 8)"; else newpass="$(head -c 16 /dev/urandom | od -An -tx1 | tr -d ' \n' | cut -c1-16)"; fi
  code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 8 \
    -X PUT "${base}/teacher/password" -H 'Content-Type: application/json' \
    -H "Authorization: Bearer $token" \
    -d "{\"old_password\":\"demo1234\",\"new_password\":\"${newpass}\"}" 2>/dev/null || echo 000)"
  if [ "$code" = "200" ]; then
    printf 'teacher=demo\npassword=%s\nurl=http://%s:%s\n' "$newpass" "$(public_ip)" "$PORT" > "$APP_DIR/.demo-credentials"
    chmod 600 "$APP_DIR/.demo-credentials"
    info "demo 密码已改成随机值：.demo-credentials"
  else
    warn "改密码失败（HTTP $code），请手工处理。"
  fi
}

summary() {
  local ip
  ip="$(public_ip)"
  step "部署完成"
  cat <<EOF
    访问地址   http://${ip}:${PORT}
    健康检查   http://${ip}:${PORT}/api/health
    数据目录   $APP_DIR/data
    运行模式   精简模式（EDU_RETRIEVAL_MODE=$MODE，无 OCR）

    常用命令
      bash deploy-slim.sh status    状态与内存
      bash deploy-slim.sh logs      跟踪日志
      bash deploy-slim.sh restart   重启

    还差一步（云控制台里做，脚本改不了）
      安全组/防火墙放行 TCP ${PORT}
EOF
  warn "拍题识别与向量检索在这台机器上不可用（省内存），其余功能正常。"
  [ -f "$APP_DIR/.demo-credentials" ] && info "demo 新密码见 .demo-credentials"
  info "内存占用：$(free -m | awk '/Mem:/{printf "已用 %s MB / 共 %s MB", $3, $2}')"
}

case "$CMD" in
  up)
    ensure_swap
    ensure_python
    install_deps
    install_service
    if wait_health; then
      harden_demo || true
      summary
    else
      die "启动失败，先看：bash deploy-slim.sh logs"
    fi
    ;;
  status)
    $SUDO systemctl status edu --no-pager -n 5 || true
    if curl -fsS --max-time 3 "http://127.0.0.1:${PORT}/api/health" >/dev/null 2>&1; then
      info "健康检查：通过"
      curl -fsS "http://127.0.0.1:${PORT}/api/health" | head -c 400; printf '\n'
    else
      warn "健康检查：不通"
    fi
    free -m
    ;;
  logs)
    $SUDO journalctl -u edu -f -n 100
    ;;
  restart)
    $SUDO systemctl restart edu
    wait_health || true
    ;;
  down)
    $SUDO systemctl stop edu 2>/dev/null || true
    $SUDO systemctl disable edu 2>/dev/null || true
    info "服务已停止并取消开机自启；data/ 保留。"
    ;;
  uninstall)
    $SUDO systemctl disable --now edu 2>/dev/null || true
    $SUDO rm -f "$SERVICE"
    $SUDO systemctl daemon-reload
    rm -rf "$APP_DIR/.venv"
    info "已删除 service 与 .venv；data/ 与代码保留。"
    ;;
  *)
    usage >&2; die "未知命令：$CMD"
    ;;
esac
