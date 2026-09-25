FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOST=0.0.0.0 \
    PORT=8000

WORKDIR /app

# 仅拷贝应用代码与验证脚本（运行时零第三方依赖）。
COPY app ./app
COPY tests ./tests
COPY scripts ./scripts

RUN chmod +x scripts/verify.py \
    && python -m compileall -q app tests scripts \
    && useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

# 容器级健康检查：slim 镜像不带 curl，直接用标准库探活。
HEALTHCHECK --interval=10s --timeout=3s --start-period=3s --retries=5 \
    CMD python -c "import urllib.request,sys; r=urllib.request.urlopen('http://127.0.0.1:'+__import__('os').environ.get('PORT','8000')+'/healthz', timeout=2); sys.exit(0 if r.status==200 else 1)"

CMD ["python", "-m", "app.server"]
