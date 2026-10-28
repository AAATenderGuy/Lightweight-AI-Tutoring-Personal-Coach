"""导出：班级成绩 CSV、单次作业明细 CSV、学生个人 HTML 报告。

不引入任何模板引擎，HTML 直接拼接；所有用户输入都经过 html.escape。
"""
from __future__ import annotations

import csv
import html
import io
import time

from .mastery import compute_mastery, mastery_label


def _pct(value: float) -> str:
    return f"{round(max(0.0, min(1.0, float(value))) * 100)}%"


def _score_pct(value: object) -> str:
    try:
        return str(round(float(value) * 100))
    except (TypeError, ValueError):
        return "0"


def _time(ts: object) -> str:
    try:
        stamp = float(ts or 0)
    except (TypeError, ValueError):
        return ""
    if stamp <= 0:
        return ""
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(stamp))


def _cell(value: object) -> str:
    """CSV 单元格：转义 Excel 公式，避免 =/+/−/@ 开头的内容被当成公式执行。"""
    text = str(value if value is not None else "")
    if text[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + text
    return text


def _csv(rows: list[list[str]]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerows([[_cell(cell) for cell in row] for row in rows])
    # Excel 需要 BOM 才能正确识别 UTF-8 中文
    return ("\ufeff" + buffer.getvalue()).encode("utf-8")


def _kind_label(kind: str) -> str:
    return "随堂测验" if kind == "quiz" else "课后作业"


def csv_class_scores(klass: dict, students: list[dict], assignments: list[dict],
                     submissions: list[dict]) -> bytes:
    by_key = {(item.get("assignment_id"), item.get("student_id")): item for item in submissions}
    header = ["学号", "姓名"]
    for assignment in assignments:
        header.append(f"{assignment.get('title')}（{_kind_label(assignment.get('kind', ''))}）")
    header += ["提交数", "应交数", "平均分"]

    rows = [header]
    for student in students:
        row = [str(student.get("number") or ""), str(student.get("name") or "")]
        scores: list[float] = []
        for assignment in assignments:
            submission = by_key.get((assignment["id"], student["id"]))
            if submission:
                row.append(_score_pct(submission.get("score")))
                scores.append(float(submission.get("score") or 0))
            else:
                row.append("未交")
        row += [
            str(len(scores)),
            str(len(assignments)),
            str(round(sum(scores) / len(scores) * 100)) if scores else "",
        ]
        rows.append(row)

    if not students:
        rows.append(["（暂无学生）", "", *["" for _ in assignments], "", "", ""])
    return _csv(rows)


def csv_assignment(assignment: dict, students: list[dict], submissions: list[dict],
                   questions: list[dict]) -> bytes:
    by_student = {str(item.get("student_id")): item for item in submissions}
    header = ["学号", "姓名", "状态", "得分", "答对", "题数", "提交次数", "提交时间"]
    header += [f"Q{index + 1}（{str(question.get('knowledge_point') or '未标注')}）"
               for index, question in enumerate(questions)]
    rows = [header]
    for student in students:
        submission = by_student.get(student["id"])
        row = [str(student.get("number") or ""), str(student.get("name") or "")]
        if submission:
            row += [
                "已提交",
                _score_pct(submission.get("score")),
                str(submission.get("correct_count") or 0),
                str(submission.get("total") or 0),
                str(submission.get("attempts") or 1),
                _time(submission.get("submitted_at")),
            ]
            results = {str(item.get("question_id")): item for item in (submission.get("results") or [])}
            for question in questions:
                result = results.get(str(question.get("id")))
                if not result:
                    row.append("—")
                elif not str(result.get("submitted") or "").strip():
                    row.append("未答")
                else:
                    row.append("√" if result.get("correct") else "×")
        else:
            row += ["未提交", "", "", "", "", ""]
            row += ["—" for _ in questions]
        rows.append(row)

    if not students:
        rows.append(["（暂无学生）", "", "", "", "", "", "", ""])
    return _csv(rows)


# ---------------------------------------------------------------- HTML 报告
REPORT_CSS = """
:root { --ink:#17171a; --ink2:#55554f; --ink3:#86867e; --line:#e2e2db; --accent:#1f6b4c; --soft:#f5f6f2; }
* { box-sizing:border-box; }
body { margin:0; padding:40px 32px 56px; background:#fff; color:var(--ink);
  font:14px/1.7 system-ui,-apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif; }
.wrap { max-width:820px; margin:0 auto; }
.top { display:flex; align-items:flex-start; justify-content:space-between; gap:20px;
  padding-bottom:18px; border-bottom:2px solid var(--ink); }
.brand { font-size:12px; letter-spacing:.16em; text-transform:uppercase; color:var(--ink3); }
h1 { margin:6px 0 2px; font-size:26px; letter-spacing:-.02em; }
.sub { color:var(--ink2); font-size:13px; }
.meta { text-align:right; font-size:12px; color:var(--ink3); line-height:1.8; }
h2 { margin:30px 0 10px; font-size:15px; letter-spacing:.02em; }
h2::before { content:""; display:inline-block; width:3px; height:13px; margin-right:8px;
  background:var(--accent); vertical-align:-2px; }
.grid { display:grid; grid-template-columns:repeat(4,1fr); gap:10px; }
.card { padding:14px 15px; border:1px solid var(--line); border-radius:10px; }
.card .v { font-size:24px; font-weight:650; letter-spacing:-.02em; font-variant-numeric:tabular-nums; }
.card .k { font-size:11.5px; color:var(--ink3); margin-top:1px; }
table { width:100%; border-collapse:collapse; font-size:12.5px; }
th, td { padding:8px 10px; border-bottom:1px solid var(--line); text-align:left; vertical-align:top; }
th { font-size:11px; font-weight:600; color:var(--ink3); letter-spacing:.04em; background:var(--soft); }
td.num, th.num { text-align:right; font-variant-numeric:tabular-nums; }
tr:last-child td { border-bottom:0; }
.tag { display:inline-block; padding:1px 7px; border:1px solid var(--line); border-radius:999px;
  font-size:11px; color:var(--ink2); white-space:nowrap; }
.tag.ok { border-color:#cfe0d6; background:#eef5f1; color:#1c5b41; }
.tag.warn { border-color:#e8d6b8; background:#fdf7ec; color:#8a5a12; }
.tag.bad { border-color:#e8c8c3; background:#fdf1ef; color:#9a2b1f; }
.bar { position:relative; height:6px; min-width:80px; border-radius:999px; background:#ecece5; overflow:hidden; }
.bar > i { position:absolute; inset:0 auto 0 0; display:block; border-radius:999px; background:var(--accent); }
.point { display:grid; grid-template-columns:minmax(120px,1.4fr) 100px 70px 60px; gap:12px; align-items:center;
  padding:9px 0; border-bottom:1px solid var(--line); font-size:12.5px; }
.point:last-child { border-bottom:0; }
.point b { font-weight:600; overflow-wrap:anywhere; }
.note { padding:12px 14px; border-left:2px solid var(--accent); background:#f6faf8; border-radius:0 8px 8px 0;
  font-size:12.5px; color:#1c4a37; line-height:1.7; }
.note + .note { margin-top:8px; }
.wrong { padding:11px 0; border-bottom:1px solid var(--line); font-size:12.5px; }
.wrong:last-child { border-bottom:0; }
.wrong .q { font-weight:500; }
.wrong .a { color:var(--ink2); margin-top:3px; }
.wrong .a em { font-style:normal; color:var(--accent); }
.foot { margin-top:34px; padding-top:14px; border-top:1px solid var(--line);
  font-size:11px; color:var(--ink3); display:flex; justify-content:space-between; gap:12px; }
.empty { padding:18px; border:1px dashed var(--line); border-radius:10px; color:var(--ink3); font-size:12.5px; }
@media print {
  body { padding:0; }
  .wrap { max-width:none; }
  h2 { break-after:avoid; }
  table, .point, .wrong { break-inside:avoid; }
}
@media (max-width:640px) {
  body { padding:24px 16px 40px; }
  .grid { grid-template-columns:1fr 1fr; }
  .point { grid-template-columns:1fr 90px; }
  .point > :nth-child(3), .point > :nth-child(4) { display:none; }
  .top { flex-direction:column; }
  .meta { text-align:left; }
}
"""


def _e(value: object) -> str:
    return html.escape(str(value or ""))


def html_student_report(*, student: dict, klass: dict, teacher_name: str,
                        assignments: list[dict], submissions: list[dict],
                        timeline: list[dict] | None = None) -> str:
    by_assignment = {str(item.get("assignment_id")): item for item in submissions}
    ordered_submissions = sorted(submissions, key=lambda item: float(item.get("submitted_at") or 0))

    scores = [float(item.get("score") or 0) for item in ordered_submissions]
    avg = sum(scores) / len(scores) if scores else 0.0
    completion = len(submissions) / len(assignments) if assignments else 0.0
    best = max(scores) if scores else 0.0

    points: dict[str, dict] = {}
    for submission in ordered_submissions:
        for result in submission.get("results") or []:
            name = str(result.get("knowledge_point") or "未标注知识点")[:60]
            entry = points.setdefault(name, {"scores": [], "wrong": 0, "total": 0, "questions": []})
            entry["scores"].append(float(result.get("score") or 0))
            entry["total"] += 1
            if not result.get("correct"):
                entry["wrong"] += 1
                entry["questions"].append({
                    "question": result.get("question") or "",
                    "submitted": result.get("submitted") or "",
                    "correct_answer": result.get("correct_answer") or "",
                    "explanation": result.get("explanation") or "",
                    "options": result.get("options") or [],
                    "correct_index": result.get("correct_index"),
                })

    point_rows = []
    for name, entry in points.items():
        score = compute_mastery(entry["scores"])
        point_rows.append({
            "name": name,
            "mastery": score,
            "label": mastery_label(score),
            "wrong": entry["wrong"],
            "total": entry["total"],
            "questions": entry["questions"],
        })
    point_rows.sort(key=lambda item: item["mastery"])

    assignment_rows = []
    for assignment in sorted(assignments, key=lambda item: -float(item.get("created_at") or 0)):
        submission = by_assignment.get(str(assignment.get("id")))
        if submission:
            state = "已提交"
            state_class = "ok"
            score_text = _pct(submission.get("score") or 0)
            when = _time(submission.get("submitted_at"))
        elif assignment.get("closed") or (float(assignment.get("due_at") or 0) and float(assignment.get("due_at")) < time.time()):
            state = "未提交（已截止）"
            state_class = "bad"
            score_text = "—"
            when = ""
        else:
            state = "待完成"
            state_class = "warn"
            score_text = "—"
            when = ""
        assignment_rows.append({
            "title": assignment.get("title") or "未命名作业",
            "kind": _kind_label(assignment.get("kind") or ""),
            "state": state,
            "state_class": state_class,
            "score": score_text,
            "when": when,
        })

    notes = []
    missing = [row["title"] for row in assignment_rows if row["state"].startswith("未提交")]
    if missing:
        notes.append(f"有 {len(missing)} 份作业未提交：{('、'.join(missing[:4]))}"
                     f"{' 等' if len(missing) > 4 else ''}。建议先补交，再回看错题。")
    weak = [row for row in point_rows if row["total"] and row["mastery"] < 0.7]
    if weak:
        notes.append("需要巩固的知识点：" + "、".join(
            f"{row['name']}（{_pct(row['mastery'])}）" for row in weak[:4]
        ) + "。可以在「举一反三」里做同知识点的变式题。")
    if not notes:
        notes.append("完成度和正确率都不错，可以尝试更高难度的变式题，或把知识点讲给同学听。")

    wrong_items = []
    for row in point_rows:
        for question in row["questions"]:
            if len(wrong_items) >= 10:
                break
            answer = question["correct_answer"]
            if question["options"] and isinstance(question["correct_index"], int):
                index = question["correct_index"]
                if 0 <= index < len(question["options"]):
                    answer = f"{'ABCDEF'[index]}. {question['options'][index]}"
            wrong_items.append({
                "question": question["question"],
                "point": row["name"],
                "submitted": question["submitted"] or "未作答",
                "answer": answer or "（未提供）",
                "explanation": question["explanation"],
            })

    if timeline:
        timeline_rows = "".join(
            '<tr><td>{when}</td><td><span class="tag {cls}">{label}</span></td>'
            '<td>{text}</td><td class="num">{score}</td></tr>'.format(
                when=_time(item.get("ts")),
                cls="ok" if item.get("kind") in ("quiz", "assignment") else "warn",
                label=_e(item.get("label") or "记录"),
                text=_e(item.get("summary") or item.get("topic") or ""),
                score=_pct(item["score"]) if item.get("score") is not None else "—",
            )
            for item in timeline
        )
        timeline_html = (
            '<table><thead><tr><th>时间</th><th>类型</th><th>内容</th>'
            '<th class="num">得分</th></tr></thead><tbody>'
            + timeline_rows + "</tbody></table>"
        )
    else:
        timeline_html = '<div class="empty">还没有学习轨迹记录。</div>'

    generated = time.strftime("%Y-%m-%d %H:%M")

    if assignment_rows:
        body_rows = "".join(
            '<tr><td>{title}</td><td>{kind}</td><td><span class="tag {cls}">{state}</span></td>'
            '<td class="num">{score}</td><td>{when}</td></tr>'.format(
                title=_e(row["title"]), kind=_e(row["kind"]), cls=row["state_class"],
                state=_e(row["state"]), score=row["score"], when=_e(row["when"]),
            )
            for row in assignment_rows
        )
        assignment_html = (
            '<table><thead><tr><th>作业</th><th>类型</th><th>状态</th>'
            '<th class="num">得分</th><th>提交时间</th></tr></thead><tbody>'
            + body_rows + "</tbody></table>"
        )
    else:
        assignment_html = '<div class="empty">还没有布置过作业。</div>'

    if point_rows:
        point_html = "".join(
            '<div class="point"><b>{name}</b><div class="bar"><i style="width:{width}"></i></div>'
            '<span>{width}</span><span class="tag {cls}">{label}</span></div>'.format(
                name=_e(row["name"]), width=_pct(row["mastery"]),
                cls="ok" if row["mastery"] >= 0.85 else ("warn" if row["mastery"] >= 0.6 else "bad"),
                label=_e(row["label"]),
            )
            for row in point_rows
        )
    else:
        point_html = '<div class="empty">还没有作答记录。</div>'

    if wrong_items:
        wrong_html = "".join(
            '<div class="wrong"><div class="q">{index}. {question}</div>'
            '<div class="a">知识点：{point} · 你的作答：{submitted} · 正确答案：<em>{answer}</em></div>'
            '{explain}</div>'.format(
                index=index, question=_e(item["question"]), point=_e(item["point"]),
                submitted=_e(item["submitted"]), answer=_e(item["answer"]),
                explain=('<div class="a">' + _e(item["explanation"]) + "</div>") if item["explanation"] else "",
            )
            for index, item in enumerate(wrong_items, 1)
        )
    else:
        wrong_html = '<div class="empty">没有错题，保持住。</div>'

    note_html = "".join('<div class="note">' + _e(note) + "</div>" for note in notes)

    head = (
        "<!doctype html>\n<html lang=\"zh-CN\"><head><meta charset=\"utf-8\"/>\n"
        '<meta name="viewport" content="width=device-width, initial-scale=1"/>\n'
        "<title>{name} · 学习报告</title>\n<style>{css}</style></head>\n<body><div class=\"wrap\">\n"
        '  <div class="top">\n    <div>\n'
        '      <div class="brand">Edu · 轻量级 AI 教学系统</div>\n'
        "      <h1>{name} 的学习报告</h1>\n"
        '      <div class="sub">{klass} · 学号 {number} · 任课教师 {teacher}</div>\n'
        "    </div>\n"
        '    <div class="meta">生成时间<br/>{generated}<br/>数据来源：班级作业记录</div>\n'
        "  </div>\n\n"
    ).format(
        name=_e(student.get("name")), css=REPORT_CSS, klass=_e(klass.get("name")),
        number=_e(student.get("number") or "未填写"), teacher=_e(teacher_name), generated=generated,
    )

    summary = (
        '  <h2>总体表现</h2>\n  <div class="grid">\n'
        f'    <div class="card"><div class="v">{_pct(completion)}</div><div class="k">作业完成率（{len(submissions)}/{len(assignments)}）</div></div>\n'
        f'    <div class="card"><div class="v">{_pct(avg)}</div><div class="k">平均得分</div></div>\n'
        f'    <div class="card"><div class="v">{_pct(best)}</div><div class="k">单次最高</div></div>\n'
        f'    <div class="card"><div class="v">{len(point_rows)}</div><div class="k">涉及知识点</div></div>\n'
        "  </div>\n\n"
    )

    tail = (
        "\n  <h2>下一步建议</h2>\n  " + note_html + "\n\n"
        '  <div class="foot"><span>Edu · 本报告由作业记录自动生成，掌握度按最近表现加权计算。</span>'
        "<span>可在浏览器中「打印 → 另存为 PDF」。</span></div>\n</div></body></html>"
    )

    return (
        head + summary
        + "  <h2>作业明细</h2>\n  " + assignment_html + "\n\n"
        + "  <h2>知识点掌握度</h2>\n  " + point_html + "\n\n"
        + "  <h2>学习轨迹</h2>\n  " + timeline_html + "\n\n"
        + "  <h2>错题回顾</h2>\n  " + wrong_html + "\n"
        + tail
    )


# ---------------------------------------------------------------- 整班成绩报告
# 纯 CSS + 内联 SVG 画图，不引用任何外部脚本与字体，离线可看、打印保真。
CLASS_EXTRA_CSS = """
.wrap { max-width:940px; }
.lede { margin:2px 0 0; color:var(--ink2); font-size:13px; }
.kpis { display:grid; grid-template-columns:repeat(6,1fr); gap:9px; margin-top:18px; }
.kpi { padding:13px 14px; border:1px solid var(--line); border-radius:10px; background:#fff; }
.kpi .v { font-size:22px; font-weight:650; letter-spacing:-.02em; font-variant-numeric:tabular-nums; line-height:1.2; }
.kpi .v small { font-size:12px; font-weight:500; color:var(--ink3); margin-left:1px; }
.kpi .v.low { color:#9a2b1f; }
.kpi .k { font-size:11px; color:var(--ink3); margin-top:2px; }

/* 成绩分布柱状图 */
.hist { display:flex; align-items:flex-end; gap:14px; height:206px; padding:0 6px;
  border-bottom:1px solid var(--line); }
.hist .col { flex:1; display:flex; flex-direction:column; align-items:center;
  justify-content:flex-end; gap:5px; }
.hist .cnt { font-size:12px; font-weight:600; color:var(--ink2); font-variant-numeric:tabular-nums; }
.hist .bar-c { width:100%; max-width:96px; border-radius:7px 7px 0 0; }
.hist .cap { font-size:11px; color:var(--ink3); padding-top:7px; white-space:nowrap; }
.b-ex { background:#1f6b4c; } .b-gd { background:#4a9473; }
.b-md { background:#b58c33; } .b-ps { background:#c9763c; } .b-fl { background:#b54a3d; }
.hist-note { font-size:11.5px; color:var(--ink3); margin-top:8px; }

/* 通用横向条 */
.track { position:relative; height:7px; border-radius:999px; background:#ecece5; overflow:hidden; }
.track > i { position:absolute; inset:0 auto 0 0; border-radius:999px; background:var(--accent); }
.track > i.b-ex { background:#1f6b4c; } .track > i.b-gd { background:#4a9473; }
.track > i.b-md { background:#b58c33; } .track > i.b-ps { background:#c9763c; }
.track > i.b-fl { background:#b54a3d; }
.track > i.b-no { background:#c9c9c0; }

/* 排名 */
.rank { display:grid; grid-template-columns:26px minmax(84px,150px) 1fr 46px;
  gap:11px; align-items:center; padding:7px 0; border-bottom:1px solid #f0f0ea; font-size:12.5px; }
.rank:last-child { border-bottom:0; }
.rank .idx { font-size:11px; color:var(--ink3); font-variant-numeric:tabular-nums; text-align:right; }
.rank .idx.top { color:#1f6b4c; font-weight:700; }
.rank .nm { font-weight:500; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.rank .nm em { font-style:normal; color:var(--ink3); font-size:11px; margin-left:5px; }
.rank .vl { text-align:right; font-variant-numeric:tabular-nums; font-weight:600; }

/* 作业完成情况 */
.done-row { display:grid; grid-template-columns:22px minmax(120px,1.6fr) 76px 96px 52px;
  gap:10px; align-items:center; padding:8px 0; border-bottom:1px solid #f0f0ea; font-size:12.5px; }
.done-row:last-child { border-bottom:0; }
.done-row .no { font-size:11px; color:var(--ink3); font-variant-numeric:tabular-nums; }
.done-row .tt { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.done-row .rt { font-size:11.5px; color:var(--ink2); font-variant-numeric:tabular-nums; }
.done-row .av { text-align:right; font-variant-numeric:tabular-nums; font-weight:600; }
.done-row .av.ex { color:#14563c; } .done-row .av.gd { color:#1f5f45; }
.done-row .av.md { color:#7a5a13; } .done-row .av.ps { color:#8a4a1c; }
.done-row .av.fl { color:#8f2a1f; }

/* 成绩矩阵 */
.matrix { font-size:12px; }
.matrix th, .matrix td { padding:6px 7px; }
.matrix th.sticky, .matrix td.sticky { position:sticky; left:0; background:#fff; z-index:1; }
.matrix thead th.sticky { background:var(--soft); }
.matrix-scroll { overflow-x:auto; border:1px solid var(--line); border-radius:10px; }
.matrix-scroll table { min-width:100%; }
.matrix th.rot { max-width:74px; }
.matrix th.rot span { display:block; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.cell { display:inline-block; min-width:30px; padding:2px 6px; border-radius:6px;
  font-variant-numeric:tabular-nums; font-weight:600; }
.c-ex { background:#dcefe4; color:#14563c; }
.c-gd { background:#e8f3ec; color:#1f5f45; }
.c-md { background:#fbf3e0; color:#7a5a13; }
.c-ps { background:#fbeade; color:#8a4a1c; }
.c-fl { background:#fae4e0; color:#8f2a1f; }
.c-no { background:#f1f1eb; color:#a0a098; font-weight:500; }

/* 薄弱知识点 */
.weak-row { display:grid; grid-template-columns:minmax(120px,1.5fr) 1fr 58px 64px;
  gap:12px; align-items:center; padding:8px 0; border-bottom:1px solid #f0f0ea; font-size:12.5px; }
.weak-row:last-child { border-bottom:0; }
.weak-row .pt { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.weak-row .rt { text-align:right; font-variant-numeric:tabular-nums; font-weight:600; }

/* 趋势折线 */
.chart-box { border:1px solid var(--line); border-radius:10px; padding:10px 12px 2px; margin-top:4px; }
.trend { width:100%; height:auto; display:block; }
.trend .gl { stroke:#eaeae3; stroke-width:1; }
.trend .gt { fill:#a2a29a; font-size:10.5px; }
.trend .gd { fill:#1f6b4c; }
.trend .ln { fill:none; stroke:#1f6b4c; stroke-width:2.2; stroke-linejoin:round; stroke-linecap:round; }
.trend .ar { fill:#1f6b4c; opacity:.09; }
.sec-note { margin:6px 0 0; font-size:11.5px; color:var(--ink3); }
.muted { color:var(--ink3); font-size:11px; }

@media print {
  .kpis { grid-template-columns:repeat(6,1fr); }
  .matrix-scroll { overflow:visible; }
  .rank, .done-row, .weak-row { break-inside:avoid; }
  .hist { break-inside:avoid; }
}
@media (max-width:760px) {
  .kpis { grid-template-columns:repeat(2,1fr); }
  .rank { grid-template-columns:22px minmax(70px,1fr) 1fr 40px; }
  .done-row { grid-template-columns:20px minmax(90px,1fr) 60px 50px; }
  .done-row .track { display:none; }
  .weak-row { grid-template-columns:1fr 58px; }
  .weak-row .track, .weak-row .cnt { display:none; }
}
"""

BANDS = (
    ("0-59", 0.00, 0.60, "fl"),
    ("60-69", 0.60, 0.70, "ps"),
    ("70-79", 0.70, 0.80, "md"),
    ("80-89", 0.80, 0.90, "gd"),
    ("90-100", 0.90, 1.01, "ex"),
)


def _band_class(score: float) -> str:
    for _label, low, high, css in BANDS:
        if low <= score < high:
            return css
    return "fl"


def _avg(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _trend_svg(rows: list[dict]) -> str:
    """班级平均分随作业序号变化的折线图。rows 按时间升序。"""
    if len(rows) < 2:
        return ""
    width, height = 720, 196
    left, right, top, bottom = 34, 16, 12, 26
    plot_w = width - left - right
    plot_h = height - top - bottom
    count = len(rows)
    step = plot_w / (count - 1)

    def y_of(value: float) -> float:
        value = max(0.0, min(1.0, float(value)))
        return top + (1.0 - value) * plot_h

    points = [(left + index * step, y_of(row["avg"])) for index, row in enumerate(rows)]
    polyline = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
    area = f"{left:.1f},{top + plot_h:.1f} {polyline} {left + plot_w:.1f},{top + plot_h:.1f}"

    grid = "".join(
        f'<line class="gl" x1="{left}" y1="{y_of(level):.1f}" '
        f'x2="{width - right}" y2="{y_of(level):.1f}"/>'
        f'<text class="gt" x="{left - 8}" y="{y_of(level) + 3.5:.1f}" '
        f'text-anchor="end">{int(round(level * 100))}</text>'
        for level in (1.0, 0.75, 0.5, 0.25, 0.0)
    )
    dots = "".join(f'<circle class="gd" cx="{x:.1f}" cy="{y:.1f}" r="3.4"/>' for x, y in points)
    skip = 1 if count <= 14 else 2
    labels = "".join(
        f'<text class="gt" x="{x:.1f}" y="{height - 7}" text-anchor="middle">{index + 1}</text>'
        for index, (x, _y) in enumerate(points) if index % skip == 0
    )
    return (
        f'<svg class="trend" viewBox="0 0 {width} {height}" '
        f'preserveAspectRatio="xMidYMid meet" role="img" aria-label="班级平均分趋势">'
        f"{grid}"
        f'<polygon class="ar" points="{area}"/>'
        f'<polyline class="ln" points="{polyline}"/>'
        f"{dots}{labels}</svg>"
    )


def html_class_report(*, klass: dict, teacher_name: str, students: list[dict],
                      assignments: list[dict], submissions: list[dict]) -> str:
    """整班成绩报告：概览指标 + 分布图 + 趋势图 + 排名 + 成绩矩阵 + 薄弱知识点。"""
    by_key = {
        (str(item.get("assignment_id")), str(item.get("student_id"))): item
        for item in submissions
    }
    ordered = sorted(assignments, key=lambda item: float(item.get("created_at") or 0))
    roster = len(students)

    # 每份作业的提交与均分
    assignment_rows = []
    for index, assignment in enumerate(ordered, 1):
        rows = [item for item in submissions if str(item.get("assignment_id")) == assignment["id"]]
        scores = [float(item.get("score") or 0) for item in rows]
        assignment_rows.append({
            "no": index,
            "title": assignment.get("title") or "未命名作业",
            "kind": _kind_label(assignment.get("kind") or ""),
            "submitted": len(rows),
            "total": roster,
            "avg": _avg(scores),
            "rate": (len(rows) / roster) if roster else 0.0,
            "due": float(assignment.get("due_at") or 0),
        })

    # 每位学生的逐次得分
    student_rows = []
    for student in students:
        scores = []
        cells = []
        for assignment in ordered:
            submission = by_key.get((str(assignment["id"]), str(student["id"])))
            if submission:
                value = float(submission.get("score") or 0)
                scores.append(value)
                cells.append({"score": value, "cls": _band_class(value), "text": _score_pct(value)})
            else:
                cells.append({"score": None, "cls": "no", "text": "—"})
        student_rows.append({
            "id": student["id"],
            "name": student.get("name") or "未命名",
            "number": str(student.get("number") or ""),
            "scores": scores,
            "cells": cells,
            "submitted": len(scores),
            "avg": _avg(scores) if scores else None,
        })

    participated = [row for row in student_rows if row["avg"] is not None]
    ranked = sorted(participated, key=lambda row: -row["avg"])
    class_avg = _avg([float(item.get("score") or 0) for item in submissions])
    total_slots = roster * len(ordered)
    submit_rate = (len(submissions) / total_slots) if total_slots else 0.0
    best = max((row["avg"] for row in participated), default=0.0)
    worst = min((row["avg"] for row in participated), default=0.0)

    # 分布：按学生平均分统计人数
    band_counts = []
    for label, low, high, css in BANDS:
        count = len([row for row in participated if low <= row["avg"] < high])
        band_counts.append({"label": label, "count": count, "css": css})
    peak = max((item["count"] for item in band_counts), default=0) or 1

    # 知识点错误率
    points: dict[str, dict] = {}
    for submission in submissions:
        for result in submission.get("results") or []:
            name = str(result.get("knowledge_point") or "未标注知识点")[:40]
            entry = points.setdefault(name, {"total": 0, "wrong": 0})
            entry["total"] += 1
            if not result.get("correct"):
                entry["wrong"] += 1
    weak_points = [
        {
            "name": name,
            "total": entry["total"],
            "wrong": entry["wrong"],
            "rate": (entry["wrong"] / entry["total"]) if entry["total"] else 0.0,
        }
        for name, entry in points.items() if entry["wrong"]
    ]
    weak_points.sort(key=lambda item: (-item["rate"], -item["wrong"]))
    weak_points = weak_points[:8]

    generated = time.strftime("%Y-%m-%d %H:%M")
    class_name = str(klass.get("name") or "班级")
    subject = str(klass.get("subject") or "").strip()
    grade = str(klass.get("grade") or "").strip()
    meta_parts = [part for part in (grade, subject) if part]
    if teacher_name:
        meta_parts.append("任课教师 " + str(teacher_name))
    meta_text = " · ".join(meta_parts) or "班级整体表现"

    # ---- 头部
    head = (
        "<!doctype html>\n<html lang=\"zh-CN\"><head><meta charset=\"utf-8\"/>\n"
        '<meta name="viewport" content="width=device-width, initial-scale=1"/>\n'
        f"<title>{_e(class_name)} · 成绩报告</title>\n<style>{REPORT_CSS + CLASS_EXTRA_CSS}</style></head>\n<body><div class=\"wrap\">\n"
        '  <div class="top">\n    <div>\n'
        '      <div class="brand">Edu · 轻量级 AI 教学系统</div>\n'
        f"      <h1>{_e(class_name)} 成绩报告</h1>\n"
        f'      <div class="sub">{_e(meta_text)}</div>\n'
        "    </div>\n"
        f'    <div class="meta">生成时间<br/>{generated}<br/>数据来源：班级作业记录</div>\n'
        "  </div>\n\n"
    )

    # ---- 指标卡
    kpis = (
        '  <div class="kpis">\n'
        '    <div class="kpi"><div class="v">{students}</div><div class="k">学生人数</div></div>\n'
        '    <div class="kpi"><div class="v">{assignments}</div><div class="k">作业份数</div></div>\n'
        '    <div class="kpi"><div class="v">{rate}</div><div class="k">提交率</div></div>\n'
        '    <div class="kpi"><div class="v">{avg}<small>分</small></div><div class="k">班级平均</div></div>\n'
        '    <div class="kpi"><div class="v">{best}<small>分</small></div><div class="k">最高均分</div></div>\n'
        '    <div class="kpi"><div class="v low">{worst}<small>分</small></div><div class="k">最低均分</div></div>\n'
        "  </div>\n\n"
    ).format(
        students=roster, assignments=len(ordered), rate=_pct(submit_rate),
        avg=_pct(class_avg), best=_pct(best), worst=_pct(worst) if participated else "—",
    )

    # ---- 成绩分布
    if participated:
        columns = "".join(
            '<div class="col"><span class="cnt">{count}</span>'
            '<div class="bar-c b-{css}" style="height:{height}px"></div>'
            '<span class="cap">{label}</span></div>'.format(
                count=item["count"], css=item["css"], label=item["label"],
                height=0 if not item["count"] else max(6, round(item["count"] / peak * 132)),
            )
            for item in band_counts
        )
        hist_html = (
            '  <div class="hist">' + columns + "</div>\n"
            '  <p class="hist-note">横轴按分数段从低到高排列，柱高代表该分数段的人数；'
            "统计口径是每位学生的<b>平均得分</b>，不是单次成绩。</p>\n"
        )
    else:
        hist_html = '<div class="empty">还没有学生提交作业，暂时没有可统计的成绩。</div>\n'

    # ---- 趋势
    trend_html = ""
    if len([row for row in assignment_rows if row["submitted"]]) >= 2:
        trend_rows = [row for row in assignment_rows if row["submitted"]]
        trend_html = (
            '  <h2>平均分趋势</h2>\n  <div class="chart-box">'
            + _trend_svg(trend_rows)
            + '</div>\n  <p class="sec-note">横轴为作业序号（与下表「#」列对应），'
            "纵轴为全班平均分。</p>\n\n"
        )

    # ---- 作业完成情况
    if assignment_rows:
        done_html = "".join(
            '<div class="done-row"><span class="no">{no}</span>'
            '<span class="tt" title="{title}">{title}</span>'
            '<span class="rt">{submitted}/{total} 人</span>'
            '<div class="track"><i style="width:{width}"></i></div>'
            '<span class="av {css}">{avg}</span></div>'.format(
                no=row["no"], title=_e(row["title"]), submitted=row["submitted"],
                total=row["total"], width=_pct(row["rate"]),
                css=_band_class(row["avg"]) if row["submitted"] else "",
                avg=_pct(row["avg"]) if row["submitted"] else "—",
            )
            for row in assignment_rows
        )
        done_html += (
            '\n  <p class="sec-note">条形长度表示提交率，右侧数字为该次作业的全班平均分'
            "（颜色由绿到红表示由高到低）。</p>"
        )
    else:
        done_html = '<div class="empty">还没有布置过作业。</div>'

    # ---- 学生排名
    if ranked:
        rank_html = "".join(
            '<div class="rank"><span class="idx{top}">{index}</span>'
            '<span class="nm">{name}{number}</span>'
            '<div class="track"><i class="b-{css}" style="width:{width}"></i></div>'
            '<span class="vl">{avg}</span></div>'.format(
                top=" top" if index <= 3 else "",
                index=index, name=_e(row["name"]),
                number=("<em>" + _e(row["number"]) + "</em>") if row["number"] else "",
                width=_pct(row["avg"]), css=_band_class(row["avg"]), avg=_pct(row["avg"]),
            )
            for index, row in enumerate(ranked, 1)
        )
        idle = len(student_rows) - len(ranked)
        rank_note = (
            f'<p class="sec-note">共 {len(ranked)} 名学生有提交记录；'
            f"另有 {idle} 人尚未提交任何作业，未参与排名。</p>"
        ) if idle else (
            f'<p class="sec-note">共 {len(ranked)} 名学生，按平均得分从高到低排列。</p>'
        )
    else:
        rank_html = '<div class="empty">还没有学生提交作业。</div>'
        rank_note = ""

    # ---- 成绩矩阵
    if ordered and student_rows:
        head_cells = "".join(
            '<th class="num rot" title="{title}"><span>{no}</span></th>'.format(
                title=_e(row["title"]), no=row["no"],
            )
            for row in assignment_rows
        )
        body_cells = "".join(
            '<tr><td class="sticky">{name}{number}</td>'.format(
                name=_e(row["name"]),
                number=(' <span class="muted">' + _e(row["number"]) + "</span>") if row["number"] else "",
            )
            + "".join(
                '<td class="num"><span class="cell c-{cls}">{text}</span></td>'.format(
                    cls=cell["cls"], text=cell["text"],
                )
                for cell in row["cells"]
            )
            + '<td class="num"><b>{avg}</b></td></tr>'.format(
                avg=_pct(row["avg"]) if row["avg"] is not None else "—",
            )
            for row in student_rows
        )
        matrix_html = (
            '<div class="matrix-scroll"><table class="matrix"><thead><tr>'
            '<th class="sticky">学生</th>' + head_cells + '<th class="num">均分</th>'
            "</tr></thead><tbody>" + body_cells + "</tbody></table></div>\n"
            '<p class="sec-note">列序号对应上方「作业完成情况」的 # 列；单元格为单次得分，'
            "颜色由绿到红表示由高到低，「—」表示未提交。</p>\n"
        )
    else:
        matrix_html = '<div class="empty">还没有可展示的成绩数据。</div>\n'

    # ---- 薄弱知识点
    if weak_points:
        weak_html = "".join(
            '<div class="weak-row"><span class="pt">{name}</span>'
            '<div class="track"><i class="b-{css}" style="width:{width}"></i></div>'
            '<span class="rt">{rate}</span>'
            '<span class="cnt">{wrong}/{total} 错</span></div>'.format(
                name=_e(item["name"]), width=_pct(item["rate"]),
                css="fl" if item["rate"] >= 0.5 else ("ps" if item["rate"] >= 0.3 else "md"),
                rate=_pct(item["rate"]), wrong=item["wrong"], total=item["total"],
            )
            for item in weak_points
        )
    else:
        weak_html = '<div class="empty">没有答错的题目，或者还没有作答记录。</div>'

    # ---- 结论
    notes = []
    if total_slots and submit_rate < 0.8:
        notes.append(
            f"提交率 {_pct(submit_rate)}，有 {total_slots - len(submissions)} 人次未交。建议先在课堂上提醒补交，"
            "未交的作业会让统计失真。"
        )
    if weak_points:
        notes.append("错误率最高的知识点是「{name}」（{rate}），可作为下一节课的复习重点。".format(
            name=weak_points[0]["name"], rate=_pct(weak_points[0]["rate"]),
        ))
    if participated and worst < 0.6:
        lagging = [row["name"] for row in ranked if row["avg"] < 0.6]
        if lagging:
            notes.append(
                "{count} 名学生平均分低于 60：{names}。建议单独查看他们的个人报告。".format(
                    count=len(lagging), names="、".join(lagging[:5]),
                )
            )
    if not notes:
        notes.append("提交率和成绩分布都比较理想，可以进入下一阶段的内容。")
    note_html = "".join('<div class="note">' + _e(note) + "</div>" for note in notes)

    tail = (
        "\n  <h2>要点提示</h2>\n  " + note_html + "\n\n"
        '  <div class="foot"><span>Edu · 本报告由班级作业记录自动生成，'
        "所有数据来自学生实际提交。</span>"
        "<span>可在浏览器中「打印 → 另存为 PDF」。</span></div>\n</div></body></html>"
    )

    return (
        head + kpis
        + "  <h2>成绩分布</h2>\n" + hist_html + "\n"
        + trend_html
        + "  <h2>作业完成情况</h2>\n  " + done_html + "\n\n"
        + "  <h2>学生排名</h2>\n  " + rank_html + "\n  " + rank_note + "\n\n"
        + "  <h2>成绩矩阵</h2>\n  " + matrix_html + "\n"
        + "  <h2>薄弱知识点</h2>\n  " + weak_html + "\n"
        + tail
    )
