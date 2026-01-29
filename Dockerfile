# Веб-бэкенд: чат с RAG и внешней LLM
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Зависимости бэкенда и RAG
COPY requirements-web.txt ./
RUN pip install --no-cache-dir -r requirements-web.txt

COPY rag/ ./rag/
COPY backend/ ./backend/

ENV PYTHONUNBUFFERED=1
EXPOSE 8000

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
