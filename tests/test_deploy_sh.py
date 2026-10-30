"""deploy.sh 的静态检查与纯逻辑测试（不碰 Docker）。

真正的容器生命周期（起容器、健康检查、改密码、备份、停止）在
`.github/workflows/ci.yml` 的 `deploy` job 里跑；这里只覆盖能在几秒内验证的部分：
语法、参数校验、Caddyfile 生成、.env 读写。

只在 Linux 上跑：脚本本身有 `uname -s` 守卫，Windows 开发机跑了也会直接退出。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "deploy.sh"
BASH = shutil.which("bash") or "/bin/bash"

pytestmark = [
    pytest.mark.skipif(sys.platform != "linux", reason="deploy.sh 只在 Linux 服务器上跑"),
    pytest.mark.skipif(shutil.which("bash") is None, reason="环境里没有 bash"),
]


def clean_env() -> dict[str, str]:
    """去掉 conftest 注入的 EDU_* 变量，避免测试互相污染。"""
    env = {k: v for k, v in os.environ.items() if not k.startswith("EDU_")}
    env.setdefault("PATH", "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin")
    return env


def run(args: list[str], cwd: Path = ROOT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [BASH, SCRIPT.as_posix(), *args],
        cwd=str(cwd), capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=60, env=clean_env(),
    )


def run_sourced(tmp_path: Path, body: str) -> subprocess.CompletedProcess[str]:
    """source 去掉 main 之后的脚本，执行一小段断言代码。"""
    lines = SCRIPT.read_text(encoding="utf-8").rstrip().splitlines()
    assert lines[-1].strip() == "main", "deploy.sh 末尾应当只有 main 一行"
    (tmp_path / "t.sh").write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")
    return subprocess.run(
        [BASH, "-c", f"cd {tmp_path.as_posix()} && source ./t.sh && {body}"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=60, env=clean_env(),
    )


# ---------------------------------------------------------------- 静态
def test_syntax_is_valid():
    result = subprocess.run(
        [BASH, "-n", SCRIPT.as_posix()],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
    )
    assert result.returncode == 0, result.stderr


def test_help_lists_subcommands():
    result = run(["--help"])
    assert result.returncode == 0
    for word in ("up", "down", "backup", "https", "logs"):
        assert word in result.stdout


def test_unknown_flag_fails():
    result = run(["--bogus"])
    assert result.returncode != 0
    assert "未知参数" in result.stderr


def test_rejects_bad_mode():
    result = run(["--mode", "vector"])
    assert result.returncode != 0
    assert "--mode 只能是" in result.stderr


def test_rejects_bad_port():
    result = run(["--port", "abc"])
    assert result.returncode != 0
    assert "只接受数字" in result.stderr


# ---------------------------------------------------------------- 生成逻辑
def test_https_generates_caddyfile_and_override(tmp_path):
    result = run_sourced(
        tmp_path,
        "DOMAIN=edu.example.com ACME_EMAIL=ops@example.com setup_https >/dev/null",
    )
    assert result.returncode == 0, result.stderr

    caddyfile = (tmp_path / "deploy" / "Caddyfile").read_text(encoding="utf-8")
    assert "edu.example.com {" in caddyfile
    assert "email ops@example.com" in caddyfile
    # SSE 不能缓冲，否则对话与课堂生成会卡住
    assert "flush_interval -1" in caddyfile
    assert "reverse_proxy edu:8000" in caddyfile

    override = (tmp_path / "docker-compose.https.yml").read_text(encoding="utf-8")
    assert "caddy:2-alpine" in override
    assert "./deploy/Caddyfile" in override
    assert '"443:443"' in override


def test_rejects_bad_domain(tmp_path):
    result = run_sourced(tmp_path, "DOMAIN='bad domain' setup_https")
    assert result.returncode != 0
    assert "域名格式不对" in result.stderr


def test_env_helpers_keep_and_override(tmp_path):
    body = (
        "ensure_kv EDU_PORT 8000 && "
        "ensure_kv EDU_PORT 9000 && "
        "set_kv EDU_API_KEY 'sk-a|b&c' && "
        "set_kv EDU_API_KEY 'sk-new/1' && "
        "cat .env"
    )
    result = run_sourced(tmp_path, body)
    assert result.returncode == 0, result.stderr
    env_text = (tmp_path / ".env").read_text(encoding="utf-8")
    # ensure_kv 只补空值，不覆盖已有值
    assert "EDU_PORT=8000" in env_text
    assert "EDU_PORT=9000" not in env_text
    # set_kv 强制覆盖，且 | 与 / 不会打穿写入逻辑
    assert "EDU_API_KEY=sk-new/1" in env_text
    assert "sk-a|b&c" not in env_text


def test_reuse_https_recovers_domain(tmp_path):
    setup = run_sourced(
        tmp_path,
        "DOMAIN=edu.example.com setup_https >/dev/null; "
        "DOMAIN=''; COMPOSE_FILES=(-f docker-compose.yml); "
        "reuse_https; echo \"domain=$DOMAIN\"; echo \"files=${COMPOSE_FILES[*]}\"",
    )
    assert setup.returncode == 0, setup.stderr
    assert "domain=edu.example.com" in setup.stdout
    assert "docker-compose.https.yml" in setup.stdout
