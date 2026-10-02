FROM python:3.12-slim

# Tesseract — из пакетов ОС; языковые модели — стандартные tessdata (на них сервис проверялся),
# а не облегчённые tessdata_fast из пакетов Debian.
RUN apt-get update \
 && apt-get install -y --no-install-recommends tesseract-ocr \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

ADD https://github.com/tesseract-ocr/tessdata/raw/main/rus.traineddata tessdata/rus.traineddata
ADD https://github.com/tesseract-ocr/tessdata/raw/main/eng.traineddata tessdata/eng.traineddata
COPY app ./app

RUN useradd --uid 10001 --no-create-home redactor \
 && mkdir -p /data && chown redactor /data \
 && chmod 644 tessdata/*.traineddata
USER redactor

ENV STATE_DIR=/data PYTHONUNBUFFERED=1
EXPOSE 8088
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8088/')" || exit 1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8088"]
