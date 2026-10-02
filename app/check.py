"""Проверка окружения перед первым запуском.

    python -m app.check

Печатает по пунктам, что в порядке, а что нужно исправить. Код возврата 1, если есть ошибки.
"""
import os
import platform
import sys
from pathlib import Path

OK, WARN, FAIL = "✅", "⚠️ ", "❌"
problems = 0


def report(status: str, text: str, hint: str = "") -> None:
    global problems
    if status == FAIL:
        problems += 1
    print(f"{status} {text}")
    if hint:
        print(f"     → {hint}")


def main() -> int:
    try:  # консоль Windows в старой кодировке не должна падать на ✅/❌
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass
    print(f"Python {platform.python_version()} ({sys.executable})\n")

    if sys.version_info < (3, 11):
        report(FAIL, "Нужен Python 3.11 или новее", "установите свежий Python и пересоздайте .venv")
    else:
        report(OK, "Версия Python подходит")

    missing = []
    for mod in ("fastapi", "uvicorn", "multipart", "pymupdf", "PIL", "numpy", "pytesseract", "openai"):
        try:
            __import__(mod)
        except ImportError:
            missing.append(mod)
    if missing:
        report(FAIL, f"Не установлены пакеты: {', '.join(missing)}",
               "активируйте .venv и выполните: pip install -r requirements.txt")
        return 1
    report(OK, "Python-пакеты установлены")

    from . import config  # импорт после проверки пакетов: config читает .env

    base = config.BASE_DIR
    if platform.system() == "Windows" and not str(base).isascii():
        report(WARN, f"В пути к проекту есть не-латинские символы: {base}",
               "Tesseract на Windows может не загрузить модели. Перенесите проект, например, в C:\\redactor")

    env = base / ".env"
    report(OK if env.exists() else WARN, ".env найден" if env.exists() else ".env нет — используются значения по умолчанию",
           "" if env.exists() else "скопируйте .env.example в .env, если нужно что-то поменять")

    from . import ocr  # noqa: F401 — применяет TESSERACT_CMD из настроек
    import pytesseract
    try:
        version = pytesseract.get_tesseract_version()
    except Exception:
        report(FAIL, "Tesseract не найден",
               "установите Tesseract (см. docs/setup.md) или укажите путь в .env: TESSERACT_CMD=...")
        return 1
    if version.major < 4:
        report(FAIL, f"Tesseract {version} слишком старый", "нужна версия 4 или новее")
    else:
        report(OK, f"Tesseract {version}")

    prefix = os.environ.get("TESSDATA_PREFIX")
    tessdata = Path(prefix) if prefix else None
    where = str(tessdata) if tessdata else "моделей, установленных с Tesseract"
    need = [lang for lang in config.OCR_LANG.split("+")
            if tessdata and not (tessdata / f"{lang}.traineddata").exists()]
    if need:
        report(FAIL, f"Нет языковых моделей в {tessdata}: {', '.join(need)}",
               "скачайте rus.traineddata и eng.traineddata в папку tessdata (см. docs/setup.md)")
    else:
        try:
            langs = pytesseract.get_languages()
            lost = [lang for lang in config.OCR_LANG.split("+") if lang not in langs]
            if lost:
                report(FAIL, f"Tesseract не видит языки: {', '.join(lost)} (ищет в: {where})",
                       "скачайте модели в папку tessdata проекта (см. docs/setup.md); "
                       "на Windows путь к проекту — только латиницей")
            else:
                report(OK, f"Языки OCR: {config.OCR_LANG} (из {where})")
        except Exception as e:
            report(FAIL, f"Tesseract не смог прочитать модели: {e}")

    try:
        state = Path(config.STATE_DIR)
        state.mkdir(parents=True, exist_ok=True)
        probe = state / ".write_test"
        probe.write_text("ok")
        probe.unlink()
        report(OK, f"Каталог задач доступен для записи: {state}")
    except OSError as e:
        report(FAIL, f"Нельзя писать в каталог задач {config.STATE_DIR}: {e}", "поменяйте STATE_DIR в .env")

    if config.llm_enabled():
        try:
            from openai import OpenAI
            OpenAI(base_url=config.LLM_BASE_URL, api_key=config.LLM_API_KEY, timeout=10, max_retries=0).models.list()
            report(OK, f"LLM отвечает: {config.LLM_MODEL} @ {config.LLM_BASE_URL}")
        except Exception as e:
            report(WARN, f"LLM настроена, но недоступна ({type(e).__name__})",
                   "сервис будет работать на правилах; чтобы убрать предупреждение, закомментируйте LLM_* в .env")
    else:
        report(OK, "LLM выключена — работают только правила")

    print()
    print("Всё готово, можно запускать." if not problems else f"Найдено проблем: {problems}.")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
