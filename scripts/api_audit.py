"""前端调用与后端 OpenAPI 路由一致性检查。

用法（服务已启动）：
    .venv/Scripts/python scripts/api_audit.py http://127.0.0.1:8000
"""
import glob
import re
import sys

import httpx

BASE = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://127.0.0.1:8010"

with httpx.Client(trust_env=False) as client:
    openapi = client.get(f"{BASE}/api/openapi.json").json()["paths"]
backend = set(openapi)
frontend = set()
pattern = re.compile(r"""["'`](/api/[^"'`\s]+)["'`]""")
for path in glob.glob("web/src/**/*.js", recursive=True) + glob.glob("web/src/**/*.vue", recursive=True):
    text = open(path, encoding="utf-8").read()
    for match in pattern.findall(text):
        if "${" in match:
            match = re.sub(r"\$\{[^}]+\}", "{id}", match)
        frontend.add(match.split("?")[0])

print(f"frontend calls ({len(frontend)}):")
for path in sorted(frontend):
    print(" ", path)
print(f"\nbackend paths ({len(backend)}):")
for path in sorted(backend):
    print(" ", path)


def normalize(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "{x}", path)


backend_norm = {normalize(p): p for p in backend}
missing = sorted(p for p in frontend if normalize(p) not in backend_norm)
print(f"\nmissing (normalized): {len(missing)}")
for path in missing:
    print(" ", path)
