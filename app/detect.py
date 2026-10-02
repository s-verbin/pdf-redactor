"""Поиск конфиденциальных фрагментов на странице: правила + внутренняя LLM."""
import difflib
import logging
import re
from dataclasses import dataclass, field

from . import llm
from .grid import Grid
from .ocr import PageOCR, Word

log = logging.getLogger(__name__)

CATEGORY_NAMES = {
    "money": "Сумма",
    "passport": "Паспорт",
    "address": "Адрес собственника",
    "birth": "Дата/место рождения",
    "phone": "Телефон",
    "email": "E-mail",
    "owner": "Данные собственника (всё, кроме ФИО/ИНН/ОГРНИП)",
}


@dataclass
class Hit:
    category: str
    text: str
    source: str             # rule | table | llm
    rects: list[tuple] = field(default_factory=list)  # готовые прямоугольники (ячейки таблиц)
    words: list[Word] = field(default_factory=list)   # найденные слова (для rule/llm)


# ---------------------------------------------------------------- текстовый поток

class Stream:
    """Слова страницы, склеенные в строку, с отображением символов обратно на слова."""

    def __init__(self, words: list[Word]):
        self.words = words
        parts, self.spans = [], []
        pos = 0
        for w in words:
            self.spans.append((pos, pos + len(w.text)))
            parts.append(w.text)
            pos += len(w.text) + 1
        self.text = " ".join(parts)

    def words_in(self, start: int, end: int) -> list[Word]:
        return [w for w, (a, b) in zip(self.words, self.spans) if a < end and b > start]


# ---------------------------------------------------------------- правила

_NUM = r"\d{1,3}(?:[  ]?\d{3})*(?:[.,]\d{1,2})?"
MONEY_RES = [
    # 150 000,00 (сто пятьдесят тысяч) рублей 00 копеек
    re.compile(_NUM + r"\s*(?:\([^()]{0,300}\)\s*)?(?:руб\w*|₽|р\.)\.?(?:\s*\d{1,2}\s*коп\w*\.?)?", re.I),
    # сумма прописью в скобках, где есть «рубл»
    re.compile(r"\([^()]{0,300}?\bрубл[^()]{0,100}\)", re.I),
    # денежный формат без «руб.» (сметы, таблицы расчётов): 1 250 000,00 / 48 300,50 / 150,00.
    # Ровно две цифры после запятой — площади вроде «120,5» и «85,3» не подходят.
    # Первая группа — любая длина: OCR иногда склеивает разряды («1250 000,00»).
    re.compile(r"(?<![\d.,:/])\d+(?:[ \u00a0]\d{3})*,\d{2}(?![\d,.])"
               r"(?!\s*(?:кв|м2|м²|м3|м³|%|квт|kw|га|шт|мм|см|км|°))", re.I),
]
PASSPORT_RE = re.compile(
    r"паспорт\w*[\s\S]{0,250}?(?:код\w*\s+подразделени\w*\s*:?\s*\d{3}\s*[-–—]?\s*\d{3}|"
    r"(?=,\s*(?:зарегистр|ОГРН|ИНН|мест\w*\s+рожд|адрес)))", re.I)
BIRTH_RES = [
    re.compile(r"\d{1,2}(?:\s+[а-яё]+\s+|\.\d{2}\.)\d{4}\s*(?:года?\s+рождения|г\.?\s*р\.?)", re.I),
    re.compile(r"(?:мест\w*|гор\.?|город)\s*рождени\w*\s*:?\s*[^,]{2,80}", re.I),
    re.compile(r"рождени\w*\s*:?\s*\d{1,2}[.\s][\s\S]{0,40}?\d{4}", re.I),
]
ADDRESS_RE = re.compile(
    r"(?:зарегистрирова\w*\s+по\s+адресу|адрес\w*\s+(?:регистрации|проживания|места\s+жительства)"
    r"|адрес\w*\s+для\s+корреспонденции|почтов\w*\s+адрес|проживающ\w*\s+по\s+адресу)\s*:?\s*"
    r"(?P<v>[\s\S]{3,160}?)(?=,?\s*(?:[сc¢]\s+одной\s+стороны|ОГРН|ИНН|паспорт|тел\w*|e-?mail|эл\.|"
    r"гражданств|дата|пол:|\d{9,})|;|$)", re.I)
PHONE_RE = re.compile(r"(?:\+7|\b8)[\s\-(]*\d{3}[\s\-)]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}\b")
EMAIL_RE = re.compile(r"[\w.+\-]+@[\w\-]+(?:\.[\w\-]+)+")

