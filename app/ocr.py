"""Растеризация страниц и распознавание текста с координатами слов."""
from dataclasses import dataclass

import numpy as np
import pymupdf
import pytesseract
from PIL import Image, ImageFilter

from . import config

if config.TESSERACT_CMD:
    pytesseract.pytesseract.tesseract_cmd = config.TESSERACT_CMD


@dataclass
class Word:
    text: str
    x0: float  # координаты в пикселях изображения, по которому шло распознавание
    y0: float
    x1: float
    y1: float
    line: tuple  # (block, par, line) — идентификатор строки Tesseract

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2


@dataclass
class PageOCR:
    image: Image.Image
    dpi: int
    words: list[Word]
    angle: float = 0.0  # на сколько градусов повёрнуто изображение для выравнивания

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)

    def lines(self) -> list[list[Word]]:
        out: dict[tuple, list[Word]] = {}
        for w in self.words:
            out.setdefault(w.line, []).append(w)
        return list(out.values())


def render(page: pymupdf.Page, dpi: int, angle: float = 0.0) -> Image.Image:
    pix = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csRGB, alpha=False)
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    if angle:
        img = img.rotate(angle, resample=Image.BICUBIC, fillcolor="white")
    return img


def estimate_skew(img: Image.Image, max_angle: float = 3.0) -> float:
    """Угол наклона скана (градусы) по резкости горизонтальной проекции."""
    small = img.convert("L")
    small.thumbnail((1000, 1000))
    best, best_score = 0.0, -1.0
    steps = [a / 10 for a in range(int(-max_angle * 10), int(max_angle * 10) + 1)]
    for a in steps:
        rot = np.asarray(small.rotate(a, fillcolor=255)) < 150
        prof = rot.sum(axis=1).astype(np.float64)
        score = float(np.square(np.diff(prof)).sum())
        if score > best_score:
            best, best_score = a, score
    return best


def _long_runs(dark: np.ndarray, k: int) -> np.ndarray:
    """Маска пикселей, входящих в горизонтальный сплошной отрезок длиной ≥ k."""
    h, w = dark.shape
    cs = np.zeros((h, w + 1), np.int32)
    np.cumsum(dark, axis=1, out=cs[:, 1:])
    runs = (cs[:, k:] - cs[:, :-k]) == k
    rc = np.zeros((h, runs.shape[1] + 1), np.int32)
    np.cumsum(runs, axis=1, out=rc[:, 1:])
    lo = np.clip(np.arange(w) - k + 1, 0, runs.shape[1])
    hi = np.clip(np.arange(w) + 1, 0, runs.shape[1])
    return (rc[:, hi] - rc[:, lo]) > 0


def remove_lines(img: Image.Image) -> Image.Image:
    """Копия для OCR без линий таблиц: они мешают Tesseract собирать строки."""
    gray = np.asarray(img.convert("L"))
    dark = gray < 150
    k = max(40, img.width // 30)
    mask = _long_runs(dark, k) | _long_runs(dark.T, k).T
    mask = np.asarray(Image.fromarray(mask.astype(np.uint8) * 255).filter(ImageFilter.MaxFilter(5))) > 0
    out = gray.copy()
    out[mask] = 255
    return Image.fromarray(out)


def ocr_image(img: Image.Image, dpi: int) -> PageOCR:
    data = pytesseract.image_to_data(
        remove_lines(img), lang=config.OCR_LANG, config="--psm 3", output_type=pytesseract.Output.DICT
    )
    words = []
    for i, text in enumerate(data["text"]):
        text = (text or "").strip()
        if not text:
            continue
        x, y, w, h = data["left"][i], data["top"][i], data["width"][i], data["height"][i]
        words.append(Word(text, x, y, x + w, y + h,
                          (data["block_num"][i], data["par_num"][i], data["line_num"][i])))
    return PageOCR(img, dpi, words)


def ocr_page(page: pymupdf.Page, dpi: int | None = None) -> PageOCR:
    dpi = dpi or config.OCR_DPI
    angle = estimate_skew(render(page, 100))
    result = ocr_image(render(page, dpi, angle), dpi)
    result.angle = angle
    return result
