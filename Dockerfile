# Agnes Video Generator — 容器化构建
# 单阶段：python:3.11-slim + 内置 ffmpeg（硬依赖）+ CJK 字体（随仓库 resource/）
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# ffmpeg 是视频拼接/音频处理的硬依赖。
# 采用 imageio-ffmpeg：ffmpeg 静态二进制打包在 PyPI wheel 内，
# 避免 apt 装 ffmpeg 的庞大依赖树。
# 默认走官方 PyPI（GitHub Actions 美国 runner 最快）。
# 本地国内构建如需加速，传 --build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ARG PIP_INDEX_URL=
RUN if [ -n "$PIP_INDEX_URL" ]; then \
        pip config set global.index-url "$PIP_INDEX_URL"; \
    fi \
    && pip install --no-cache-dir --default-timeout=600 imageio-ffmpeg \
    && if [ -n "$PIP_INDEX_URL" ]; then \
        pip config unset global.index-url; \
    fi

# 将 imageio-ffmpeg 提供的静态二进制暴露到 PATH（moviepy / ffmpeg CLI 均可调用）
RUN FFMPEG_BIN=$(python -c "import imageio_ffmpeg, os; print(os.path.join(os.path.dirname(imageio_ffmpeg.__file__), 'binaries', os.listdir(os.path.join(os.path.dirname(imageio_ffmpeg.__file__), 'binaries'))[0]))") \
    && ln -sf "$FFMPEG_BIN" /usr/local/bin/ffmpeg \
    && FFMPEG_EXE=$(python -c "import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())") \
    && ln -sf "$FFMPEG_EXE" /usr/local/bin/ffmpeg \
    && ffmpeg -version | head -1

# 先装项目 Python 依赖（利用层缓存）
COPY requirements.txt .
RUN if [ -n "$PIP_INDEX_URL" ]; then \
        pip config set global.index-url "$PIP_INDEX_URL"; \
    fi \
    && pip install --no-cache-dir --default-timeout=600 -r requirements.txt \
    && if [ -n "$PIP_INDEX_URL" ]; then \
        pip config unset global.index-url; \
    fi

# 拷贝应用代码（resource/fonts 含 CJK 字体，必须随镜像）
COPY . .

EXPOSE 8765

# 3.2：容器健康检查（python urllib 探活 /api/health，避免依赖 apt curl）
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8765/api/health', timeout=3).status==200 else 1)"

# 声明持久化卷：即使不加 -v 直接 docker run，以下两个目录也会落到 Docker 管理的卷里，
# 同一容器 stop/start 时数据保留；可用 `docker cp 容器名:/app/.working_dir ./out` 导出。
# 若要数据直接落盘到本机并随时导出，推荐用 docker-compose.yml 或 docker-run.sh（bind mount）。
VOLUME ["/app/.working_dir", "/app/.agnes_config"]

# server.py 内部以 host=0.0.0.0 port=8765 启动，容器外可访问
# API Key 通过环境变量注入：-e AGNES_API_KEY=xxx（也可在 Web UI 配置）
CMD ["python", "server.py"]
