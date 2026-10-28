"""请求/响应的数据结构。"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(default="", max_length=8000)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    mode: Literal["socratic", "explain"] = "socratic"
    history: list[ChatMessage] = Field(default_factory=list)
    material_ids: list[str] = Field(default_factory=list)
    use_materials: bool = True


class LessonRequest(BaseModel):
    topic: str = Field(min_length=1, max_length=200)
    level: Literal["beginner", "intermediate", "advanced"] = "beginner"
    duration: int = Field(default=20, ge=5, le=120)
    material_ids: list[str] = Field(default_factory=list)
    scene_count: int = Field(default=6, ge=5, le=10)


class DiscussRequest(BaseModel):
    lesson_id: str
    scene_id: str
    question: str = Field(min_length=1, max_length=800)
    history: list[ChatMessage] = Field(default_factory=list)


class GroupMessage(BaseModel):
    role: Literal["user", "assistant"]
    agent: str = Field(default="", max_length=40)
    content: str = Field(default="", max_length=3000)


class GroupDiscussRequest(BaseModel):
    lesson_id: str
    scene_id: str
    message: str = Field(default="", max_length=1200)
    mode: Literal["chat", "auto"] = "chat"
    history: list[GroupMessage] = Field(default_factory=list)


class GroupAgentConfig(BaseModel):
    id: str = Field(default="", max_length=40)
    name: str = Field(min_length=1, max_length=20)
    role: str = Field(min_length=1, max_length=20)
    instruction: str = Field(min_length=1, max_length=400)


class GroupAgentsPayload(BaseModel):
    agents: list[GroupAgentConfig] = Field(min_length=2, max_length=6)
    max_speakers: int = Field(default=2, ge=1, le=3)


class SimilarQuizRequest(BaseModel):
    count: int = Field(default=4, ge=1, le=8)
    focus_points: list[str] = Field(default_factory=list, max_length=8)


class QuizRequest(BaseModel):
    topic: str = Field(min_length=1, max_length=200)
    material_ids: list[str] = Field(default_factory=list)
    count: int = Field(default=4, ge=1, le=8)
    difficulty: Literal["easy", "medium", "hard"] = "medium"


class AnswerItem(BaseModel):
    question_id: str
    answer: str = Field(default="", max_length=4000)


class QuizSubmitRequest(BaseModel):
    answers: list[AnswerItem] = Field(default_factory=list)


class SettingsPayload(BaseModel):
    base_url: str | None = Field(default=None, max_length=300)
    model: str | None = Field(default=None, max_length=120)
    api_key: str | None = Field(default=None, max_length=300)
    temperature: float | None = Field(default=None, ge=0, le=1.5)


# ---------------------------------------------------------------- 教师工作台
class TeacherRegister(BaseModel):
    username: str = Field(min_length=3, max_length=24)
    password: str = Field(min_length=6, max_length=72)
    name: str = Field(default="", max_length=24)


class TeacherLogin(BaseModel):
    username: str = Field(min_length=1, max_length=24)
    password: str = Field(min_length=1, max_length=72)


class PasswordChange(BaseModel):
    old_password: str = Field(min_length=1, max_length=72)
    new_password: str = Field(min_length=6, max_length=72)


class ClassCreate(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    subject: str = Field(default="", max_length=40)
    grade: str = Field(default="", max_length=40)
    group_id: str = Field(default="", max_length=64)


class ClassUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=40)
    subject: str | None = Field(default=None, max_length=40)
    grade: str | None = Field(default=None, max_length=40)
    archived: bool | None = None
    group_id: str | None = Field(default=None, max_length=64)


class GroupCreate(BaseModel):
    name: str = Field(min_length=2, max_length=30)


class GroupUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=30)


class GroupMemberAdd(BaseModel):
    username: str = Field(min_length=1, max_length=24)


class AssignmentCreate(BaseModel):
    class_id: str
    title: str = Field(default="", max_length=80)
    topic: str = Field(min_length=1, max_length=120)
    kind: Literal["quiz", "homework"] = "homework"
    submission_mode: Literal["quiz", "file"] = "quiz"
    count: int = Field(default=4, ge=1, le=8)
    difficulty: Literal["easy", "medium", "hard"] = "medium"
    due_at: float = Field(default=0, ge=0)
    instructions: str = Field(default="", max_length=300)
    rubric: str = Field(default="", max_length=1500)
    reveal: bool = False


class AssignmentUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=80)
    instructions: str | None = Field(default=None, max_length=300)
    rubric: str | None = Field(default=None, max_length=1500)
    due_at: float | None = Field(default=None, ge=0)
    reveal: bool | None = None
    closed: bool | None = None


class PracticeRequest(BaseModel):
    count: int = Field(default=4, ge=1, le=8)
    focus_points: list[str] = Field(default_factory=list, max_length=6)
    due_at: float = Field(default=0, ge=0)


class JoinRequest(BaseModel):
    code: str = Field(min_length=1, max_length=12)
    name: str = Field(min_length=1, max_length=20)
    number: str = Field(default="", max_length=20)


class StudentIdRequest(BaseModel):
    student_id: str = Field(min_length=1, max_length=64)
    token: str = Field(default="", max_length=80)


class StudentSubmitRequest(QuizSubmitRequest):
    student_id: str = Field(min_length=1, max_length=64)
    token: str = Field(default="", max_length=80)


class SubmissionGrade(BaseModel):
    """教师复核：score 用百分制，0–100，便于直接填分。"""

    score: float = Field(ge=0, le=100)
    feedback: str = Field(default="", max_length=2000)
    note: str = Field(default="", max_length=300)


class StudentLogin(BaseModel):
    """学生用教务系统学号 + 密码登录。"""

    number: str = Field(min_length=1, max_length=32)
    password: str = Field(min_length=1, max_length=72)
    code: str = Field(default="", max_length=12)


class StudentPasswordChange(BaseModel):
    student_id: str = Field(min_length=1, max_length=64)
    token: str = Field(default="", max_length=80)
    old_password: str = Field(min_length=1, max_length=72)
    new_password: str = Field(min_length=6, max_length=72)


class StudentPasswordReset(BaseModel):
    """教师重置学生密码；留空则生成随机初始密码。"""

    password: str = Field(default="", max_length=72)
