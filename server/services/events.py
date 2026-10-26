"""进程内事件总线与在线名单。

Edu 是单进程应用（uvicorn 默认一个进程），所以「数据变了」只需要在内存里
广播给已经连上的 SSE 订阅者：不需要 Redis、消息队列，也不需要事件持久化。

设计要点：事件只说明「哪个主题变了」，不带业务数据。客户端收到后调用自己
原有的接口重新拉取，因此统计口径、权限过滤、字段裁剪永远只有一份实现。

边界：一旦改成 `--workers > 1` 或多机部署，不同进程之间互相看不到事件，
必须把 EventBus 换成 Redis pub/sub（event 名与前端协议不用改）。
"""
from __future__ import annotations

import asyncio
import time
from collections import defaultdict

_QUEUE_SIZE = 64


class EventBus:
    """topic -> 订阅队列。publish 在事件循环线程里同步调用。"""

    def __init__(self) -> None:
        self._topics: dict[str, set[asyncio.Queue]] = defaultdict(set)
        self._seq = 0

    def subscribe(self, topics: list[str]) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=_QUEUE_SIZE)
        for topic in topics:
            self._topics[topic].add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue, topics: list[str]) -> None:
        for topic in topics:
            room = self._topics.get(topic)
            if not room:
                continue
            room.discard(queue)
            if not room:
                self._topics.pop(topic, None)

    def publish(self, topic: str, event_type: str, **payload: object) -> None:
        self._seq += 1
        event = {
            "seq": self._seq,
            "topic": topic,
            "type": event_type,
            "at": time.time(),
            **payload,
        }
        for queue in list(self._topics.get(topic, ())):
            if queue.full():
                # 慢客户端：丢掉最旧的信号。它收到下一条仍会整体重拉，不会丢状态。
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                pass

    def subscriber_count(self, topic: str) -> int:
        return len(self._topics.get(topic, ()))


class Presence:
    """谁现在开着页面。同一个学生多开标签页按连接数计数。"""

    def __init__(self) -> None:
        self._counts: dict[str, dict[str, int]] = defaultdict(dict)

    def enter(self, class_id: str, student_id: str) -> bool:
        """从离线变成在线时返回 True。"""
        room = self._counts.setdefault(class_id, {})
        count = room.get(student_id, 0) + 1
        room[student_id] = count
        return count == 1

    def leave(self, class_id: str, student_id: str) -> bool:
        """最后一个连接也断开时返回 True。"""
        room = self._counts.get(class_id)
        if not room:
            return False
        count = room.get(student_id, 0) - 1
        if count > 0:
            room[student_id] = count
            return False
        room.pop(student_id, None)
        if not room:
            self._counts.pop(class_id, None)
        return True

    def online(self, class_id: str) -> list[str]:
        return list(self._counts.get(class_id, {}))


bus = EventBus()
presence = Presence()
