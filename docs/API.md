# Edu 接口文档

| 项 | 内容 |
| --- | --- |
| 版本 | v1.5.0 |
| Base URL | `http://<host>:<port>/api` |
| 交互式文档 | `GET /api/docs`（Swagger UI）、`GET /api/openapi.json` |
| 编码 | 请求/响应均为 UTF-8 JSON（文件上传为 `multipart/form-data`） |
| 时间 | 所有时间戳为 **Unix 秒**（浮点数） |

---

## 1. 通用约定

### 1.1 鉴权

| 端 | 方式 |
| --- | --- |
| 教师 | `Authorization: Bearer <token>`（`POST /teacher/login` 或 `/teacher/register` 返回） |
| 学生 | `student_id` + `token` 一起传：JSON body、query 参数，或 SSE/下载用 `X-Student-Token` 头 |

- 教师 token 有效期 12 小时，服务重启后仍有效（磁盘只存 SHA-256）。
- 学生 token 为 HMAC 签名，**同一学生**重新登录/换设备会得到同一 token。
- 未认证/失效：`401`；越权（不属于当前教师/学生）：`400`（错误信息说明原因）。

### 1.2 错误格式

```json
{ "detail": "学号或密码不正确。" }
```

| 状态码 | 含义 |
| --- | --- |
| 400 | 业务校验失败（参数不合规、越权、状态不允许） |
| 401 | 未登录 / token 失效 |
| 404 | 资源不存在 |
| 413 | 上传超过大小限制 |
| 422 | 请求体字段类型/长度不合法（FastAPI 校验） |
| 429 | 触发限流（默认 120 次/分钟/IP，`EDU_RATE_LIMIT=0` 关闭） |
| 502 | 模型调用失败（Key、网络、上游错误） |

### 1.3 分页与排序

当前**没有分页**：列表接口一次返回全部（按创建时间倒序或业务排序）。数据量大时建议前端折叠或后续加分页。

### 1.4 SSE 协议

- `Content-Type: text/event-stream`；每条消息 `data: {json}\n\n`；
- 心跳为 `: ping\n\n`（15 秒）；
- 首帧 `{"type":"ready", ...}`；
- 客户端断线后应按指数退避重连，并在 `ready` 后整体重拉一次数据。

---

## 2. 公共接口

| 方法 | 路径 | 鉴权 | 说明 |
| --- | --- | --- | --- |
| GET | `/health` | 无 | 健康检查：版本、模式、资料/课堂/班级/教师数量 |
| GET | `/settings` | 无 | 模型配置（Key 只返回掩码） |
| PUT | `/settings` | 无 | 保存模型配置 |
| POST | `/settings/test` | 无 | 用当前配置发一次最小请求 |
| GET | `/materials` | 无 | 资料列表 |
| POST | `/materials` | 无 | 上传资料（multipart，≤10 MB） |
| DELETE | `/materials/{id}` | 无 | 删除资料 |
| POST | `/chat/stream` | 无 | AI 导师对话（SSE） |
| GET | `/progress` | 无 | 本机学习进度与掌握度 |
| DELETE | `/progress` | 无 | 清空进度 |

> 说明：本项目定位单机/小班，学生侧与资料/测验类接口沿用无登录设计；班级与教师数据由教师 token 保护。

### 2.1 `POST /chat/stream`

请求：

```json
{
  "message": "为什么光反应发生在类囊体薄膜上？",
  "mode": "socratic",
  "history": [{ "role": "user", "content": "..." }],
  "material_ids": ["mat_xxx"],
  "use_materials": true
}
```

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| message | string | 是 | 1–8000 字 |
| mode | `socratic` / `explain` | 否 | 默认 `socratic` |
| history | array | 否 | 最近若干轮 |
| material_ids | string[] | 否 | 限定检索范围 |
| use_materials | bool | 否 | 默认 true |

响应（SSE）：

```text
data: {"type":"meta","sources":[{"index":1,"title":"光合作用.md","preview":"..."}],"demo":false}
data: {"type":"delta","text":"先从"}
...
data: {"type":"done"}
```

