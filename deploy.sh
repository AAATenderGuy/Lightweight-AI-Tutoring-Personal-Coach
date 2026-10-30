#!/usr/bin/env bash
# =============================================================================
# Edu · 云服务器一键部署（Ubuntu 22.04 / 24.04，Debian 12 亦可）
#
#   bash deploy.sh                      # 装 Docker → 生成 .env → 构建 → 起服务 → 健康检查
#   bash deploy.sh --domain edu.x.cn    # 额外拉起 Caddy，自动 HTTPS（域名需先解析到本机）
#   bash deploy.sh update | logs | status | restart | backup | down
#
# 三条跟这套代码强绑定的约束，改脚本时别动：
#   1. 单进程：SSE 事件总线、在线名单、限流都在进程内存里，开多 worker 会串台；
#   2. 数据在命名卷 edu-data 里（不是 ./data 绑定挂载），容器内 uid 10001 才有写权限；
#   3. 大模型 Key 只走环境变量，容器不读宿主机 data/settings.json。
# =============================================================================
set -Eeuo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$APP_DIR"

# ---------------------------------------------------------------- 默认值
CMD="up"
PORT="${EDU_PORT:-8000}"
DOMAIN=""
ACME_EMAIL=""
API_KEY="${EDU_API_KEY:-}"
MODE="${EDU_RETRIEVAL_MODE:-hybrid}"
PORT_GIVEN=0
MODE_GIVEN=0
NO_BUILD="${EDU_NO_BUILD:-0}"
ASSUME_YES=0
PURGE=0
SUDO=""
DOCKER=(docker)
COMPOSE=(docker compose)
COMPOSE_FILES=(-f docker-compose.yml)

# ---------------------------------------------------------------- 输出
if [ -t 1 ]; then
  C_RED=$'\033[31m'; C_GRN=$'\033[32m'; C_YEL=$'\033[33m'; C_DIM=$'\033[2m'; C_END=$'\033[0m'
else
  C_RED=""; C_GRN=""; C_YEL=""; C_DIM=""; C_END=""
fi

step() { printf '\n%s==>%s %s\n' "$C_GRN" "$C_END" "$*"; }
info() { printf '    %s\n' "$*"; }
warn() { printf '%s[注意]%s %s\n' "$C_YEL" "$C_END" "$*" >&2; }
die()  { printf '%s[失败]%s %s\n' "$C_RED" "$C_END" "$*" >&2; exit 1; }

trap 'code=$?; [ $code -ne 0 ] && printf "\n%s[失败]%s 第 %s 行命令执行失败（退出码 %s）\n" "$C_RED" "$C_END" "$LINENO" "$code" >&2; exit $code' ERR

usage() {
  cat <<'EOF'
Edu 一键部署

用法：
  bash deploy.sh [命令] [选项]

命令：
  up          安装依赖并启动（默认）
  down        停止服务（默认保留数据卷；加 --purge 才删除数据）
  restart     重启
  logs        跟踪日志（Ctrl+C 退出）
  status      查看容器状态、健康检查、内存占用
  update      git pull 后重新构建
  backup      把数据卷打包到 ./backups/，保留最近 7 份
  https       生成并启用 Caddy 配置（必须带 --domain）

选项：
  --port <端口>        宿主机端口，默认 8000
  --domain <域名>      启用 HTTPS（Caddy 自动申请证书，需域名已解析、80/443 放行）
  --email <邮箱>       ACME 通知邮箱（建议填写）
  --key <API Key>      大模型 Key；不填则交互输入，留空即演示模式
  --mode <模式>        检索模式：hybrid（默认）/ bm25 / dense / hybrid_rerank
  --no-build           跳过镜像构建，直接用本地已有镜像启动（CI 用，等价 EDU_NO_BUILD=1）
  --purge              down 时同时删除数据卷（不可恢复）
  -y, --yes            不询问，直接执行
  -h, --help           显示本帮助

示例：
  bash deploy.sh
  bash deploy.sh --port 8080 --key sk-xxxx --mode bm25
  bash deploy.sh --domain edu.example.com --email me@example.com
EOF
}

