import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_env_file() -> None:
    """Подхватывает .env из корня проекта (без внешних зависимостей)."""
    env = BASE_DIR / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_env_file()

# Модели Tesseract можно положить в ./tessdata проекта (тогда не нужны языковые пакеты ОС).
# Если там пусто — используются модели, установленные вместе с Tesseract.
_local_tessdata = BASE_DIR / "tessdata"
if any(_local_tessdata.glob("*.traineddata")):
    os.environ.setdefault("TESSDATA_PREFIX", str(_local_tessdata))

OCR_LANG = os.getenv("OCR_LANG", "rus+eng")
TESSERACT_CMD = os.getenv("TESSERACT_CMD", "")      # путь к tesseract, если его нет в PATH (Windows)
OCR_DPI = int(os.getenv("OCR_DPI", "300"))          # разрешение для распознавания
OUTPUT_DPI = int(os.getenv("OUTPUT_DPI", "200"))    # разрешение страниц в итоговом PDF
JPEG_QUALITY = int(os.getenv("JPEG_QUALITY", "80"))

LLM_BASE_URL = os.getenv("LLM_BASE_URL", "")        # напр. http://llm.local:8000/v1
LLM_API_KEY = os.getenv("LLM_API_KEY", "none")
LLM_MODEL = os.getenv("LLM_MODEL", "")
LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "180"))

WORKERS = int(os.getenv("WORKERS", "1"))            # сколько документов обрабатывается параллельно
if WORKERS > 1:
    # Tesseract сам занимает все ядра; при нескольких воркерах они мешали бы друг другу.
    os.environ.setdefault("OMP_THREAD_LIMIT", "1")
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "60"))
RESULT_TTL_MIN = int(os.getenv("RESULT_TTL_MIN", "30"))
# Где хранятся задачи между перезапусками. На сервере — tmpfs (/run/redactor), см. deploy/redactor.service.
STATE_DIR = os.getenv("STATE_DIR", str(BASE_DIR / "data"))
MAX_ATTEMPTS = int(os.getenv("MAX_ATTEMPTS", "3"))  # сколько раз пробовать задачу, если процесс падал на ней


def llm_enabled() -> bool:
    return bool(LLM_BASE_URL and LLM_MODEL)
