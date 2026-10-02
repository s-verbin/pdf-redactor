"""Хранение задач вне памяти процесса, чтобы перезапуск службы не терял работу пользователей.

Каталог задачи STATE_DIR/<id>/:
    job.json        — состояние, отчёт, предложенные плашки
    source.pdf      — загруженный файл; удаляется сразу после анализа
    page_N.jpg      — выровненная страница без закраски (для сборки PDF)
    prev_N.jpg      — уменьшенное превью для браузера

Рекомендуется держать STATE_DIR в tmpfs (/run/redactor): данные переживают перезапуск
службы, но не попадают на физический диск.
"""
import json
import os
import shutil
from pathlib import Path

from . import config
from .pipeline import PageDraft


def root() -> Path:
    path = Path(config.STATE_DIR)
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def job_dir(job_id: str) -> Path:
    if not job_id.isalnum():  # id — uuid4().hex; защита от путей вида ../
        raise ValueError("bad job id")
    return root() / job_id


def save_state(job_id: str, state: dict) -> None:
    d = job_dir(job_id)
    d.mkdir(exist_ok=True, mode=0o700)
    tmp = d / "job.json.tmp"
    tmp.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, d / "job.json")  # атомарно: при падении не останется полузаписанного файла


def load_states() -> list[dict]:
    states = []
    for d in root().iterdir():
        f = d / "job.json"
        try:
            states.append(json.loads(f.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            shutil.rmtree(d, ignore_errors=True)  # мусор от прерванной загрузки
    return states


def save_source(job_id: str, data: bytes) -> None:
    d = job_dir(job_id)
    d.mkdir(exist_ok=True, mode=0o700)
    (d / "source.pdf").write_bytes(data)


def load_source(job_id: str) -> bytes:
    return (job_dir(job_id) / "source.pdf").read_bytes()


def drop_source(job_id: str) -> None:
    (job_dir(job_id) / "source.pdf").unlink(missing_ok=True)


def save_pages(job_id: str, drafts: list[PageDraft]) -> None:
    d = job_dir(job_id)
    for n, draft in enumerate(drafts):
        (d / f"page_{n}.jpg").write_bytes(draft.image)
        (d / f"prev_{n}.jpg").write_bytes(draft.preview)


def preview_path(job_id: str, n: int) -> Path:
    return job_dir(job_id) / f"prev_{n}.jpg"


def load_draft(job_id: str, n: int, page: dict) -> PageDraft:
    image = (job_dir(job_id) / f"page_{n}.jpg").read_bytes()
    return PageDraft(page["src_page"], page["width_pt"], page["height_pt"], image, page["boxes"])


def delete(job_id: str) -> None:
    shutil.rmtree(job_dir(job_id), ignore_errors=True)
