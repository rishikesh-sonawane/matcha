FROM python:3.11-slim AS builder

WORKDIR /build

COPY requirements.txt .
RUN pip install --no-cache-dir --user --upgrade pip && \
    pip install --no-cache-dir --user -r requirements.txt


FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

RUN groupadd --gid 10001 app && \
    useradd --uid 10001 --gid app --shell /bin/bash --create-home app

COPY --from=builder /root/.local /home/app/.local

ENV PATH=/home/app/.local/bin:$PATH

WORKDIR /app

COPY --chown=app:app . .

USER app

ENTRYPOINT ["python3", "main.py"]