# ---------------------------------------------------------------- 参数
while [ $# -gt 0 ]; do
  case "$1" in
    up|down|restart|logs|status|update|backup|https) CMD="$1"; shift ;;
    --port)     PORT="${2:?--port 后面要跟端口}"; PORT_GIVEN=1; shift 2 ;;
    --port=*)   PORT="${1#*=}"; PORT_GIVEN=1; shift ;;
    --domain)   DOMAIN="${2:?--domain 后面要跟域名}"; shift 2 ;;
    --domain=*) DOMAIN="${1#*=}"; shift ;;
    --email)    ACME_EMAIL="${2:?--email 后面要跟邮箱}"; shift 2 ;;
    --email=*)  ACME_EMAIL="${1#*=}"; shift ;;
    --key)      API_KEY="${2:?--key 后面要跟 Key}"; shift 2 ;;
    --key=*)    API_KEY="${1#*=}"; shift ;;
    --mode)     MODE="${2:?--mode 后面要跟模式}"; MODE_GIVEN=1; shift 2 ;;
    --mode=*)   MODE="${1#*=}"; MODE_GIVEN=1; shift ;;
    --no-build) NO_BUILD=1; shift ;;
    --purge)    PURGE=1; shift ;;
    -y|--yes)   ASSUME_YES=1; shift ;;
    -h|--help)  usage; exit 0 ;;
    *)          usage >&2; die "未知参数：$1" ;;
  esac
done

if [ "$CMD" = "help" ]; then
  usage
  exit 0
fi

# ---------------------------------------------------------------- 基础工具
env_get() {
  [ -f .env ] || return 0
  sed -n "s/^$1=//p" .env | tail -n 1
}

require_os() {
  [ "$(uname -s)" = "Linux" ] || die "本脚本要在 Linux 服务器上跑。Windows 本机请用 start.bat，或装 Docker Desktop。"
  case "$PORT" in
    ''|*[!0-9]*) die "--port 只接受数字，收到：$PORT" ;;
  esac
  [ "$PORT" -ge 1 ] && [ "$PORT" -le 65535 ] || die "端口超出范围：$PORT"
  case "$MODE" in
    bm25|dense|hybrid|hybrid_rerank) ;;
    *) die "--mode 只能是 bm25 / dense / hybrid / hybrid_rerank，收到：$MODE" ;;
  esac
}

need_root() {
  if [ "$(id -u)" -eq 0 ]; then
    SUDO=""
  elif command -v sudo >/dev/null 2>&1; then
    SUDO="sudo"
  else
    die "需要 root 或 sudo 权限来安装 Docker。"
  fi
}

need_curl() {
  command -v curl >/dev/null 2>&1 && return 0
  info "安装 curl（健康检查与元数据查询要用）"
  $SUDO apt-get install -y curl >/dev/null 2>&1 || warn "curl 装不上，健康检查会跳过。"
}

confirm() {
  [ "$ASSUME_YES" -eq 1 ] && return 0
  [ -t 0 ] || die "当前是非交互环境，需要确认的操作请加 -y。"
  printf '%s [y/N] ' "$1"
  read -r answer
  case "$answer" in [yY]|[yY][eE][sS]) return 0 ;; *) die "已取消。" ;; esac
}

