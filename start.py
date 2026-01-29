#!/usr/bin/env python3
"""Railway 시작 스크립트 - 로깅 후 Streamlit 실행."""
import os
import sys
import subprocess
from datetime import datetime

# 즉시 출력 (버퍼링 없이)
print(f"[START] start.py executing at {datetime.now()}", file=sys.stderr, flush=True)
print(f"[START] PORT={os.environ.get('PORT', 'NOT SET')}", file=sys.stderr, flush=True)
print(f"[START] RAILWAY_ENVIRONMENT={os.environ.get('RAILWAY_ENVIRONMENT', 'NOT SET')}", file=sys.stderr, flush=True)
print(f"[START] Python version: {sys.version}", file=sys.stderr, flush=True)
print(f"[START] Working directory: {os.getcwd()}", file=sys.stderr, flush=True)

# 기존 unknown 레코드 수정 (1회성)
print(f"[START] Running fix_unknown_records.py...", file=sys.stderr, flush=True)
try:
    result = subprocess.run(
        [sys.executable, "scripts/fix_unknown_records.py"],
        env={**os.environ, "DATABASE_URL": "/data/ddari.db"},
        capture_output=True,
        text=True,
        timeout=30,
    )
    print(f"[START] fix_unknown_records output: {result.stdout}", file=sys.stderr, flush=True)
    if result.returncode != 0:
        print(f"[START] fix_unknown_records stderr: {result.stderr}", file=sys.stderr, flush=True)
except Exception as e:
    print(f"[START] fix_unknown_records error: {e}", file=sys.stderr, flush=True)

print(f"[START] Starting Streamlit...", file=sys.stderr, flush=True)

# PORT 환경변수 확인
port = os.environ.get("PORT", "8501")

# Streamlit 실행
try:
    subprocess.run(
        [
            sys.executable, "-m", "streamlit", "run", "app.py",
            "--server.port", port,
            "--server.address", "0.0.0.0",
        ],
        check=True,
    )
except Exception as e:
    print(f"[START] FATAL ERROR: {e}", file=sys.stderr, flush=True)
    sys.exit(1)