失败：`{"type":"error","message":"..."}`。

---

## 3. 课堂与小组

| 方法 | 路径 | 鉴权 | 说明 |
| --- | --- | --- | --- |
| POST | `/classroom/generate` | 无 | 生成课堂（SSE：`status → lesson → done`） |
| GET | `/classroom/lessons` | 无 | 课堂列表 |
| GET | `/classroom/lessons/{id}` | 无 | 课堂详情 |
| DELETE | `/classroom/lessons/{id}` | 无 | 删除课堂 |
| POST | `/classroom/lessons/{id}/quiz` | 无 | 用课堂检测页生成可提交测验 |
| GET | `/classroom/lessons/{id}/export/pptx` | 无 | 导出教师版 PPTX |
| GET | `/classroom/group/agents` | 无 | 读取小组角色配置 |
| PUT | `/classroom/group/agents` | 无 | 保存小组角色（2–6 个） |
| POST | `/classroom/group/agents/reset` | 无 | 恢复默认角色 |
| POST | `/classroom/group-discuss` | 无 | 多智能体讨论（SSE） |
| POST | `/classroom/discuss` | 无 | 课堂内答疑（SSE） |

### 3.1 生成课堂

```json
{ "topic": "光合作用", "level": "beginner", "duration": 20, "material_ids": [], "scene_count": 6 }
```

SSE 事件：`status`（备课文案）→ `lesson`（完整课堂 JSON，含 `scenes`）→ `done`。

### 3.2 小组讨论

```json
{
  "lesson_id": "lsn_xxx",
  "scene_id": "s3",
  "message": "我觉得暗反应不需要光",
  "mode": "chat",
  "history": [{ "role": "user", "agent": "", "content": "..." }]
}
```

SSE 事件顺序：

```text
meta            {agents, speakers, reason, mode, demo}
agent_start     {agent:{id,name,role}}
delta           {agent, text}        （多帧）
agent_end       {agent}
done
```

---

## 4. 测验

| 方法 | 路径 | 鉴权 | 说明 |
| --- | --- | --- | --- |
| POST | `/quiz/generate` | 无 | 生成测验（3–8 题） |
| POST | `/quiz/{id}/submit` | 无 | 提交并判分 |
| POST | `/quiz/{id}/similar` | 无 | 按薄弱知识点生成变式题（带详解） |

---

## 5. 教师端

### 5.1 账号

| 方法 | 路径 | 鉴权 | 说明 |
| --- | --- | --- | --- |
| POST | `/teacher/register` | 无 | 注册并返回 token |
| POST | `/teacher/login` | 无 | 登录并返回 token |
| POST | `/teacher/logout` | Bearer | 作废当前 token |
| GET | `/teacher/me` | Bearer | 当前教师信息 |
| PUT | `/teacher/password` | Bearer | 修改密码 |

登录请求/响应：

```json
{ "username": "demo", "password": "demo1234" }
```

```json
{
  "teacher": { "id": "tc_x", "username": "demo", "name": "演示教师" },
  "token": "…"
}
```

### 5.2 班级与名单

| 方法 | 路径 | 鉴权 | 说明 |
| --- | --- | --- | --- |
| GET | `/teacher/overview` | Bearer | 概览统计、待处理作业、薄弱点、最近提交 |
| GET | `/teacher/classes` | Bearer | 班级列表（含学生数、提交数、均分） |
| POST | `/teacher/classes` | Bearer | 新建班级 |
| GET | `/teacher/classes/{id}` | Bearer | 班级详情（学生、作业、统计） |
| PATCH | `/teacher/classes/{id}` | Bearer | 改名 / 科目 / 年级 / 归档 |
| DELETE | `/teacher/classes/{id}` | Bearer | 删除班级（连带作业、学生、提交、附件） |
| POST | `/teacher/classes/{id}/code` | Bearer | 重置邀请码 |
| POST | `/teacher/classes/{id}/roster` | Bearer | **导入名单**（multipart） |
| GET | `/teacher/classes/{id}/roster.csv` | Bearer | 导出名单（不含明文密码） |
| POST | `/teacher/classes/{id}/students/{sid}/password` | Bearer | 重置学生密码 |
| DELETE | `/teacher/classes/{id}/students/{sid}` | Bearer | 移出学生 |
| GET | `/teacher/classes/{id}/export.csv` | Bearer | 班级成绩矩阵 CSV |
| GET | `/teacher/classes/{id}/report.html` | Bearer | 班级成绩报告 HTML |