# Подписи строк в таблице реквизитов → категория ячейки значения
TABLE_LABELS = [
    (re.compile(r"паспорт", re.I), "passport"),
    (re.compile(r"рождени", re.I), "birth"),
    (re.compile(r"регистрац|корреспонд|проживан|жительств", re.I), "address"),
    (re.compile(r"телефон|тел\.", re.I), "phone"),
    (re.compile(r"e-?mail|почт", re.I), "email"),
]


_HOMOGLYPHS = str.maketrans("aekmhopctxyb", "аекмнорстхув")


def _clean(t: str) -> str:
    """Слово в нижнем регистре без мусора по краям и с кириллицей вместо похожей латиницы."""
    return re.sub(r"^\W+|\W+$", "", t.lower().replace("ё", "е").translate(_HOMOGLYPHS))


# Начало блока арендатора. Заголовок «АРЕНДАТОР» OCR иногда теряет, поэтому есть запасные маркеры.
_TENANT_RE = re.compile(r"^(арендатор|акционерн|обществ|местонахожден|огрн$)")


# Признаки того, что в блоке действительно реквизиты собственника, а не текст условий договора.
_ANCHOR_RE = re.compile(r"^(паспорт|рождени|зарегистр|регистрац|корреспонд|проживан)")


def owner_scope(page: PageOCR) -> tuple[float, float] | None:
    """Вертикальный диапазон блока реквизитов арендодателя или None, если его на странице нет.

    Блок начинается с заголовка «АРЕНДОДАТЕЛЬ» (заглавными, в кавычках или с двоеточием —
    так он оформлен в шапке договора и в реквизитах; в тексте условий слово пишется обычно)
    и заканчивается на блоке арендатора. Считается найденным, только если внутри есть
    паспорт или адрес регистрации: в подписях приложений тоже есть «АРЕНДОДАТЕЛЬ:».
    """
    def is_header(w: Word) -> bool:
        t = _clean(w.text)
        letters = re.sub(r"[^а-яa-z]", "", w.text.lower())
        return t.startswith("арендодател") and (
            w.text.upper() == w.text or ":" in w.text or "«" in w.text or '"' in w.text) and len(letters) > 5

    lines = page.lines()
    tops = [w.y0 - 5 for w in page.words if is_header(w)]
    # Заголовок OCR может исказить до неузнаваемости — тогда ищем «Индивидуальный предприниматель».
    tops += [w.y0 - 5 for w in page.words if _clean(w.text).startswith(("индивидуальн", "предпринимател"))]
    for start in sorted(set(tops)):
        ends = [w.y0 - 5 for w in page.words if w.y0 > start + 10 and _TENANT_RE.search(_clean(w.text))]
        # Абзац о стороне заканчивается словами «с одной/другой стороны» — важно, когда
        # абзац арендатора стоит выше (соглашения в приложениях), а ниже идёт текст соглашения.
        # На фото строки изогнуты и перекрываются по высоте, поэтому граница — низ всех строк,
        # начавшихся раньше, чем закончилось слово «стороны» (иначе хвост адреса останется открытым).
        for w in page.words:
            if w.y0 > start + 10 and _clean(w.text).startswith("сторон") and any(
                    _clean(x.text) in ("одной", "другой") for x in page.words
                    if x.line == w.line and x.x1 <= w.x0 + 5):
                ends.append(max(max(x.y1 for x in ln) for ln in lines
                                if start < min(x.y0 for x in ln) < w.y1 - 5) + 5)
        end = min(ends) if ends else page.image.height
        if any(start <= w.cy < end and _ANCHOR_RE.match(_clean(w.text)) for w in page.words):
            return start, end
    return None


_KEEP_RE = re.compile(r"^(арендодател\w*|индивидуальн\w*|предпринимател\w*|ип|[сc¢]|одной|сторон\w*|и)$")
_ID_RE = re.compile(r"^(огрнип|инн|огрн)$")


def _owner_paragraph_hit(words: list[Word]) -> Hit | None:
    """Абзац об арендодателе-ИП: закрываем всё, кроме ФИО, ОГРНИП, ИНН и служебных слов.

    Работает «от обратного», поэтому устойчив к ошибкам OCR: исковерканные паспорт,
    дата рождения или адрес всё равно будут закрыты.
    """
    lows = [_clean(w.text) for w in words]
    if not any(t.startswith("предпринимател") for t in lows):
        return None
    if any(t.startswith(("фио", "расчетн", "бик")) for t in lows):
        return None  # это таблица реквизитов, для неё свои правила
    keep = set()
    i = 0
    while i < len(words):
        t = lows[i]
        if not re.search(r"\w", t) or _KEEP_RE.match(t):
            keep.add(i)
        if t.startswith("предпринимател"):
            # ФИО: до трёх слов с заглавной буквы, до первой запятой
            j = i + 1
            while j < len(words) and j <= i + 3 and words[j].text[:1].isupper():
                keep.add(j)
                if words[j].text.endswith(","):
                    break
                j += 1
        if _ID_RE.match(t) and i + 1 < len(words) and sum(c.isdigit() for c in words[i + 1].text) >= 10:
            keep.update((i, i + 1))
            i += 1
        i += 1
    rest = [w for k, w in enumerate(words) if k not in keep]
    if not rest:
        return None
    return Hit("owner", " ".join(w.text for w in rest), "rule", words=rest)