# ---------------------------------------------------------------- Docker
install_docker() {
  command -v docker >/dev/null 2>&1 && return 0

  step "安装 Docker（约 300–500 MB，只有第一次做）"
  if [ ! -t 0 ] || [ "$ASSUME_YES" -eq 1 ]; then
    info "非交互模式，直接安装。"
  else
    confirm "将使用官方脚本安装 Docker CE，继续？"
  fi

  export DEBIAN_FRONTEND=noninteractive
  $SUDO apt-get update -y >/dev/null 2>&1 || true
  need_curl

  if ! $SUDO sh -c 'curl -fsSL https://get.docker.com | sh'; then
    warn "官方脚本失败，改用发行版自带的 docker.io。"
    $SUDO apt-get install -y docker.io docker-compose-v2 || die "Docker 安装失败，请手动安装后重试。"
  fi

  $SUDO systemctl enable --now docker >/dev/null 2>&1 || warn "systemctl 不可用（可能跑在容器里），跳过开机自启。"
  $SUDO usermod -aG docker "${SUDO_USER:-$USER}" >/dev/null 2>&1 || true

  # 国内拉镜像慢：没配置过就补一个，已有 daemon.json 一律不碰
  if [ ! -f /etc/docker/daemon.json ]; then
    $SUDO mkdir -p /etc/docker
    printf '{\n  "registry-mirrors": ["https://docker.m.daocloud.io", "https://dockerproxy.com"]\n}\n' \
      | $SUDO tee /etc/docker/daemon.json >/dev/null
    $SUDO systemctl restart docker >/dev/null 2>&1 || true
    info "已配置镜像加速：/etc/docker/daemon.json"
  fi

  command -v docker >/dev/null 2>&1 || die "Docker 没装上，请手工安装后再跑一次。"
}

# 刚装完 Docker 时当前用户通常还没有权限，本次全程用 sudo 兜住
ensure_docker_access() {
  if docker info >/dev/null 2>&1; then
    DOCKER=(docker)
  elif [ -n "$SUDO" ] && $SUDO docker info >/dev/null 2>&1; then
    DOCKER=("$SUDO" docker)
    warn "当前用户不在 docker 组，本次用 sudo 跑 docker。"
    warn "想永久生效：sudo usermod -aG docker $USER，然后退出重新登录。"
  else
    die "无法访问 Docker 守护进程：sudo systemctl status docker 看看。"
  fi
}

detect_compose() {
  if "${DOCKER[@]}" compose version >/dev/null 2>&1; then
    COMPOSE=("${DOCKER[@]}" compose)
  elif command -v docker-compose >/dev/null 2>&1; then
    COMPOSE=(${SUDO:+$SUDO} docker-compose)
  elif [ -n "$SUDO" ] && $SUDO docker-compose version >/dev/null 2>&1; then
    COMPOSE=(docker-compose)
  else
    die "找不到 docker compose。Ubuntu 上执行：sudo apt-get install -y docker-compose-v2"
  fi
}

# ---------------------------------------------------------------- 资源检查
check_resources() {
  local mem_mb disk_gb arch
  mem_mb="$(awk '/MemTotal/{printf "%d", $2/1024}' /proc/meminfo 2>/dev/null || echo 0)"
  disk_gb="$(df -Pk "$APP_DIR" 2>/dev/null | awk 'NR==2{printf "%d", $4/1048576}' || echo 0)"
  arch="$(uname -m)"

  step "资源检查"
  info "内存 ${mem_mb} MB · 可用磁盘 ${disk_gb} GB · 架构 ${arch}"

  if [ "$mem_mb" -gt 0 ] && [ "$mem_mb" -lt 3500 ]; then
    warn "内存不足 4 GB：拍题 OCR + 向量检索同时加载会 OOM。"
    warn "两条路：① 换 2核4G 机型；② 用 --mode bm25 并删掉 requirements.txt 里 onnxruntime/rapidocr/fastembed 那几行。"
    if [ -t 0 ] && [ "$ASSUME_YES" -eq 0 ]; then
      confirm "内存偏小，仍然继续？"
    fi
  fi

  if [ "$disk_gb" -gt 0 ] && [ "$disk_gb" -lt 5 ]; then
    die "磁盘只剩 ${disk_gb} GB，构建镜像至少需要 5 GB。"
  fi

  if [ "$arch" != "x86_64" ] && [ "$arch" != "amd64" ]; then
    warn "当前架构 $arch：onnxruntime / rapidocr 可能没有对应轮子，OCR 会返回 503，服务本身照常跑。"
  fi
}

