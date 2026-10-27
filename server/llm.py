"""OpenAI 兼容的流式模型客户端 + 无密钥时的离线演示实现。"""
from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncIterator

import httpx

from .config import Settings
from .config import settings as default_settings

# 超时设置：连接要快，读取要足够长（生成长课堂时可能超过 2 分钟）。
TIMEOUT = httpx.Timeout(connect=15.0, read=300.0, write=60.0, pool=30.0)


class LLMError(RuntimeError):
    """可以直接展示给用户的模型调用错误。"""

    def __init__(self, message: str, status: int = 0) -> None:
        super().__init__(message)
        self.status = status


def parse_json(text: str) -> dict:
    """从模型输出中提取 JSON 对象，容忍代码块和尾随逗号。"""
    raw = (text or "").strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", raw, re.S)
    if fence:
        raw = fence.group(1).strip()
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        raise LLMError("模型没有返回 JSON 结构，请重试。")
    snippet = raw[start:end + 1]
    for candidate in (snippet, re.sub(r",\s*([}\]])", r"\1", snippet)):
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
    raise LLMError("模型返回的 JSON 无法解析，请重试或更换模型。")


def _friendly_error(status: int, detail: str) -> str:
    hint = ""
    try:
        payload = json.loads(detail)
        hint = (payload.get("error") or {}).get("message") or payload.get("message") or ""
    except (ValueError, AttributeError):
        hint = detail.strip()
    hint = hint[:200]
    if status in (401, 403):
        return f"API Key 无效或没有权限（HTTP {status}）。请在「设置」中检查 Key。{hint}"
    if status == 404:
        return f"接口地址或模型名不正确（HTTP 404）。请检查 Base URL 是否以 /v1 结尾，以及模型名。{hint}"
    if status == 429:
        return f"请求过于频繁或额度不足（HTTP 429）。{hint}"
    if status >= 500:
        return f"模型服务暂时异常（HTTP {status}），请稍后重试。{hint}"
    return f"模型调用失败（HTTP {status}）。{hint}"