**导入名单**（multipart/form-data）：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| file | file | 否 | CSV/TXT，≤2 MB |
| text | string | 否 | 直接粘贴的名单（与 file 二选一） |
| default_password | string | 否 | 没有密码列时使用；留空则随机 6 位 |

CSV 格式（列顺序不限，表头可省略）：

```text
学号,姓名,密码
2024001,张三,zhang123
2024002,李四,li456
```

响应：

```json
{
  "class": { "id": "cl_x", "name": "高一(3)班", "student_count": 42 },
  "created": 40,
  "updated": 2,
  "total": 42,
  "errors": ["第 7 行缺少学号"],
  "duplicates": 1,
  "credentials": [{ "number": "2024001", "name": "张三", "password": "zhang123" }]
}
```

> `credentials` 里的明文密码**只返回这一次**，请立即分发。

### 5.3 作业与批改

| 方法 | 路径 | 鉴权 | 说明 |
| --- | --- | --- | --- |
| GET | `/teacher/assignments` | Bearer | 作业列表（`?class_id=` 过滤） |
| POST | `/teacher/assignments` | Bearer | 布置作业（在线或文件） |
| GET | `/teacher/assignments/{id}` | Bearer | 作业详情（统计、错题、提交、文件） |
| PATCH | `/teacher/assignments/{id}` | Bearer | 改标题/说明/评分要点/截止/显示解析/关闭 |
| DELETE | `/teacher/assignments/{id}` | Bearer | 删除作业（连带提交与附件） |
| POST | `/teacher/assignments/{id}/practice` | Bearer | 按薄弱点生成补练作业 |
| GET | `/teacher/assignments/{id}/export.csv` | Bearer | 作业明细 CSV |
| GET | `/teacher/students/{sid}/report.html` | Bearer | 学生个人报告 |
| GET | `/teacher/submissions/{sid}` | Bearer | 单份提交详情 |
| PATCH | `/teacher/submissions/{sid}` | Bearer | **教师复核改分** |
| POST | `/teacher/submissions/{sid}/regrade-ai` | Bearer | 重新触发 AI 批改 |
| GET | `/teacher/submissions/{sid}/files/{fid}` | Bearer | 下载学生附件 |
| GET | `/teacher/stream` | Bearer | 教师端 SSE |
| GET | `/teacher/presence` | Bearer | 在线名单快照 |

**布置文件作业**：

```json
{
  "class_id": "cl_x",
  "topic": "光合作用实验报告",
  "kind": "homework",
  "submission_mode": "file",
  "instructions": "提交一份实验报告",
  "rubric": "写出光反应与暗反应的区别；给出实验现象；结论明确",
  "due_at": 1760000000,
  "reveal": true
}
```

`submission_mode`：`quiz`（在线作答，默认）或 `file`（文件提交，不生成题目）。

**复核改分**：

```json
{ "score": 88, "feedback": "论证完整，结论明确", "note": "比上次结构清楚" }
```

- `score` 为 **0–100** 的百分制；
- 保存后 `score` 覆盖最终分，`ai_score` 保留初评，`regrade_history` 追加记录；
- 学生端立即可见新分数与评语。

---

## 6. 学生端

| 方法 | 路径 | 鉴权 | 说明 |
| --- | --- | --- | --- |
| POST | `/student/login` | 无 | 学号 + 密码登录 |
| POST | `/student/join` | 无 | 邀请码加入（兼容未导入名单的班） |
| GET | `/student/tasks` | student_id + token | 任务列表与状态 |
| POST | `/student/tasks/{id}/start` | student_id + token | 取题（文件作业返回已提交文件） |
| GET | `/student/tasks/{id}/result` | student_id + token | 回看结果 |
| POST | `/student/tasks/{id}/submit` | student_id + token | 交卷 |
| POST | `/student/tasks/{id}/submit-file` | student_id + token | 提交文件作业（multipart） |
| GET | `/student/submissions/{sid}/files/{fid}` | student_id + token | 下载自己的附件 |
| GET | `/student/stream` | student_id + token | 学生端 SSE |