check_port() {
  step "端口检查"
  if command -v ss >/dev/null 2>&1 && ss -ltn 2>/dev/null | awk '{print $4}' | grep -qE "[:.]${PORT}$"; then
    if "${DOCKER[@]}" ps --format '{{.Names}}' 2>/dev/null | grep -q '^edu$'; then
      info "端口 $PORT 由本项目占用，将重建容器。"
    else
      die "端口 $PORT 被别的程序占用，换一个：bash deploy.sh --port 8080"
    fi
  else
    info "端口 $PORT 可用。"
  fi
}

# ---------------------------------------------------------------- .env
# 整行重写而不是 sed 替换：Key / URL 里可能出现 | & / 等字符，sed 分隔符会被打穿
set_kv() {
  local key="$1" value="$2" tmp
  [ -f .env ] || : > .env
  tmp="$(mktemp)"
  grep -v "^${key}=" .env > "$tmp" || true
  printf '%s=%s\n' "$key" "$value" >> "$tmp"
  mv "$tmp" .env
}

ensure_kv() {
  local current
  current="$(env_get "$1")"
  [ -n "$current" ] && return 0
  set_kv "$1" "$2"
}

write_env() {
  step "准备 .env"
  if [ ! -f .env ]; then
    {
      echo "# 由 deploy.sh 生成；可手工改，改完 bash deploy.sh restart"
      echo "# 不要提交到仓库（.gitignore 已忽略本文件）"
    } > .env
  fi

  [ -n "$API_KEY" ] || API_KEY="$(env_get EDU_API_KEY)"

  if [ -z "$API_KEY" ] && [ -t 0 ]; then
    printf '    DeepSeek / 兼容接口的 API Key（直接回车 = 演示模式）：'
    read -r API_KEY || true
  fi

  # 端口与检索模式：命令行显式给了就覆盖，否则沿用 .env 里的值
  if [ "$PORT_GIVEN" -eq 1 ]; then
    set_kv EDU_PORT "$PORT"
  else
    ensure_kv EDU_PORT "$PORT"
    PORT="$(env_get EDU_PORT)"
  fi

  if [ "$MODE_GIVEN" -eq 1 ]; then
    set_kv EDU_RETRIEVAL_MODE "$MODE"
  else
    ensure_kv EDU_RETRIEVAL_MODE "$MODE"
  fi

  ensure_kv EDU_BASE_URL "https://api.deepseek.com/v1"
  ensure_kv EDU_MODEL "deepseek-chat"
  # 国内不挂镜像的话，95 MB 的 bge 模型可能卡在下载
  ensure_kv HF_ENDPOINT "https://hf-mirror.com"

  if [ -n "$API_KEY" ]; then
    set_kv EDU_API_KEY "$API_KEY"
    info "已写入 EDU_API_KEY（${API_KEY:0:6}…，共 ${#API_KEY} 位）"
  else
    warn "没有 API Key，服务将以「演示模式」运行（规则生成 + 关键词判分，界面会标注演示）。"
  fi

  chmod 600 .env
  info ".env 已就绪（权限 600，端口 ${PORT}，检索 $(env_get EDU_RETRIEVAL_MODE)）"
}

warn_secret() {
  if [ -f data/settings.json ] && grep -q 'sk-' data/settings.json 2>/dev/null; then
    warn "本机 data/settings.json 里有明文 API Key —— 容器不读它，但别把它打进部署包或仓库。"
  fi
}

