# Edu 打包与部署

| 项 | 内容 |
| --- | --- |
| 版本 | v1.5.0 |
| 适用 | 单机演示 / 校内服务器 / 云主机 |
| 相关 | [接口文档](API.md) · [需求文档](REQUIREMENTS.md) · [项目说明](PROJECT_BRIEF.md) |

---

## 1. 先选方式

| 方式 | 适合场景 | 需要 | 优点 | 限制 |
| --- | --- | --- | --- | --- |
| **A. 源码 zip** | 教师笔记本、校内电脑、答辩现场 | Python 3.10+（可选 Node 仅构建） | 双击即用、可离线、改代码方便 | 手动装依赖；Windows 为主 |
| **B. Docker** | 有 Docker 的服务器、快速复制环境 | Docker 20+ | 环境一致、升级回滚简单 | 镜像需先构建前端；本机未装 Docker，未做构建验证 |
| **C. 云主机 + systemd + Nginx** | 公网访问、多人使用 | Linux、域名（HTTPS 需备案） | 可控、可 HTTPS、可备份 | 需要运维基础 |

> 没有云服务器也能跑：A 方式在校内笔记本/机房的局域网内即可完成一节课的全部演示。公网访问再考虑 C。

---

## 2. 方式 A：源码 zip（推荐给单机/校内）

### 2.1 生成安装包

```bash
# 先确保前端已构建（仓库通常已带 web/dist，可跳过）
cd web && npm install && npm run build && cd ..

# 生成 dist/edu-v1.5.0.zip
.venv\Scripts\python scripts/package.py
# macOS/Linux: .venv/bin/python scripts/package.py
```

产物特点：

- 含 `server/`、`web/dist/`、`scripts/`、`tests/`、`docs/`、`start.bat`、`start.sh`、`Dockerfile`；
- **不含** `data/`、`.venv/`、`web/node_modules/`、`.env`、缓存；
- 当前约 2.8 MB、124 个文件。

> 不要把 `.venv` 打进压缩包：它绑定创建时的绝对路径和 Python 小版本，换机必坏。`start.bat` 会自建。

### 2.2 在 Windows 上运行

1. 解压到任意目录（路径尽量不含中文/空格）；
2. 安装 Python 3.10+（勾选 Add to PATH）；
3. 双击 `start.bat`：
   - 首次自动创建 `.venv`、装依赖（约 1–3 分钟）；
   - 自动选 8000–8049 中的空闲端口；
   - 自动打开浏览器。
4. 教师端：`demo / demo1234`（登录后立即改密）；学生端：教师导入名单后用学号登录。

### 2.3 在 macOS / Linux 上运行

```bash
chmod +x start.sh
./start.sh
```

### 2.4 局域网内给学生用

```bash
# Windows
.venv\Scripts\python -m server.main --host 0.0.0.0 --port 8000 --no-browser
# macOS/Linux
.venv/bin/python -m server.main --host 0.0.0.0 --port 8000 --no-browser
```

- 放行防火墙 8000 端口；
- 学生访问 `http://<电脑局域网IP>:8000`；
- 手机与电脑需在同一网络；
- 仅局域网演示，不要直接映射到公网。

### 2.5 配置与数据

| 项 | 位置/方式 |
| --- | --- |
| 模型配置 | 界面左下角「设置」，或 `.env` 的 `EDU_BASE_URL/EDU_MODEL/EDU_API_KEY` |
| 数据目录 | 默认 `data/`，可用 `EDU_DATA_DIR` 指定 |
| 端口 | `--port` 或 `EDU_PORT` |
| 限流 | `EDU_RATE_LIMIT`（默认 120 次/分钟/IP，0 关闭） |
| 备份 | 复制整个 `data/`（含 `uploads/`、`sessions.json`、`secret.key`） |

---

## 3. 方式 B：Docker

### 3.1 构建

```bash
# 1) 先构建前端（镜像只复制 web/dist）
cd web && npm install && npm run build && cd ..

# 2) 构建镜像
docker build -t edu:1.5.0 .

# 3) 运行
docker run -d --name edu \
  -p 8000:8000 \
  -v "$(pwd)/data:/app/data" \
  --restart unless-stopped \
  edu:1.5.0
```

