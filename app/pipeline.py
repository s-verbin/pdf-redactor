"""Полный цикл: OCR всех страниц → поиск данных → (проверка пользователем) → закраска → PDF из картинок.

Итоговый PDF собирается из растровых изображений, в которых чёрные прямоугольники
«впечатаны» в пиксели. Текстового слоя, аннотаций и метаданных нет — снять закраску
в PDF-редакторе невозможно, под ней нет исходных данных.
"""
import io
import logging
import re
from dataclasses import dataclass, field
from typing import Callable

import pymupdf
from PIL import Image, ImageDraw

from . import config
from .detect import CATEGORY_NAMES, detect
from .ocr import ocr_page, render

log = logging.getLogger(__name__)

Progress = Callable[[str], None]


class ProcessingError(Exception):
    pass


# Латинские буквы, которые OCR путает с кириллицей
_HOMOGLYPHS = str.maketrans("aekmhopctxyb", "аекмнорстхув")


def _norm(t: str) -> str:
    return re.sub(r"\s+", " ", t.lower().replace("ё", "е").translate(_HOMOGLYPHS))


def detect_kind(first_page_text: str) -> str:
    head = _norm(first_page_text)[:600]
    if re.search(r"акт\w*\s+(приема|приемки|возврата)", head) or "приема-передачи" in head[:120]:
        return "act"
    return "contract"


_SIGN_RE = re.compile(r"подпис\w*\s*сторон")
_APPENDIX_RE = re.compile(r"приложени\w*\s*(№|n[eo]|no)?\s*\d+\s*к\s+договор")


def suggest_contract_pages(texts: list[str]) -> list[int]:
    """Подсказка для договора: стр. 1 и страница с подписями в конце основного текста.

    Возвращает индексы (с 0). Если страницу с подписями найти не удалось — только [0].
    """
    first_appendix = None
    for i in range(1, len(texts)):
        text = _norm(texts[i])
        if _APPENDIX_RE.search(text[:250]):
            first_appendix = i  # приложения тоже подписаны — дальше не ищем
            break
        if _SIGN_RE.search(text) and "арендодател" in text and "арендатор" in text:
            return [0, i]
    if first_appendix and first_appendix > 1:
        return [0, first_appendix - 1]
    return [0]


@dataclass
class PageDraft:
    """Страница, подготовленная к проверке пользователем."""
    src_page: int                 # номер в исходнике (с 1)
    width_pt: float
    height_pt: float
    image: bytes                  # JPEG выровненной страницы итогового разрешения, без закраски
    boxes: list[dict]             # {x0,y0,x1,y1 в долях 0..1, category}
    preview: bytes = b""          # уменьшенный JPEG для браузера


@dataclass
class Report:
    doc_kind: str = ""
    pages: list[int] = field(default_factory=list)       # номера исходных страниц (с 1)
    suggested: list[int] = field(default_factory=list)   # какие страницы предлагается оставить (с 1)
    items: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    llm_used: bool = False


PREVIEW_WIDTH = 1200


