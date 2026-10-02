"""Веб-сервис: загрузка PDF → очередь → проверка плашек пользователем → обезличенный PDF.

Задачи хранятся в STATE_DIR (см. app/store.py) и переживают перезапуск службы: задачи из
очереди и незавершённые продолжают обрабатываться, проверенные можно собрать.
Загруженный файл удаляется сразу после анализа, остальное — через RESULT_TTL_MIN минут
без активности.
"""
import asyncio
import logging
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from . import config, store
from .pipeline import ProcessingError, analyze, build_pdf

log = logging.getLogger("redactor")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

KINDS = {"auto", "contract", "act"}
NO_STORE = {"Cache-Control": "no-store"}


@dataclass
class Job:
    id: str
    filename: str
    kind: str
    status: str = "queued"          # queued | processing | review | error
    stage: str = ""
    error: str = ""
    report: dict | None = None
    pages: list[dict] = field(default_factory=list)   # src_page, width_pt, height_pt, boxes
    attempts: int = 0
    created: float = field(default_factory=time.time)
    touched: float = field(default_factory=time.time)

    def save(self) -> None:
        store.save_state(self.id, asdict(self))


jobs: dict[str, Job] = {}
queue: asyncio.Queue[str] = asyncio.Queue()
order: list[str] = []  # id в очереди, для отображения позиции


def enqueue(job: Job) -> None:
    order.append(job.id)
    queue.put_nowait(job.id)


def fail(job: Job, message: str) -> None:
    job.status, job.error, job.stage = "error", message, ""
    job.touched = time.time()
    job.save()
    store.drop_source(job.id)


async def worker():
    loop = asyncio.get_running_loop()
    while True:
        job_id = await queue.get()
        if job_id in order:
            order.remove(job_id)
        job = jobs.get(job_id)
        if not job or job.status != "queued":
            queue.task_done()
            continue
        # Счётчик сохраняется до начала работы: если процесс упадёт на этом файле,
        # после перезапуска будет видно, сколько раз уже пробовали.
        job.attempts += 1
        if job.attempts > config.MAX_ATTEMPTS:
            fail(job, "Не удалось обработать файл: обработка прерывалась несколько раз.")
            queue.task_done()
            continue
        job.status, job.stage = "processing", ""
        job.save()
        started = time.time()

        def progress(stage: str, job=job):
            job.stage = stage
            job.save()

        try:
            src = await loop.run_in_executor(None, store.load_source, job.id)
            drafts, report = await loop.run_in_executor(None, lambda: analyze(src, job.kind, progress=progress))
            del src
            await loop.run_in_executor(None, store.save_pages, job.id, drafts)
            job.pages = [{"src_page": d.src_page, "width_pt": d.width_pt, "height_pt": d.height_pt,
                          "boxes": d.boxes} for d in drafts]
            report.items = [{"page": i["page"], "category": i["category"], "source": i["source"]}
                            for i in report.items]  # найденный текст (ПДн) не сохраняем
            job.report, job.status, job.stage = asdict(report), "review", ""
            job.touched = time.time()
            job.save()
            store.drop_source(job.id)
            log.info("job %s проанализирован за %.0f c, страницы: %s", job.id, time.time() - started, report.pages)
        except ProcessingError as e:
            fail(job, str(e))
        except FileNotFoundError:
            fail(job, "Загруженный файл не найден — загрузите его заново.")
        except Exception:
            # Сюда же попадает остановка службы: вместе с ней система убивает процесс Tesseract.
            # Поэтому не бросаем задачу, а возвращаем в очередь — исходник пока на месте.
            log.exception("job %s прерван (попытка %d из %d)", job.id, job.attempts, config.MAX_ATTEMPTS)
            if job.attempts < config.MAX_ATTEMPTS:
                job.status, job.stage = "queued", ""
                job.save()
                enqueue(job)
            else:
                fail(job, "Внутренняя ошибка обработки. Попробуйте ещё раз или обратитесь к администратору.")
        finally:
            queue.task_done()


def restore() -> None:
    """Поднимает задачи, сохранённые до перезапуска."""
    resumed = 0
    for state in sorted(store.load_states(), key=lambda s: s.get("created", 0)):
        try:
            job = Job(**state)
        except TypeError:
            store.delete(state.get("id", ""))
            continue
        job.touched = time.time()  # время простоя сервера не засчитываем в срок хранения
        jobs[job.id] = job
        if job.status in ("queued", "processing"):
            job.status, job.stage = "queued", ""
            job.save()
            enqueue(job)
            resumed += 1
    if jobs:
        log.info("восстановлено задач: %d, возвращено в очередь: %d", len(jobs), resumed)


