# syntax=docker/dockerfile:1

# ---------------------------------------------------------------- 1. 前端构建
# 前端在镜像里重新构建，保证 dist 与源码始终一致（提交到仓库的 dist 只是本地产物）。
FROM node:22-alpine AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

# ---------------------------------------------------------------- 2. 运行时
FROM python:3.14-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    EDU_HOST=0.0.0.0 \
    EDU_PORT=8000 \
    EDU_OPEN_BROWSER=0 \
    EDU_DATA_DIR=/app/data

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY server ./server
COPY --from=web /web/dist ./web/dist

# 非 root 运行。数据目录先建好并交给 edu 用户，配合命名卷使用时权限能自然继承。
RUN useradd --create-home --uid 10001 edu \
    && mkdir -p /app/data \
    && chown -R edu:edu /app/data
USER edu

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import os,sys,urllib.request; p=os.environ.get('EDU_PORT','8000'); sys.exit(0 if urllib.request.urlopen(f'http://127.0.0.1:{p}/api/health',timeout=2).status==200 else 1)"

# 与 start.bat 走同一个入口；端口/监听地址由上面的环境变量决定。
CMD ["python", "-m", "server.main"]
