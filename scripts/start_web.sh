#!/usr/bin/env bash
# Start the local API and Vite UI together for development or Mini staging.
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="$PROJECT_ROOT/.venv/bin/python"
FRONTEND_DIR="$PROJECT_ROOT/frontend"
API_HOST="127.0.0.1"
API_PORT="8000"
FRONTEND_HOST="127.0.0.1"
FRONTEND_PORT="5173"
API_PID=""
API_LOG="${TMPDIR:-/tmp}/forming-grinder-guide-api-$$.log"
ENV_FILE="$PROJECT_ROOT/.env"

cleanup() {
    if [[ -n "$API_PID" ]] && kill -0 "$API_PID" 2>/dev/null; then
        kill "$API_PID" 2>/dev/null || true
        wait "$API_PID" 2>/dev/null || true
    fi
}

fail() {
    echo "启动失败：$1" >&2
    exit 1
}

port_is_listening() {
    lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1
}

api_is_healthy() {
    curl --fail --silent "http://${API_HOST}:${API_PORT}/api/health" >/dev/null 2>&1
}

trap cleanup EXIT INT TERM

[[ -x "$PYTHON" ]] || fail "未找到 Python 虚拟环境。请先在项目根目录执行：python3 -m venv .venv"
[[ -f "$ENV_FILE" ]] || fail "未找到 .env。请复制 .env.example 为 .env 并配置账户和会话密钥。"
set -a
. "$ENV_FILE"
set +a
[[ -n "${CAD_ADMIN_USERNAME:-}" ]] || fail "请设置 CAD_ADMIN_USERNAME。"
[[ -n "${CAD_ADMIN_PASSWORD:-}" ]] || fail "请设置 CAD_ADMIN_PASSWORD。"
[[ -n "${CAD_SESSION_SECRET:-}" ]] || fail "请设置 CAD_SESSION_SECRET。"
"$PYTHON" -c "import fastapi, uvicorn" 2>/dev/null || fail "缺少 Python 依赖。请执行：./.venv/bin/python -m pip install -r requirements.txt"
command -v npm >/dev/null 2>&1 || fail "未找到 npm。请先安装 Node.js。"
[[ -x "$FRONTEND_DIR/node_modules/.bin/vite" ]] || fail "未安装前端依赖。请执行：cd frontend && npm ci"

if port_is_listening "$FRONTEND_PORT"; then
    fail "端口 ${FRONTEND_PORT} 已被占用。请关闭已有前端服务后再启动。"
fi

if port_is_listening "$API_PORT"; then
    api_is_healthy || fail "端口 ${API_PORT} 已被其他服务占用，且不是本项目 API。"
    echo "检测到已有本项目 API，复用 http://${API_HOST}:${API_PORT}。"
else
    "$PYTHON" -m uvicorn src.web_api:app --host "$API_HOST" --port "$API_PORT" >"$API_LOG" 2>&1 &
    API_PID="$!"
    for _ in {1..20}; do
        if api_is_healthy; then
            break
        fi
        sleep 0.25
    done
    api_is_healthy || {
        cat "$API_LOG" >&2
        fail "API 未能启动。"
    }
fi

echo "导轨生成器已启动：http://${FRONTEND_HOST}:${FRONTEND_PORT}"
echo "按 Ctrl+C 将停止本次启动的服务。"
cd "$FRONTEND_DIR"
npm run dev -- --host "$FRONTEND_HOST" --port "$FRONTEND_PORT" --strictPort
