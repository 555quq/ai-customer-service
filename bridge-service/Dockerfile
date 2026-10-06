# Bridge Service Dockerfile
FROM python:3.11-slim@sha256:9c900dea9e8fb7e16277c179b555cc72d29a352dbc33cff48ad5a0412fd5bfc7

# 设置工作目录
WORKDIR /app

# 复制运行时依赖文件
COPY requirements-runtime.txt .

# 默认使用官方 PyPI，允许构建时根据本地网络覆盖
ARG PIP_INDEX_URL=https://pypi.org/simple
ENV PIP_INDEX_URL=${PIP_INDEX_URL} \
    PIP_DEFAULT_TIMEOUT=120 \
    PIP_RETRIES=10

# pydantic-core 索引页很大，单独安装可避免总解析阶段反复下载
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install pydantic-core==2.14.6

# 安装 Python 运行时依赖
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements-runtime.txt

# 复制应用代码
COPY src/ ./src/
COPY pytest.ini ./

# 创建日志目录
RUN mkdir -p /var/log/bridge

# 暴露端口
EXPOSE 8000

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8000/health')"

# 启动命令
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