def _rule_hits(page: PageOCR, grid: Grid) -> list[Hit]:
    hits: list[Hit] = []
    full = Stream(page.words)
    margin = 0.07 * page.image.width  # рукописные пометки на полях («ИП Иванов И.И.») не трогаем
    scope = owner_scope(page)
    if scope:
        y0, y1 = scope
        owner = Stream([w for w in page.words if y0 <= w.cy < y1 and w.cx > margin])
    else:
        # Блока реквизитов нет (условия договора, приложения): ищем персональные данные
        # по всей странице. Возможны лишние срабатывания — их уберёт пользователь.
        y0, y1 = 0, page.image.height
        owner = Stream([w for w in page.words if w.cx > margin])

    def add(stream: Stream, m: re.Match, cat: str, group: str | None = None):
        a, b = (m.start(group), m.end(group)) if group and m.group(group) else (m.start(), m.end())
        words = stream.words_in(a, b)
        if words:
            hits.append(Hit(cat, stream.text[a:b], "rule", words=words))

    for rx in MONEY_RES:
        for m in rx.finditer(full.text):
            add(full, m, "money")
    # Белый список — только внутри найденного блока реквизитов и только если блок похож на абзац,
    # а не на пол-страницы: иначе ошибка в границах блока закрасила бы весь текст.
    if scope and scope[1] - scope[0] < 0.3 * page.image.height:
        para = _owner_paragraph_hit(owner.words)
        if para:
            hits.append(para)
    for m in PASSPORT_RE.finditer(owner.text):
        add(owner, m, "passport")
    for rx in BIRTH_RES:
        for m in rx.finditer(owner.text):
            add(owner, m, "birth")
    for m in ADDRESS_RE.finditer(owner.text):
        if re.search(r"\d", m.group("v") or ""):  # в адресе есть дом или индекс; иначе это текст условий
            add(owner, m, "address", "v")
    for m in PHONE_RE.finditer(owner.text):
        add(owner, m, "phone")
    for m in EMAIL_RE.finditer(owner.text):
        add(owner, m, "email")

    # Таблица реквизитов: подпись строки слева → закрашиваем ячейку значения справа.
    # Только в найденном блоке реквизитов: в других таблицах «регистрация» и «почта» — обычные слова.
    for w in page.words if scope else []:
        if not (y0 <= w.cy < y1):
            continue
        for rx, cat in TABLE_LABELS:
            if rx.search(w.text):
                cell = grid.value_cell_right_of(w.x1, w.y0, w.y1)
                if cell:
                    hits.append(Hit(cat, f"ячейка «{w.text}…»", "table", [cell]))
                break
    return hits


# ---------------------------------------------------------------- LLM

def _norm(t: str) -> str:
    return re.sub(r"[^\w@.+\-]", "", t.lower().replace("ё", "е"))


def locate(page_words: list[Word], fragment: str, min_ratio: float = 0.75) -> list[Word]:
    """Находит в словах страницы участок, наиболее похожий на фрагмент (OCR неидеален)."""
    tokens = [_norm(t) for t in fragment.split()]
    tokens = [t for t in tokens if t]
    if not tokens:
        return []
    norm_words = [_norm(w.text) for w in page_words]
    n = len(tokens)
    best, best_i, best_len = 0.0, -1, n
    first = tokens[0]
    for i in range(len(norm_words)):
        # быстрый фильтр по первому слову
        if difflib.SequenceMatcher(None, norm_words[i], first).ratio() < 0.6 and n > 1:
            continue
        for ln in (n - 1, n, n + 1):
            if ln <= 0 or i + ln > len(norm_words):
                continue
            r = difflib.SequenceMatcher(None, "".join(norm_words[i:i + ln]), "".join(tokens)).ratio()
            if r > best:
                best, best_i, best_len = r, i, ln
    if best < min_ratio:
        return []
    return page_words[best_i:best_i + best_len]