或使用 compose：

```bash
docker compose up -d --build
docker compose logs -f
```

### 3.2 说明

- 镜像基于 `python:3.12-slim`，只装运行依赖，不含 Node；
- `data/` 通过 volume 持久化；容器删除不丢数据；
- 健康检查：`GET /api/health`；
- 模型 Key 建议在界面配置（写入 `data/settings.json`，优先于环境变量）；
- **注意**：本仓库开发机未安装 Docker，`Dockerfile` / `compose` 已按标准写法提供，但未在本机构建验证；首次在有 Docker 的机器上请先 `docker build` 确认。

---

## 4. 方式 C：云主机 + systemd + Nginx（公网）

### 4.1 服务器规格

| 规模 | 建议 | 说明 |
| --- | --- | --- |
| 1 个班演示 | 2 核 2G / 40G 盘 | 足够；无 GPU 需求 |
| 3–5 个班 | 2 核 4G / 60G | 主要吃内存（解析 PDF、并发 SSE） |
| 10+ 班 | 4 核 8G + 数据库改造 | 先按文档把 JSON 换成 SQLite/Postgres |

带宽 3–5 Mbps 即可（文本为主，附件 20 MB 以内）。

### 4.2 初始化

```bash
# Ubuntu 22.04 为例
sudo apt update
sudo apt install -y python3 python3-venv python3-pip nginx
sudo useradd -r -m -d /opt/edu -s /bin/bash edu
sudo mkdir -p /opt/edu /var/lib/edu
sudo chown -R edu:edu /opt/edu /var/lib/edu
```

把 `dist/edu-v1.5.0.zip` 上传到服务器并解压：

```bash
sudo -u edu unzip edu-v1.5.0.zip -d /opt
sudo mv /opt/edu-1.5.0/* /opt/edu/
```

安装依赖：

```bash
sudo -u edu python3 -m venv /opt/edu/.venv
sudo -u edu /opt/edu/.venv/bin/pip install -r /opt/edu/requirements.txt
```

### 4.3 systemd

```bash
sudo cp /opt/edu/deploy/edu.service /etc/systemd/system/edu.service
sudo systemctl daemon-reload
sudo systemctl enable --now edu
sudo systemctl status edu
```

默认监听 `127.0.0.1:8000`，数据在 `/opt/edu/data`（示例 unit 用 `EDU_DATA_DIR` 可改到 `/var/lib/edu`）。

### 4.4 Nginx + HTTPS

```bash
sudo cp /opt/edu/deploy/nginx.conf.example /etc/nginx/conf.d/edu.conf
# 修改 server_name、证书路径
sudo nginx -t && sudo systemctl reload nginx

# 免费证书
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d edu.example.com
```

关键点（已写进示例）：

- `client_max_body_size 25m`（作业附件 20 MB）；
- `proxy_buffering off`、`proxy_read_timeout 3600s`（SSE 必须，否则实时事件会被攒住）；
- 只暴露 80/443，8000 不对外开放。

### 4.5 云服务器与域名成本（参考价，随活动波动）

| 项 | 参考价 |
| --- | --- |
| 轻量应用服务器 2C2G 3M | 约 60–120 元/月（新用户活动更低） |
| 学生机/开发者套餐 | 约 10–30 元/月（限时） |
| 域名 `.com` / `.cn` | 约 30–80 元/年 |
| ICP 备案 | 免费，约 7–20 个工作日 |
| HTTPS 证书（Let's Encrypt） | 免费 |
| 备份（可选对象存储） | 约 1–5 元/月 |

> 结论：**不需要 GPU**；一台 2C2G 轻量服务器 + 域名即可支撑一个班的公网使用。校内演示完全可以不买服务器。

---

## 5. 数据、备份与升级

### 5.1 数据目录

