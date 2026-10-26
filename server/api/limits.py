"""进程内限流：保护模型调用与上传接口，避免被同一局域网的人刷爆额度。

默认每个 IP 每分钟 120 次「生成类」请求；`EDU_RATE_LIMIT=0` 可关闭（测试用）。
这个实现是单进程内存版的滑动窗口，和项目其它部分一样不引入 Redis。
"""
from __future__ import annotations

import os
import time
from collections import defaultdict, deque

from fastapi import Depends, HTTPException, Request

WINDOW = 60.0
DEFAULT_LIMIT = int(os.environ.get("EDU_RATE_LIMIT", "120") or 0)

_buckets: dict[tuple[str, str], deque] = defaultdict(deque)


def _allow(key: tuple[str, str], limit: int) -> bool:
    now = time.monotonic()
    bucket = _buckets[key]
    while bucket and now - bucket[0] > WINDOW:
        bucket.popleft()
    if len(bucket) >= limit:
        return False
    bucket.append(now)
    return True


def rate_limit(scope: str, limit: int | None = None):
    """返回一个 FastAPI 依赖：超限直接 429。"""

    async def dependency(request: Request) -> None:
        if DEFAULT_LIMIT <= 0:  # 全局关闭（测试或特殊部署）
            return
        allowed = DEFAULT_LIMIT if limit is None else limit
        ip = request.client.host if request.client else "unknown"
        if not _allow((scope, ip), allowed):
            raise HTTPException(status_code=429, detail="请求过于频繁，请稍后再试。")

    return Depends(dependency)
