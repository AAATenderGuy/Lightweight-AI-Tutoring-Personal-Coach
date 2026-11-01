"""统一登录 / 注册：不选身份，靠输入判定。

设计要点：
- 登录只收「账号 + 密码」。服务端先查教师用户名，再查班级名单里的学号，
  命中哪个就按哪个校验；两者都命中时以密码正确的那个为准。
- 注册靠「是否填了班级邀请码」分流：填了按学生入班，留空则创建教师账号。
- 教师用户名禁止纯数字（见 services/auth.py），所以「纯数字=学号」是一条
  可以放心依赖的硬规则，前端才能即时显示识别结果。

旧的 /api/teacher/login、/api/student/login 保持原样，供脚本与测试继续使用。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .. import store
from ..schemas import AuthLogin, AuthRegister
from ..services import auth as auth_service
from ..services import classes
from .limits import rate_limit

router = APIRouter(tags=["auth"])


def _bad(error: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail=str(error))


def _is_student_number(number: str) -> bool:
    """这个学号是否出现在某个未归档班级的名单里。"""
    target = (number or "").strip()
    if not target:
        return False
    for student in store.list_items("students"):
        if str(student.get("number") or "").strip() != target:
            continue
        klass = store.load_item("classes", student.get("class_id") or "")
        if klass and not klass.get("archived"):
            return True
    return False


@router.post("/auth/login", dependencies=[rate_limit("auth-login", 30)])
async def login(payload: AuthLogin) -> dict:
    account = payload.account.strip()
    if not account or not payload.password:
        raise HTTPException(status_code=400, detail="请填写账号和密码。")

    is_teacher = auth_service.find_by_username(account) is not None
    is_student = _is_student_number(account)

    if not is_teacher and not is_student:
        raise HTTPException(status_code=400, detail="账号或密码不正确。")

    if is_teacher:
        try:
            return {"role": "teacher", **auth_service.login(account, payload.password)}
        except ValueError as exc:
            # 账号既是教师用户名又是某个学号时，再按学生校验一次，避免撞车后无法登录
            if not is_student:
                raise _bad(exc) from exc

    try:
        data = classes.student_login(account, payload.password, payload.code)
    except ValueError as exc:
        raise _bad(exc) from exc
    return {"role": "student", **data}


@router.post("/auth/register", dependencies=[rate_limit("auth-register", 20)])
async def register(payload: AuthRegister) -> dict:
    invite = payload.invite.strip().upper()
    if invite:
        try:
            data = classes.join(invite, payload.name, payload.account)
        except ValueError as exc:
            raise _bad(exc) from exc
        return {"role": "student", **data}

    if not payload.name.strip():
        raise HTTPException(status_code=400, detail="请填写姓名。")
    try:
        data = auth_service.register(payload.account, payload.password, payload.name)
    except ValueError as exc:
        raise _bad(exc) from exc
    return {"role": "teacher", **data}
