"""Поиск линий таблиц на скане — чтобы закрашивать ячейку значения целиком."""
import numpy as np
from PIL import Image


class Grid:
    def __init__(self, img: Image.Image):
        gray = np.asarray(img.convert("L"))
        self.h, self.w = gray.shape
        dark = gray < 150
        # Небольшое утолщение по вертикали, чтобы слегка перекошенные линии не рвались.
        thick = dark.copy()
        for s in (1, 2):
            thick[s:] |= dark[:-s]
            thick[:-s] |= dark[s:]
        self.dark = dark
        k = max(20, self.w // 50)  # минимальная длина сплошного отрезка линии
        cs = np.zeros((self.h, self.w + 1), dtype=np.int32)
        np.cumsum(thick, axis=1, out=cs[:, 1:])
        runs = (cs[:, k:] - cs[:, :-k]) == k  # в точке x начинается сплошной отрезок длиной k
        # Покрытие линии: точка x лежит внутри хотя бы одного такого отрезка.
        rc = np.zeros((self.h, runs.shape[1] + 1), dtype=np.int32)
        np.cumsum(runs, axis=1, out=rc[:, 1:])
        lo = np.clip(np.arange(self.w) - k + 1, 0, runs.shape[1])
        hi = np.clip(np.arange(self.w) + 1, 0, runs.shape[1])
        cov = (rc[:, hi] - rc[:, lo]) > 0
        self.hcov = cov
        rows = np.where(cov.sum(axis=1) > 0.15 * self.w)[0]
        self.hlines = _merge(rows)

    def _hline_covers(self, y: int, x0: float, x1: float) -> bool:
        x0, x1 = int(max(0, x0)), int(min(self.w, x1))
        if x1 <= x0:
            return False
        ys = slice(max(0, y - 6), min(self.h, y + 7))
        return self.hcov[ys, x0:x1].any(axis=0).mean() > 0.75

    def vlines(self, y0: int, y1: int) -> list[int]:
        y0, y1 = y0 + 4, y1 - 4
        if y1 - y0 < 5:
            return []
        band = self.dark[y0:y1]
        thick = band.copy()
        for s in (1, 2):
            thick[:, s:] |= band[:, :-s]
            thick[:, :-s] |= band[:, s:]
        cols = np.where(thick.mean(axis=0) > 0.9)[0]
        return _merge(cols)

    def cell(self, x0: float, y0: float, x1: float, y1: float,
             max_h: float = 0.15, max_w: float = 0.7):
        """Ячейка таблицы, содержащая прямоугольник, или None."""
        above = [y for y in self.hlines if y < y0 + 2 and self._hline_covers(y, x0, x1)]
        below = [y for y in self.hlines if y > y1 - 2 and self._hline_covers(y, x0, x1)]
        if not above or not below:
            return None
        top, bottom = max(above), min(below)
        if bottom - top > max_h * self.h:
            return None
        vs = self.vlines(top, bottom)
        left = [x for x in vs if x <= x0 + 2]
        right = [x for x in vs if x >= x1 - 2]
        if not left or not right:
            return None
        l, r = max(left), min(right)
        if r - l > max_w * self.w:
            return None
        return (l, top, r, bottom)

    def value_cell_right_of(self, word_x1: float, y0: float, y1: float):
        """Для подписи строки таблицы (левая колонка) — ячейка значения справа."""
        above = [y for y in self.hlines if y < y0 + 2]
        below = [y for y in self.hlines if y > y1 - 2]
        if not above or not below:
            return None
        top, bottom = max(above), min(below)
        if bottom - top > 0.12 * self.h:
            return None
        vs = self.vlines(top, bottom)
        right = [x for x in vs if x > word_x1]
        left = [x for x in vs if x < word_x1]
        if len(right) < 2 or not left:
            return None
        label_w = right[0] - max(left)
        if label_w > 0.5 * self.w:  # это не узкая колонка подписи, а обычный абзац
            return None
        l, r = right[0], right[1]
        if r - l < 0.12 * self.w:
            return None
        return (l, top, r, bottom)


def _merge(idx: np.ndarray, gap: int = 3) -> list[int]:
    """Сливает соседние индексы в одну линию, возвращает центры."""
    out, start, prev = [], None, None
    for v in idx:
        v = int(v)
        if start is None:
            start = prev = v
        elif v - prev <= gap:
            prev = v
        else:
            out.append((start + prev) // 2)
            start = prev = v
    if start is not None:
        out.append((start + prev) // 2)
    return out
