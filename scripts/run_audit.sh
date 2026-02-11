#!/usr/bin/env bash
# Windows 한글 환경에서 pip_api가 UTF-8 디코딩 오류 나는 것 방지
# 사용: bash scripts/run_audit.sh   또는  ./scripts/run_audit.sh
PYTHONUTF8=1 python -m pip_audit "$@"