def _jpeg(img: Image.Image, quality: int) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def analyze(pdf_bytes: bytes, kind: str = "auto", use_llm: bool | None = None,
            progress: Progress = lambda s: None) -> tuple[list[PageDraft], Report]:
    """Шаг 1: OCR всех страниц и предложение областей для закрытия."""
    if use_llm is None:
        use_llm = config.llm_enabled()
    try:
        src = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    except Exception as e:
        raise ProcessingError("Файл не открывается как PDF.") from e
    if src.page_count == 0:
        raise ProcessingError("В PDF нет страниц.")

    report = Report(llm_used=use_llm)
    drafts, texts = [], []
    for pno in range(src.page_count):
        progress(f"Распознаю страницу {pno + 1} из {src.page_count}")
        page = ocr_page(src[pno])
        texts.append(page.text)
        if pno == 0 and kind == "auto":
            kind = detect_kind(page.text)
        hits, rects, llm_err = detect(page, kind, use_llm)
        if llm_err and not any("LLM" in w for w in report.warnings):
            report.warnings.append(f"LLM недоступна, использованы только правила: {llm_err[:200]}")
        for h in hits:
            report.items.append({"page": pno + 1, "category": CATEGORY_NAMES[h.category],
                                 "source": h.source, "text": h.text})
        W, H = page.image.size
        boxes = [{"x0": max(0.0, x0 / W), "y0": max(0.0, y0 / H),
                  "x1": min(1.0, x1 / W), "y1": min(1.0, y1 / H),
                  "category": CATEGORY_NAMES[cat]}
                 for (x0, y0, x1, y1), cat in rects]
        # Страница хранится в JPEG высокого качества: PNG на 30+ страниц занял бы ~100 МБ.
        img = render(src[pno], config.OUTPUT_DPI, page.angle)
        full = _jpeg(img, 92)
        img.thumbnail((PREVIEW_WIDTH, PREVIEW_WIDTH * 2))
        rect = src[pno].rect
        drafts.append(PageDraft(pno + 1, rect.width, rect.height, full, boxes, _jpeg(img, 80)))

    report.doc_kind = kind
    report.pages = [d.src_page for d in drafts]
    if kind == "contract":
        report.suggested = [i + 1 for i in suggest_contract_pages(texts)]
        if len(report.suggested) < 2:
            report.warnings.append("Не удалось определить страницу договора с подписями сторон.")
    else:
        report.suggested = list(report.pages)
    if not report.items:
        report.warnings.append("Не найдено ни одного фрагмента для закрытия — проверьте документ вручную.")
    src.close()
    return drafts, report


def build_pdf(drafts: list[PageDraft], boxes_per_page: list[list[dict]] | None = None,
              debug_dir: str | None = None) -> bytes:
    """Шаг 2: закраска в пикселях и сборка нового PDF только из картинок.

    В PDF попадают все переданные страницы — исключённые пользователем сюда не передаются.
    """
    if not drafts:
        raise ProcessingError("Не выбрано ни одной страницы.")
    out = pymupdf.open()
    for i, d in enumerate(drafts):
        boxes = d.boxes if boxes_per_page is None else boxes_per_page[i]
        with Image.open(io.BytesIO(d.image)) as src_img:
            img = src_img.convert("RGB")
        W, H = img.size
        draw = ImageDraw.Draw(img)
        for b in boxes:
            x0, x1 = sorted((float(b["x0"]), float(b["x1"])))
            y0, y1 = sorted((float(b["y0"]), float(b["y1"])))
            draw.rectangle([x0 * W, y0 * H, x1 * W, y1 * H], fill="black")
        if debug_dir:
            img.save(f"{debug_dir}/page_{d.src_page:02d}.png")
        page = out.new_page(width=d.width_pt, height=d.height_pt)
        page.insert_image(page.rect, stream=_jpeg(img, config.JPEG_QUALITY))
    out.set_metadata({})
    out.del_xml_metadata()
    data = out.tobytes(garbage=4, deflate=True, clean=True)
    out.close()
    return data


def process(pdf_bytes: bytes, kind: str = "auto", use_llm: bool | None = None,
            progress: Progress = lambda s: None, debug_dir: str | None = None,
            keep: str = "all") -> tuple[bytes, Report]:
    """Автоматический режим (CLI): анализ + сборка с предложенными областями.

    keep: "all" — все страницы, "suggested" — предложенные, либо список номеров «1,15».
    """
    drafts, report = analyze(pdf_bytes, kind, use_llm, progress)
    if keep == "all":
        pages = report.pages
    elif keep == "suggested":
        pages = report.suggested
    else:
        pages = [int(p) for p in keep.split(",") if p.strip()]
    chosen = [d for d in drafts if d.src_page in pages]
    return build_pdf(chosen, debug_dir=debug_dir), report