# ---------------------------------------------------------------- HTTPS
setup_https() {
  [ -n "$DOMAIN" ] || die "https 需要域名：bash deploy.sh --domain edu.example.com"
  case "$DOMAIN" in
    *[!a-zA-Z0-9.-]*) die "域名格式不对：$DOMAIN" ;;
  esac

  step "配置 HTTPS（Caddy 自动申请证书）"
  mkdir -p deploy

  {
    if [ -n "$ACME_EMAIL" ]; then
      printf '{\n\temail %s\n}\n\n' "$ACME_EMAIL"
    fi
    printf '%s {\n' "$DOMAIN"
    printf '\tencode zstd gzip\n'
    printf '\treverse_proxy edu:8000 {\n'
    printf '\t\t# SSE 必须关掉响应缓冲，否则对话与课堂生成会「憋着不动」\n'
    printf '\t\tflush_interval -1\n'
    printf '\t}\n'
    printf '\theader {\n'
    printf '\t\tStrict-Transport-Security "max-age=31536000; includeSubDomains"\n'
    printf '\t\t-Server\n'
    printf '\t}\n'
    printf '}\n'
  } > deploy/Caddyfile

  cat > docker-compose.https.yml <<'YAML'
# 由 deploy.sh 生成：Caddy 反向代理 + 自动 HTTPS
services:
  caddy:
    image: caddy:2-alpine
    container_name: edu-caddy
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./deploy/Caddyfile:/etc/caddy/Caddyfile:ro
      - caddy-data:/data
      - caddy-config:/config
    depends_on:
      edu:
        condition: service_started

volumes:
  caddy-data:
  caddy-config:
YAML

  COMPOSE_FILES=(-f docker-compose.yml -f docker-compose.https.yml)
  info "已生成 deploy/Caddyfile 与 docker-compose.https.yml"
  warn "证书要求：域名 A 记录指向本机公网 IP，且安全组放行 80 与 443。"
}

# 上次开过 HTTPS 的话，down/restart/status 也要把 caddy 一起管上
reuse_https() {
  [ -f docker-compose.https.yml ] || return 0
  COMPOSE_FILES=(-f docker-compose.yml -f docker-compose.https.yml)
  if [ -z "$DOMAIN" ] && [ -f deploy/Caddyfile ]; then
    DOMAIN="$(sed -n 's/^\([a-zA-Z0-9][a-zA-Z0-9.-]*\) {[[:space:]]*$/\1/p' deploy/Caddyfile | head -n 1)"
  fi
}

# ---------------------------------------------------------------- 启动
build_up() {
  if [ "$NO_BUILD" -eq 1 ]; then
    local image
    image="$("${COMPOSE[@]}" "${COMPOSE_FILES[@]}" config --images 2>/dev/null | head -n 1 || true)"
    if [ -n "$image" ] && ! "${DOCKER[@]}" image inspect "$image" >/dev/null 2>&1; then
      die "本地没有镜像 $image。去掉 --no-build 让脚本自己构建。"
    fi
    step "跳过构建，用本地镜像启动${image:+（$image）}"
    "${COMPOSE[@]}" "${COMPOSE_FILES[@]}" up -d
  else
    step "构建并启动（首次约 8–15 分钟：npm ci + vite build + pip 装 onnxruntime）"
    "${COMPOSE[@]}" "${COMPOSE_FILES[@]}" up -d --build
  fi
  info "容器已拉起，等待健康检查……"
}

wait_health() {
  local i url
  url="http://127.0.0.1:${PORT}/api/health"
  command -v curl >/dev/null 2>&1 || { info "没有 curl，跳过健康检查。"; return 0; }
  for i in $(seq 1 60); do
    if curl -fsS --max-time 3 "$url" >/dev/null 2>&1; then
      info "健康检查通过：$url"
      return 0
    fi
    [ $((i % 6)) -eq 0 ] && info "仍在启动…已等 $((i * 5)) 秒" || true
    sleep 5
  done
  warn "5 分钟内没等到健康响应，最近 40 行日志："
  "${COMPOSE[@]}" "${COMPOSE_FILES[@]}" logs --tail=40 edu || true
  return 1
}

gen_password() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex 8
  elif command -v python3 >/dev/null 2>&1; then
    python3 -c 'import secrets; print(secrets.token_hex(8))'
  else
    head -c 16 /dev/urandom | od -An -tx1 | tr -d ' \n' | cut -c1-16
  fi
}

