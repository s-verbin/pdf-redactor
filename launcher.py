"""Запуск PDF Redactor как обычной программы: поднимает сервис на этом компьютере и открывает браузер."""
import os
import socket
import sys
import threading
import webbrowser
from pathlib import Path

# Папка, где лежит exe (при запуске из исходников — папка этого файла)
BASE = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent

# Встроенный Tesseract лежит рядом с exe в папке tesseract\
bundled = BASE / "tesseract" / ("tesseract.exe" if os.name == "nt" else "tesseract")
if bundled.exists():
    os.environ.setdefault("TESSERACT_CMD", str(bundled))
# Задачи — в профиле пользователя: туда запись разрешена всегда
os.environ.setdefault("STATE_DIR", str(Path(os.environ.get("LOCALAPPDATA", Path.home())) / "pdf-redactor"))

import uvicorn  # noqa: E402

from app.main import app  # noqa: E402


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


port = free_port()
url = f"http://127.0.0.1:{port}"
print(f"PDF Redactor запущен: {url}\nНе закрывайте это окно, пока работаете. Закрыли окно — программа остановилась.",
      flush=True)
threading.Timer(1.5, lambda: webbrowser.open(url)).start()
uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