async def janitor():
    """Удаляет брошенные задачи."""
    while True:
        limit = time.time() - config.RESULT_TTL_MIN * 60
        for job_id, job in list(jobs.items()):
            if job.status not in ("queued", "processing") and job.touched < limit:
                jobs.pop(job_id, None)
                store.delete(job_id)
        await asyncio.sleep(60)


@asynccontextmanager
async def lifespan(app: FastAPI):
    restore()
    tasks = [asyncio.create_task(worker()) for _ in range(config.WORKERS)]
    tasks.append(asyncio.create_task(janitor()))
    log.info("воркеров: %d, хранилище: %s, LLM: %s", config.WORKERS, config.STATE_DIR,
             f"{config.LLM_MODEL} @ {config.LLM_BASE_URL}" if config.llm_enabled() else "выключена")
    yield
    for t in tasks:
        t.cancel()


app = FastAPI(title="Обезличивание договоров", lifespan=lifespan)
STATIC = Path(__file__).parent / "static"


def _job(job_id: str) -> Job:
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Задача не найдена или уже удалена (истёк срок хранения)")
    job.touched = time.time()
    return job


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.post("/api/jobs")
async def create_job(file: UploadFile = File(...), kind: str = Form("auto")):
    if kind not in KINDS:
        raise HTTPException(400, "Неизвестный тип документа")
    data = await file.read(config.MAX_UPLOAD_MB * 1024 * 1024 + 1)
    if len(data) > config.MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(413, f"Файл больше {config.MAX_UPLOAD_MB} МБ")
    if not data.startswith(b"%PDF"):
        raise HTTPException(400, "Это не PDF-файл")
    job = Job(uuid.uuid4().hex, file.filename or "document.pdf", kind)
    store.save_source(job.id, data)
    job.save()  # job.json пишется последним: без него каталог при старте считается мусором
    jobs[job.id] = job
    enqueue(job)
    return _public(job)


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    return _public(_job(job_id))


@app.get("/api/jobs/{job_id}/pages/{n}.jpg")
def page_preview(job_id: str, n: int):
    job = _job(job_id)
    if job.status != "review" or not 0 <= n < len(job.pages):
        raise HTTPException(404, "Нет такой страницы")
    return FileResponse(store.preview_path(job.id, n), media_type="image/jpeg", headers=NO_STORE)


class Box(BaseModel):
    x0: float = Field(ge=0, le=1)
    y0: float = Field(ge=0, le=1)
    x1: float = Field(ge=0, le=1)
    y1: float = Field(ge=0, le=1)


class PageChoice(BaseModel):
    keep: bool = True
    boxes: list[Box] = []


class BuildRequest(BaseModel):
    pages: list[PageChoice]


@app.post("/api/jobs/{job_id}/build")
def build(job_id: str, req: BuildRequest):
    job = _job(job_id)
    if job.status != "review":
        raise HTTPException(409, "Документ ещё не готов")
    if len(req.pages) != len(job.pages):
        raise HTTPException(400, "Число страниц не совпадает")
    kept = [n for n, p in enumerate(req.pages) if p.keep]
    if not kept:
        raise HTTPException(400, "Не выбрано ни одной страницы")
    try:
        drafts = [store.load_draft(job.id, n, job.pages[n]) for n in kept]
    except FileNotFoundError:
        raise HTTPException(410, "Страницы документа удалены — загрузите файл заново")
    data = build_pdf(drafts, [[b.model_dump() for b in req.pages[n].boxes] for n in kept])
    log.info("job %s: собран PDF, страниц %d из %d, плашек: %d", job.id, len(kept), len(job.pages),
             sum(len(req.pages[n].boxes) for n in kept))
    name = Path(job.filename).stem + "_обезличено.pdf"
    return Response(data, media_type="application/pdf", headers={
        **NO_STORE,
        "Content-Disposition": f"attachment; filename=\"redacted.pdf\"; filename*=UTF-8''{quote(name)}",
    })


@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: str):
    job = jobs.get(job_id)
    if job and job.status not in ("queued", "processing"):
        jobs.pop(job_id, None)
        store.delete(job_id)
    return {"ok": True}


def _public(job: Job) -> dict:
    report = None
    if job.report:
        # Сами закрытые фрагменты наружу не отдаём — только категории и страницы.
        report = {**job.report, "items": [{"page": i["page"], "category": i["category"]}
                                          for i in job.report["items"]]}
    return {
        "id": job.id,
        "filename": job.filename,
        "status": job.status,
        "stage": job.stage,
        "position": order.index(job.id) + 1 if job.id in order else 0,
        "error": job.error,
        "report": report,
        "pages": [{"src_page": p["src_page"], "aspect": p["height_pt"] / p["width_pt"], "boxes": p["boxes"]}
                  for p in job.pages],
    }