# 默认账号 demo/demo1234 放在公网等于没有密码，部署完立刻换掉
harden_demo() {
  local base token newpass code old_umask
  base="http://127.0.0.1:${PORT}/api"
  code="$(curl -s -o /tmp/edu_login.json -w '%{http_code}' --max-time 8 \
    -X POST "${base}/teacher/login" -H 'Content-Type: application/json' \
    -d '{"username":"demo","password":"demo1234"}' 2>/dev/null || echo 000)"

  if [ "$code" != "200" ]; then
    info "演示账号已不是默认密码（或已删除），跳过加固。"
    rm -f /tmp/edu_login.json
    return 0
  fi

  token="$(sed -n 's/.*"token"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' /tmp/edu_login.json | head -n 1)"
  rm -f /tmp/edu_login.json
  [ -n "$token" ] || { warn "没解析到 token，请登录界面手动改密码。"; return 0; }

  newpass="$(gen_password)"
  code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 8 \
    -X PUT "${base}/teacher/password" \
    -H 'Content-Type: application/json' -H "Authorization: Bearer $token" \
    -d "{\"old_password\":\"demo1234\",\"new_password\":\"${newpass}\"}" 2>/dev/null || echo 000)"

  if [ "$code" = "200" ]; then
    mkdir -p deploy
    old_umask="$(umask)"
    umask 077
    printf 'teacher=demo\npassword=%s\nurl=http://%s:%s\n生成时间=%s\n' \
      "$newpass" "$(public_ip)" "$PORT" "$(date '+%F %T')" > deploy/credentials.txt
    umask "$old_umask"
    info "默认演示账号密码已改为随机值，见 deploy/credentials.txt"
  else
    warn "改密码失败（HTTP $code），请登录后在「修改密码」里手工处理。"
  fi
}

public_ip() {
  local ip
  command -v curl >/dev/null 2>&1 || { printf '%s' "<服务器公网IP>"; return 0; }
  ip="$(curl -fsS --max-time 2 http://100.100.100.200/latest/meta-data/eipv4 2>/dev/null || true)"
  [ -n "$ip" ] || ip="$(curl -fsS --max-time 4 https://api.ipify.org 2>/dev/null || true)"
  [ -n "$ip" ] || ip="<服务器公网IP>"
  printf '%s' "$ip"
}

summary() {
  local ip url
  ip="$(public_ip)"
  if [ -n "$DOMAIN" ] && [ -f docker-compose.https.yml ]; then
    url="https://${DOMAIN}"
  else
    url="http://${ip}:${PORT}"
  fi

  step "部署完成"
  cat <<EOF
    访问地址   ${url}
    健康检查   http://${ip}:${PORT}/api/health
    数据位置   docker 卷 edu-data（删容器不丢数据）

    常用命令
      bash deploy.sh logs      看日志
      bash deploy.sh status    看状态与内存
      bash deploy.sh backup    备份数据
      bash deploy.sh update    拉代码后重建

    首次使用
      教师端 ${url} → 左侧「教师」
      学生端 ${url} → 「班级」→ 邀请码 / 学号登录
EOF

  if [ -n "$(env_get EDU_API_KEY)" ]; then
    info "模型已配置：$(env_get EDU_MODEL) @ $(env_get EDU_BASE_URL)"
  else
    warn "当前是演示模式：不调模型，判分靠关键词，界面会标注「演示」。填 Key 后 bash deploy.sh restart。"
  fi
  [ -f deploy/credentials.txt ] && info "demo 账号的新密码在 deploy/credentials.txt（保存后请删除该文件）" || true

  if [ -z "$DOMAIN" ]; then
    warn "没有 HTTPS：API Key、学生密码、作业内容在公网上是明文传输，正式演示前建议上域名。"
  fi
}