**登录**：

```json
{ "number": "2024001", "password": "zhang123", "code": "" }
```

`code` 仅在"同一学号出现在多个班"时需要填班级邀请码。

响应：`{ "student": {...}, "token": "…", "klass": {...}, "tasks": [...] }`。

**交卷**：

```json
{
  "student_id": "st_x",
  "token": "…",
  "answers": [{ "question_id": "q1", "answer": "0" }]
}
```

**提交文件**（multipart/form-data）：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| student_id | string | 是 | |
| token | string | 是 | |
| note | string | 否 | 给老师的说明，≤500 字 |
| file | file | 是 | pdf/docx/pptx/txt/md/png/jpg，≤20 MB |

文件作业返回结构（节选）：

```json
{
  "kind": "file",
  "submission_id": "sb_xxx",
  "score": 0.82,
  "ai_score": 0.82,
  "ai_feedback": "……",
  "ai_criteria": [{ "name": "光反应与暗反应的区别", "met": true, "comment": "已提及" }],
  "teacher_score": null,
  "teacher_feedback": "",
  "files": [{ "id": "f_xxx", "filename": "报告.txt", "size": 78 }],
  "needs_review": false
}
```

---

## 7. SSE 事件一览

### 7.1 学生流 `/student/stream`

| 事件 `type` | 触发 | 前端动作 |
| --- | --- | --- |
| `ready` | 连接建立 | 记录在线 |
| `assignment_created` / `updated` / `deleted` | 教师改作业 | 重拉任务 |
| `student_gone` | 被移出班级 | 清空身份、回登录页 |
| `class_deleted` | 班级被删 | 清空身份、提示 |
| `tasks_changed` | 自己的提交变化 | 重拉任务 |
| `unauthorized` | token 失效 | 回登录页 |

### 7.2 教师流 `/teacher/stream`

| 事件 `type` | 触发 | 前端动作 |
| --- | --- | --- |
| `ready` | 连接建立 | — |
| `student_joined` / `student_left` | 邀请码加入/移出 | 刷新名单 + 提示 |
| `student_online` / `student_offline` | 学生打开/关闭班级页 | 更新在线绿点 |
| `assignment_created` / `updated` / `deleted` | 作业变化 | 刷新当前标签页 |
| `submission_saved` | 学生交卷/交文件 | 刷新统计 + 提示 |
| `submission_graded` | 复核/重批 | 刷新详情 |
| `class_changed` | 班级/名单变化 | 刷新班级与概览 |

示例：

```text
data: {"type":"ready","topics":["teacher:tc_x"],"teacher_id":"tc_x"}
data: {"type":"submission_saved","assignment_id":"as_x","student_name":"张三","score":0.88}
```

---

## 8. 关键错误与处理建议

| 场景 | 返回 | 建议 |
| --- | --- | --- |
| 教师 token 过期 | 401 | 跳转登录；前端清 localStorage |
| 学生 token 失效 | 401 | 清空学生身份，回学号登录 |
| 作业已截止 | 400 | 提示截止时间，联系老师重开 |
| 文件格式不支持 | 400 | 提示支持格式 |
| 文件 > 20 MB | 413 | 提示压缩/拆分 |
| 模型 Key 错误 | 502 | 引导到设置页测试连接 |
| 请求过频 | 429 | 提示稍后再试 |

---

## 9. 版本与变更

| 版本 | 变更 |
| --- | --- |
| v1.3 | 新增 `/student/stream`、`/teacher/stream`、`/teacher/presence` |
| v1.4 | 新增文件作业提交/下载/复核/重批；学生令牌；教师会话持久化 |
| v1.5 | 新增 `/student/login`、名单导入/导出、重置学生密码；邀请码加入在导入后自动关闭 |
