FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_ROOT_USER_ACTION=ignore

WORKDIR /app

# Dependencies first: this layer is cached until requirements.txt changes.
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app
COPY sample_docs ./sample_docs

# Run as an unprivileged user; /app/data (index + embedding model) is a volume.
RUN useradd --create-home appuser && mkdir data && chown appuser data
USER appuser

EXPOSE 8000
# The first start downloads the embedding model before uvicorn opens its port, so allow
# a long start period; probing every 2 s during it still notices a warm start quickly.
HEALTHCHECK --interval=30s --timeout=5s --start-period=600s --start-interval=2s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')"

CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