def _llm_hits(page: PageOCR, doc_kind: str) -> list[Hit]:
    lines = [" ".join(w.text for w in ln) for ln in page.lines()]
    items = llm.find_sensitive(lines, doc_kind)
    scope = owner_scope(page)
    owner_words = [w for w in page.words if not scope or scope[0] <= w.cy < scope[1]]
    hits = []
    for it in items:
        cat = it.get("category", "")
        frag = str(it.get("text", "")).strip()
        if cat not in CATEGORY_NAMES or not frag:
            continue
        # Личные данные ищем только в блоке арендодателя, иначе похожий адрес объекта
        # или арендатора может «перетянуть» совпадение на себя.
        scope = page.words if cat == "money" else owner_words
        words = locate(scope, frag)
        if words:
            hits.append(Hit(cat, frag, "llm", words=words))
        else:
            log.warning("LLM-фрагмент категории %s не найден на странице", cat)  # сам текст не пишем: это ПДн
    return hits


# ---------------------------------------------------------------- геометрия

def words_to_rects(words: list[Word], all_words: list[Word]) -> list[tuple]:
    """Прямоугольники по непрерывным участкам выбранных слов в каждой строке.

    Если между выбранными словами есть невыбранное (например, ФИО), участок разрывается —
    иначе плашка закрыла бы и то, что нужно оставить.
    """
    chosen = {id(w) for w in words}
    rects, run = [], []

    def flush():
        if run:
            rects.append((min(w.x0 for w in run), min(w.y0 for w in run),
                          max(w.x1 for w in run), max(w.y1 for w in run)))
            run.clear()

    by_line: dict[tuple, list[Word]] = {}
    for w in all_words:
        by_line.setdefault(w.line, []).append(w)
    for line_words in by_line.values():
        for w in sorted(line_words, key=lambda w: w.x0):
            if id(w) not in chosen:
                flush()
                continue
            # Строки на фото бывают изогнуты: не тянем одну плашку через сильный перепад высоты.
            if run and abs(w.cy - run[-1].cy) > 0.35 * (run[-1].y1 - run[-1].y0):
                flush()
            run.append(w)
        flush()
    return rects


def _pad(r: tuple, words: list[Word]) -> tuple:
    x0, y0, x1, y1 = r
    pad = max(4, (y1 - y0) * 0.2) if not words else max(4, (words[0].y1 - words[0].y0) * 0.2)
    pad = min(pad, 12)
    return (x0 - pad, y0 - pad, x1 + pad, y1 + pad)


def _cell_rect(cell: tuple, words: list[Word]) -> tuple:
    """Ячейка таблицы + все слова, которые в неё заходят (текст скана часто наезжает на линии)."""
    l, t, r, b = cell[0] + 3, cell[1] + 3, cell[2] - 3, cell[3] - 3
    x0, y0, x1, y1 = l, t, r, b
    for w in words:
        ix = min(w.x1, r) - max(w.x0, l)
        iy = min(w.y1, b) - max(w.y0, t)
        if ix > 0 and iy > 0 and ix * iy > 0.3 * (w.x1 - w.x0) * (w.y1 - w.y0):
            px0, py0, px1, py1 = _pad((w.x0, w.y0, w.x1, w.y1), [w])
            x0, y0, x1, y1 = min(x0, px0), min(y0, py0), max(x1, px1), max(y1, py1)
    return (x0, y0, x1, y1)


def _is_label_word(w: Word, grid: Grid) -> bool:
    """Слово в левой узкой колонке таблицы реквизитов («Адрес регистрации:» и т.п.)."""
    cell = grid.cell(w.x0, w.y0, w.x1, w.y1)
    return bool(cell) and cell[0] < 0.2 * grid.w and cell[2] - cell[0] < 0.45 * grid.w


def finalize_rects(hits: list[Hit], grid: Grid, words: list[Word]) -> list[tuple[tuple, str]]:
    """Отступы + расширение до ячейки таблицы, если прямоугольник внутри узкой ячейки."""
    out = []
    for h in hits:
        for rect in h.rects:  # ячейки, найденные по подписи строки
            out.append((_cell_rect(rect, words), h.category))
        value_words = [w for w in h.words if not _is_label_word(w, grid)]
        for rect in words_to_rects(value_words, words):
            cell = grid.cell(*rect)
            if cell:
                out.append((_cell_rect(cell, words), h.category))
            out.append((_pad(rect, []), h.category))
    return out


def detect(page: PageOCR, doc_kind: str, use_llm: bool) -> tuple[list[Hit], list[tuple[tuple, str]], str | None]:
    grid = Grid(page.image)
    hits = _rule_hits(page, grid)
    llm_error = None
    if use_llm:
        try:
            hits += _llm_hits(page, doc_kind)
        except Exception as e:  # LLM — дополнительный слой, правила работают и без него
            log.exception("LLM недоступна")
            llm_error = str(e)
    return hits, finalize_rects(hits, grid, page.words), llm_error