# ---------------------------------------------------------------- 子命令
cmd_down() {
  step "停止服务"
  if [ "$PURGE" -eq 1 ]; then
    warn "将删除数据卷 edu-data：资料、班级、成绩全部清空，不可恢复。"
    confirm "确认删除？"
    "${COMPOSE[@]}" "${COMPOSE_FILES[@]}" down -v
  else
    "${COMPOSE[@]}" "${COMPOSE_FILES[@]}" down
    info "数据保留在 edu-data 卷里。"
  fi
}

cmd_status() {
  step "容器状态"
  "${COMPOSE[@]}" "${COMPOSE_FILES[@]}" ps
  if curl -fsS --max-time 3 "http://127.0.0.1:${PORT}/api/health" >/dev/null 2>&1; then
    info "健康检查：通过"
    curl -fsS "http://127.0.0.1:${PORT}/api/health" | head -c 600
    printf '\n'
  else
    warn "健康检查：不通"
  fi
  step "资源占用"
  "${DOCKER[@]}" stats --no-stream --format 'table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}' 2>/dev/null || true
}

cmd_backup() {
  local file stamp
  step "备份数据卷"
  mkdir -p backups
  stamp="$(date +%Y%m%d-%H%M%S)"
  file="${APP_DIR}/backups/edu-data-${stamp}.tgz"
  "${DOCKER[@]}" run --rm -v edu-data:/v -v "${APP_DIR}/backups":/out alpine \
    tar czf "/out/edu-data-${stamp}.tgz" -C /v . >/dev/null
  info "已生成 backups/edu-data-${stamp}.tgz（$(du -h "$file" 2>/dev/null | cut -f1)）"
  ls -1t backups/edu-data-*.tgz 2>/dev/null | tail -n +8 | while read -r old; do
    rm -f "$old"
    info "清理旧备份：$(basename "$old")"
  done
}

cmd_update() {
  if [ -d .git ]; then
    step "拉取代码"
    git pull --ff-only
  else
    info "当前目录不是 git 仓库，跳过 git pull。"
  fi
  build_up
  wait_health || true
  "${DOCKER[@]}" image prune -f >/dev/null 2>&1 || true
}

# ---------------------------------------------------------------- 主流程
main() {
  require_os

  # 没显式指定端口时，沿用上次 .env 里的值，避免 .env 与检查口径打架
  if [ "$PORT_GIVEN" -eq 0 ] && [ -f .env ]; then
    local saved_port
    saved_port="$(env_get EDU_PORT)"
    if [ -n "$saved_port" ]; then PORT="$saved_port"; fi
  fi

  case "$CMD" in
    up|restart|https)
      need_root
      install_docker
      ensure_docker_access
      detect_compose
      need_curl
      write_env
      warn_secret
      if [ -n "$DOMAIN" ]; then
        setup_https
      else
        reuse_https
      fi
      [ "$CMD" = "restart" ] || check_resources
      check_port
      if [ "$CMD" = "restart" ]; then
        step "重启并应用 .env 变更（不重新构建）"
        "${COMPOSE[@]}" "${COMPOSE_FILES[@]}" up -d
      else
        build_up
      fi
      if wait_health; then
        harden_demo || true
        summary
      else
        die "启动失败，先看：bash deploy.sh logs"
      fi
      ;;
    down)
      need_root; ensure_docker_access; detect_compose; reuse_https; cmd_down
      ;;
    logs)
      need_root; ensure_docker_access; detect_compose; reuse_https
      "${COMPOSE[@]}" "${COMPOSE_FILES[@]}" logs -f --tail=200 edu
      ;;
    status)
      need_root; ensure_docker_access; detect_compose; reuse_https; cmd_status
      ;;
    backup)
      need_root; ensure_docker_access; detect_compose; reuse_https; cmd_backup
      ;;
    update)
      need_root; install_docker; ensure_docker_access; detect_compose; reuse_https
      cmd_update
      ;;
    *)
      usage >&2; die "未知命令：$CMD"
      ;;
  esac
}

main
