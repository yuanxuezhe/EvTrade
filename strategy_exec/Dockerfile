# syntax=docker/dockerfile:1.6

# ──── Stage 1: builder ────
FROM python:3.11-slim AS builder

WORKDIR /build

# 系统依赖 (uv 后端需要的)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# 安装 uv (Astral 官方)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# 装依赖到独立虚拟环境
COPY pyproject.toml ./
RUN uv venv /opt/venv && \
    uv pip install --python /opt/venv/bin/python \
        fastapi uvicorn pydantic pydantic-settings \
        sqlalchemy pymysql cryptography \
        aio-pika pika websockets \
        backtrader pandas numpy \
        loguru tenacity

# 拷贝源代码
COPY strategy_exec ./strategy_exec
COPY scripts ./scripts

# ──── Stage 2: runtime ────
FROM python:3.11-slim AS runtime

# 复制 venv
COPY --from=builder /opt/venv /opt/venv

# 复制源码
COPY --from=builder /build/strategy_exec /app/strategy_exec
COPY --from=builder /build/scripts /app/scripts

WORKDIR /app

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

EXPOSE 8001

# 健康检查
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8001/health', timeout=2)"

# 启动
CMD ["python", "-m", "uvicorn", "strategy_exec.main:app", "--host", "0.0.0.0", "--port", "8001"]