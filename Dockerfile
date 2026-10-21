FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src ./src
COPY scripts ./scripts

RUN useradd --create-home appuser && mkdir -p /data && chown -R appuser:appuser /app /data
USER appuser

EXPOSE 8000

# Por padrao a imagem roda o Manager; os Workers sobrescrevem o comando no compose.
CMD ["uvicorn", "src.manager.main:app", "--host", "0.0.0.0", "--port", "8000"]
