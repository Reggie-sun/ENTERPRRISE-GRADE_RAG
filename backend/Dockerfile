FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV RAG_LIBREOFFICE_BINARY=/usr/bin/soffice

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
        libgomp1 \
        libreoffice-writer \
    && /usr/bin/soffice --version \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
COPY requirements /app/requirements
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt \
    && pip install --no-cache-dir -r /app/requirements/ocr-cpu.txt

COPY backend /app/backend

EXPOSE 8020

CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8020"]