class LLM:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or default_settings

    @property
    def demo(self) -> bool:
        return self.settings.is_demo

    async def stream(
        self,
        messages: list[dict],
        *,
        temperature: float | None = None,
        max_tokens: int = 1600,
        task: str = "chat",
        context: dict | None = None,
    ) -> AsyncIterator[str]:
        if self.demo:
            text = demo_reply(task, messages, context or {})
            async for piece in _pace(text):
                yield piece
            return

        payload = {
            "model": self.settings.model,
            "messages": messages,
            "temperature": self.settings.temperature if temperature is None else temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
        headers = {
            "Authorization": f"Bearer {self.settings.api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True) as client:
                async with client.stream("POST", self.settings.endpoint(), json=payload, headers=headers) as response:
                    if response.status_code >= 400:
                        body = (await response.aread()).decode("utf-8", "ignore")
                        raise LLMError(_friendly_error(response.status_code, body), response.status_code)
                    got_content = False
                    async for line in response.aiter_lines():
                        line = line.strip()
                        if not line or line.startswith(":"):
                            continue
                        if line.startswith("data:"):
                            line = line[5:].strip()
                        if not line or line == "[DONE]":
                            continue
                        try:
                            event = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        for choice in event.get("choices") or []:
                            delta = choice.get("delta") or {}
                            piece = delta.get("content")
                            if not piece:
                                message = choice.get("message") or {}
                                piece = message.get("content") if choice.get("finish_reason") else None
                            if isinstance(piece, str) and piece:
                                got_content = True
                                yield piece
                    if not got_content:
                        raise LLMError("模型没有返回任何内容，请检查模型名或稍后重试。")
        except httpx.TimeoutException as exc:
            raise LLMError("模型响应超时，请稍后重试或换用更快的模型。") from exc
        except httpx.HTTPError as exc:
            raise LLMError(f"无法连接模型服务（{self.settings.base_url}）。请检查网络、代理或本地模型是否启动。") from exc

    async def complete(
        self,
        messages: list[dict],
        *,
        temperature: float | None = None,
        max_tokens: int = 1600,
        task: str = "chat",
        context: dict | None = None,
    ) -> str:
        parts: list[str] = []
        async for piece in self.stream(
            messages, temperature=temperature, max_tokens=max_tokens, task=task, context=context
        ):
            parts.append(piece)
        return "".join(parts)

    async def json(
        self,
        messages: list[dict],
        *,
        temperature: float | None = 0.3,
        max_tokens: int = 2600,
        task: str,
        context: dict | None = None,
    ) -> dict:
        text = await self.complete(
            messages, temperature=temperature, max_tokens=max_tokens, task=task, context=context
        )
        return parse_json(text)


async def _pace(text: str, size: int = 12, delay: float = 0.012) -> AsyncIterator[str]:
    for index in range(0, len(text), size):
        yield text[index:index + size]
        await asyncio.sleep(delay)


# ===================================================================== 演示模式
def _last_user(messages: list[dict]) -> str:
    for message in reversed(messages):
        if message.get("role") == "user":
            return str(message.get("content", ""))
    return ""


def _demo_notice() -> str:
    return "> 演示模式：尚未配置模型 API Key。下面是本地规则生成的示例输出，用于体验交互流程。\n\n"


def demo_reply(task: str, messages: list[dict], context: dict) -> str:
    if task == "lesson":
        return _demo_lesson(context)
    if task == "quiz":
        return _demo_quiz(context)
    if task == "grade":
        return _demo_grade(context)
    if task == "teacher":
        return _demo_teacher(context)
    if task == "group":
        return _demo_group(context)
    return _demo_tutor(messages, context)


def _excerpt_sentences(sources: list[dict], limit: int = 5) -> list[str]:
    sentences: list[str] = []
    for source in sources:
        text = str(source.get("text") or "")
        for raw_line in re.split(r"\n+", text):
            line = raw_line.strip()
            if not line or line.startswith(("#", "```", "|", ">")):
                continue
            line = re.sub(r"^[\-\*\d\.\s]+", "", line).replace("**", "").strip()
            for sentence in re.split(r"(?<=[。！？!?])", line):
                sentence = sentence.strip()
                if 10 <= len(sentence) <= 90:
                    sentences.append(sentence)
                if len(sentences) >= limit:
                    return sentences
    return sentences


def _demo_tutor(messages: list[dict], context: dict) -> str:
    question = _last_user(messages).strip() or "这个问题"
    sources = context.get("sources") or []
    lines = [_demo_notice()]
    lines.append(f"你问的是「{question}」。")
    if sources:
        sentences = _excerpt_sentences(sources, 2)
        lines.append("\n**资料里可以先用上的线索**\n")
        for index, sentence in enumerate(sentences, 1):
            lines.append(f"> [{index}] {sentence}")
        lines.append("\n**建议的思考路径**\n")
        lines.append("1. 这段话里哪个概念你还不确定？先在纸上用自己的话解释它。")
        lines.append("2. 找材料里支持它的证据，判断是定义、原因还是例子。")
    else:
        lines.append("\n**建议的思考路径**\n")
        lines.append("1. 先写出你对这个主题已知的三件事，再标出最没把握的一件。")
        lines.append("2. 用「是什么 → 为什么 → 怎么用」的顺序拆开它。")
    lines.append("\n**轮到你**：你更想先弄清楚「定义」还是「例子」？告诉我，我们下一步就攻这里。")
    lines.append("\n\n*配置 API Key 后，这里会变成真正的苏格拉底式对话。*")
    return "\n".join(lines)


def _demo_lesson(context: dict) -> str:
    topic = str(context.get("topic") or "未命名主题").strip()
    level = context.get("level") or "beginner"
    minutes = context.get("duration") or 20
    sources = context.get("sources") or []
    sentences = _excerpt_sentences(sources, 6)

    def source_bullets(start: int, count: int, fallback: list[str]) -> list[str]:
        picked = sentences[start:start + count]
        return [s[:46] + ("…" if len(s) > 46 else "") for s in picked] or fallback

    scene_content_1 = source_bullets(0, 3, [
        f"先明确「{topic}」解决什么问题，以及它出现的场景",
        "抓住 2-3 个核心要素，不要一次记住所有细节",
        "用自己的话写下第一版定义，稍后再修正",
    ])
    scene_content_2 = source_bullets(3, 3, [
        f"把「{topic}」拆成「输入 → 过程 → 输出」三段来理解",
        "每个环节配一个具体例子，例子比定义更好记",
        "找出最容易混淆的一对概念，做一次对比",
    ])

    notes_1 = (
        f"同学们，今天我们用 {minutes} 分钟认识「{topic}」。先别急着记结论，"
        "请把注意力放在它要解决的问题上。你可以边听边在纸上写下自己的第一版理解，我们最后再回来对照。"
    )

    lesson = {
        "title": f"{topic}：一堂课抓住核心",
        "summary": f"用 {minutes} 分钟建立「{topic}」的整体框架，并完成一次自我检测。",
        "level": level,
        "objectives": [
            f"能用一句话解释「{topic}」是什么",
            f"能举出一个与「{topic}」有关的真实例子",
            "能识别学习该主题时最常见的误区",
        ],
        "scenes": [
            {
                "type": "cover",
                "title": topic,
                "subtitle": f"{minutes} 分钟迷你课 · 演示模式",
                "bullets": ["核心概念", "结构拆解", "随堂检测"],
            },
            {
                "type": "content",
                "title": "它到底在讲什么",
                "bullets": scene_content_1,
                "notes": notes_1,
                "prompt": f"如果让你用一句话向同学解释「{topic}」，你会怎么说？",
            },
            {
                "type": "content",
                "title": "把它拆开看",
                "bullets": scene_content_2,
                "notes": f"接下来我们拆结构。理解「{topic}」的关键，是分清哪些是条件、哪些是过程、哪些是结果。请边看边给每一层配一个例子。",
                "prompt": "这三个环节里，你觉得哪一层最容易出错？为什么？",
            },
            {
                "type": "discussion",
                "title": "课堂讨论",
                "prompt": f"生活中有哪些现象可以用「{topic}」来解释？请举一个，并说明它对应到哪一层结构。",
                "hints": ["从你熟悉的场景出发", "先说现象，再说对应的概念"],
            },
            {
                "type": "quiz",
                "title": "随堂检测",
                "questions": [
                    {
                        "type": "short",
                        "question": f"请用一句话解释「{topic}」的核心含义。",
                        "answer": f"能说明「{topic}」解决什么问题、由哪些关键要素构成即可。",
                        "explanation": "评分关注是否抓住核心要素，而不是背原话。",
                        "knowledge_point": f"{topic}·核心定义",
                    },
                    {
                        "type": "short",
                        "question": f"举一个「{topic}」在真实场景中的例子，并说明它为什么相关。",
                        "answer": "例子具体，且能指出与主题核心要素的对应关系。",
                        "explanation": "能完成「概念 → 例子 → 对应关系」的迁移即算通过。",
                        "knowledge_point": f"{topic}·应用迁移",
                    },
                ],
            },
            {
                "type": "summary",
                "title": "本课回顾",
                "bullets": [
                    f"「{topic}」要解决的核心问题是什么",
                    "三层结构：条件、过程、结果",
                    "下一步：用你自己的例子复述一遍",
                ],
            },
        ],
    }
    return json.dumps(lesson, ensure_ascii=False)


def _demo_quiz(context: dict) -> str:
    topic = str(context.get("topic") or "本课内容").strip()
    count = int(context.get("count") or 3)
    sources = context.get("sources") or []
    focus = [str(point).strip() for point in (context.get("focus_points") or []) if str(point).strip()][:3]
    variant = int(context.get("variant") or 0)
    sentences = _excerpt_sentences(sources, 8)
    core = "".join(sentences[:2]) or f"能说明「{topic}」要解决的问题和关键要素。"
    detail = "".join(sentences[2:5]) or f"能说出「{topic}」的关键环节及其作用。"
    example = f"例子具体，并能说明它与「{topic}」核心概念的关系。"
    bank = [
        (f"请用自己的话概括「{topic}」的核心含义。", core, f"{topic}·核心定义"),
        (f"根据资料，「{topic}」包含哪些关键环节或影响因素？", detail, f"{topic}·结构理解"),
        (f"举一个具体例子，说明「{topic}」如何在现实中出现。", example, f"{topic}·应用迁移"),
        (f"如果要向低年级同学讲「{topic}」，你会先讲什么？", "先讲直觉和例子，再给定义，最后指出常见误区。", f"{topic}·表达迁移"),
        (f"学习「{topic}」时，你最容易犯的错误是什么？如何自查？", "能说出具体误区，并给出可执行的检查方法。", f"{topic}·元认知"),
    ]
    if variant:
        shift = variant % len(bank)
        bank = bank[shift:] + bank[:shift]
    confusion = f"能指出「{topic}」中两个容易混淆的概念，并各举一个例子。"
    focus_templates = [
        ("针对「{point}」，请用自己的话说清它的含义，并举一个例子。", core),
        ("如果要在课堂上讲「{point}」，你会先讲什么、再讲什么？", detail),
        ("「{point}」最容易和哪个概念混淆？请说明区别。", confusion),
    ]
    for offset, point in enumerate(reversed(focus)):
        template, reference = focus_templates[offset % len(focus_templates)]
        bank.insert(0, (template.format(point=point), reference, point))
    questions = []
    seen: set[str] = set()
    for question, answer, point in bank:
        if question in seen:
            continue
        seen.add(question)
        questions.append({
            "type": "short",
            "question": question,
            "answer": answer,
            "explanation": "演示模式按关键词匹配给分，参考答案仅用于自查。",
            "knowledge_point": point,
        })
        if len(questions) >= count:
            break
    title = f"{topic} · 举一反三（演示）" if context.get("similar") else f"{topic} · 随堂测验（演示）"
    return json.dumps({"title": title, "questions": questions}, ensure_ascii=False)


def _terms(text: str) -> set[str]:
    """用于演示评分的粗粒度词元：中文二元组 + 英文单词。"""
    lowered = re.sub(r"\s+", " ", str(text or "").lower())
    terms = set(re.findall(r"[a-z]{3,}", lowered))
    for run in re.findall(r"[\u4e00-\u9fff]+", lowered):
        terms.update(run[i:i + 2] for i in range(len(run) - 1))
    return terms


def _demo_grade(context: dict) -> str:
    answer = str(context.get("answer") or "").strip()
    reference = str(context.get("reference") or "").strip()
    if not answer:
        return json.dumps({"score": 0, "correct": False, "feedback": "这题还没有作答，先写下你的想法，哪怕只有一句话。", "missing": ["作答内容"]}, ensure_ascii=False)
    reference_terms = _terms(reference)
    answer_terms = _terms(answer)
    overlap = len(reference_terms & answer_terms)
    coverage = overlap / len(reference_terms) if reference_terms else 0.0
    if overlap >= 3:
        score = min(1.0, 0.3 + coverage * 1.4)
    elif overlap >= 1 and len(answer) >= 12:
        score = 0.3
    else:
        score = 0.0
    if len(answer) < 6:
        score = min(score, 0.1)
    score = round(score, 2)
    if score >= 0.65:
        feedback = "抓住了资料中的主要概念，表述也比较清楚。可以再补一个具体例子，让理解更牢固。"
    elif score >= 0.3:
        feedback = "方向对了，覆盖了部分关键点。对照参考答案，把缺失的环节补上一句。"
    elif score > 0:
        feedback = "只沾到少量关键词。建议回到对应资料片段，用自己的话复述一遍再作答。"
    else:
        feedback = "暂时没有匹配到资料中的关键概念。建议先阅读相关片段，再尝试用自己的话回答。"
    return json.dumps({"score": score, "correct": score >= 0.6, "feedback": feedback, "missing": []}, ensure_ascii=False)


def _demo_group(context: dict) -> str:
    agent = context.get("agent") or {}
    name = str(agent.get("name") or "同学")
    role = str(agent.get("role") or "")
    title = str(context.get("title") or "这一页").strip()
    question = str(context.get("question") or "").strip()
    history = context.get("history") or []
    turn = 1 if any(item.get("role") == "assistant" for item in history) else 0
    focus = f"你问的「{question[:36]}」" if question else "这一页"

    if any(word in role for word in ("梳理", "归纳", "总结")):
        if turn:
            return (
                f"我再补一个对比：如果把「{title}」换成一个日常场景，先看条件、再看结果，会更容易判断。"
                "你们觉得用哪个例子最合适？"
            )
        return (
            f"小问刚才问的条件很关键。我试着把「{title}」梳理成两点：一是它要解决的问题，二是它依赖的条件和步骤。"
            "不过我们还没有把它落到一个具体例子上，谁愿意补一个？"
        )
    if any(word in role for word in ("质疑", "反例", "批判")):
        if turn:
            return (
                f"我换个角度质疑一下：如果「{title}」里的前提不成立，刚才的结论还站得住吗？"
                "我们是不是应该先找一个反例？"
            )
        return (
            f"我有一点不同意见：如果题目里的条件换一下，「{title}」的结论可能就不成立了。"
            "我们是不是应该先确认它的边界？比如换一个反例试试。"
        )
    if any(word in role for word in ("追问", "提问", "好奇")):
        if turn:
            return (
                f"顺着你刚才的说法，我想确认一个细节：在「{title}」里，如果关键条件变了，结论会怎样？"
                "谁能先举一个反例？"
            )
        return (
            f"我想先追问一个细节：关于{focus}，在「{title}」里最关键的条件是什么？"
            "如果换成一个更简单的例子，结论还成立吗？"
        )
    return (
        f"我从「{name}」的角度补一个点：这一页讲的是「{title}」，但我还想知道它和前后内容怎么衔接。"
        "你们怎么看？"
    )


def _demo_teacher(context: dict) -> str:
    title = str(context.get("title") or "这一页").strip()
    question = str(context.get("question") or "").strip()
    history = context.get("history") or []
    previous = next(
        (str(item.get("content") or "").strip() for item in reversed(history) if item.get("role") == "user"),
        "",
    )
    lead = "我们接着上一问往下说。 " if previous else ""
    return (
        f"{lead}关于「{title}」，你问的「{question[:50]}」可以先放回这一页的主线：它要解决什么问题、用了什么手段、结果是什么。"
        "把它看成一个环节，而不是孤立结论，会更容易和前后内容连起来。"
        "你能先用自己的例子复述一遍吗？"
    )


llm = LLM()