```text
data/
├─ teachers/ classes/ students/ assignments/ submissions/ quizzes/ lessons/ materials/ chats/
├─ uploads/           学生提交的附件
├─ sessions.json      教师会话（只存 token 哈希）
├─ secret.key         学生令牌 HMAC 密钥
├─ progress.json      本机学习进度
└─ settings.json      模型配置
```

### 5.2 备份

```bash
# 每天 2:00 备份，保留 14 天
0 2 * * * tar czf /var/backups/edu-$(date +\%F).tgz -C /opt/edu data && find /var/backups -name 'edu-*.tgz' -mtime +14 -delete
```

恢复：停服务 → 解压覆盖 `data/` → 启动。

### 5.3 升级与回滚

```bash
# 升级：保留 data，替换程序
sudo systemctl stop edu
sudo mv /opt/edu /opt/edu.bak-$(date +%F)
sudo unzip edu-v1.6.0.zip -d /opt && sudo mv /opt/edu-1.6.0 /opt/edu
sudo cp -r /opt/edu.bak-*/data /opt/edu/data   # 或使用独立 EDU_DATA_DIR
sudo -u edu /opt/edu/.venv/bin/pip install -r /opt/edu/requirements.txt
sudo systemctl start edu
```

回滚：停服务，换回旧目录即可。建议 `EDU_DATA_DIR` 独立于程序目录，升级时不用搬数据。

---

## 6. 安全清单（公网部署必看）

- [ ] 修改 `demo` 账号密码，或删除演示账号；
- [ ] 全站 HTTPS，8000 端口不对公网开放；
- [ ] 教师密码至少 12 位；学生初始密码首次登录后建议更换（当前版本由教师重置）；
- [ ] `EDU_RATE_LIMIT` 保持开启；
- [ ] 定期备份 `data/`，备份文件不入 Web 目录；
- [ ] **不要导入教务系统明文密码**：建议改为"名单只含学号姓名 + 一次性激活码"，或对接学校统一身份；如必须导入，至少加密落盘、导入后删除源文件、限制访问；
- [ ] 面向未成年人时，补充隐私说明与监护人同意流程；
- [ ] 关注 `journalctl -u edu -f` 与磁盘占用（附件会增长）。

---

## 7. 故障排查

| 现象 | 排查 |
| --- | --- |
| 启动后浏览器打不开 | 看命令行实际端口（8000 被占会自动 +1）；检查防火墙 |
| 学生手机打不开 | 服务是否 `--host 0.0.0.0`；是否同一局域网；系统防火墙是否放行 |
| 实时不更新 | Nginx 是否关闭 `proxy_buffering`；浏览器 Network 里 SSE 是否 200 |
| 上传 413 | Nginx `client_max_body_size`；应用限制为资料 10 MB、作业 20 MB |
| 模型 502 | 设置页「测试连接」；检查 Base URL 是否以 `/v1` 结尾、Key、额度 |
| 登录后立刻 401 | 服务重启过？教师 token 已持久化；学生 token 是否带对 |
| 页面还是旧版 | `Ctrl+F5`；确认 `web/dist` 已更新并重启 |
| Docker 构建失败 | 是否先执行了 `npm run build`（镜像需要 `web/dist`） |

---

## 8. 部署验收

```bash
curl -s http://127.0.0.1:8000/api/health
# {"ok":true,"version":"1.5.0","mode":"live",...}

curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/
# 200

# 教师登录
curl -s -X POST http://127.0.0.1:8000/api/teacher/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"demo","password":"demo1234"}'
```

浏览器端再走一遍：教师登录 → 建班 → 导入名单 → 学生登录 → 发作业 → 提交 → 复核 → 导出。

---

## 9. 一页速查

```text
源码包：python scripts/package.py  →  dist/edu-v1.5.0.zip（约 2.8 MB）
Windows：双击 start.bat
Linux：  ./start.sh
Docker： cd web && npm run build && cd .. && docker compose up -d --build
公网：   systemd(127.0.0.1:8000) + Nginx(443, proxy_buffering off) + certbot
数据：   data/（备份、迁移、删除都只动这一个目录）
```
