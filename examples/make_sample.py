"""Генерирует вымышленный «скан» договора аренды для демонстрации и проверки сервиса.

    python examples/make_sample.py [путь_к_шрифту.ttf]

Все имена, номера и адреса выдуманы. Результат — examples/sample_contract.pdf:
3 страницы без текстового слоя, с лёгким наклоном и шумом, как у настоящего скана.
"""
import io
import random
import sys
from pathlib import Path

import numpy as np
import pymupdf
from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1654, 2339          # A4 при 200 dpi
LEFT, RIGHT = 150, W - 150
FONTS = [
    "/System/Library/Fonts/Supplemental/Times New Roman.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
    "C:/Windows/Fonts/times.ttf",
]


def font_path() -> str:
    if len(sys.argv) > 1:
        return sys.argv[1]
    for f in FONTS:
        if Path(f).exists():
            return f
    sys.exit("Укажите путь к TTF-шрифту с кириллицей: python examples/make_sample.py шрифт.ttf")


FP = font_path()
BOLD = FP.replace(".ttf", " Bold.ttf") if Path(FP.replace(".ttf", " Bold.ttf")).exists() else FP
F = ImageFont.truetype(FP, 34)
FB = ImageFont.truetype(BOLD, 34)
FT = ImageFont.truetype(BOLD, 42)


class Page:
    def __init__(self):
        self.img = Image.new("L", (W, H), 255)
        self.d = ImageDraw.Draw(self.img)
        self.y = 140

    def title(self, text):
        w = self.d.textlength(text, font=FT)
        self.d.text(((W - w) / 2, self.y), text, font=FT, fill=0)
        self.y += 70

    def para(self, text, bold_prefix="", gap=18, left=LEFT):
        """Абзац с переносом по ширине; bold_prefix — жирное начало."""
        words = ([(w, FB) for w in bold_prefix.split()] if bold_prefix else []) + [(w, F) for w in text.split()]
        line, width = [], 0
        space = self.d.textlength(" ", font=F)
        for word, font in words:
            ww = self.d.textlength(word, font=font)
            if line and width + space + ww > RIGHT - left:
                self._line(line, left)
                line, width = [], 0
            line.append((word, font))
            width += (space if len(line) > 1 else 0) + ww
        if line:
            self._line(line, left)
        self.y += gap

    def _line(self, line, left):
        x = left
        for word, font in line:
            self.d.text((x, self.y), word, font=font, fill=0)
            x += self.d.textlength(word + " ", font=font)
        self.y += 46

    def hline(self, y=None):
        y = self.y if y is None else y
        self.d.line([(LEFT - 20, y), (RIGHT + 20, y)], fill=0, width=3)

    def scanned(self, seed) -> Image.Image:
        random.seed(seed)
        img = self.img.rotate(random.uniform(-0.8, 0.8), resample=Image.BICUBIC, fillcolor=255)
        arr = np.asarray(img).astype(np.int16)
        arr += np.random.default_rng(seed).normal(0, 6, arr.shape).astype(np.int16)
        img = Image.fromarray(arr.clip(0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(0.6))
        return img.convert("RGB")


def page1() -> Page:
    p = Page()
    p.title("ДОГОВОР № 0451")
    p.title("аренды нежилого помещения")
    p.d.text((LEFT, p.y), "г. Энск", font=FB, fill=0)
    p.d.text((RIGHT - 330, p.y), "«15» марта 2026 года", font=FB, fill=0)
    p.y += 80
    p.hline(); p.y += 15
    p.para("", bold_prefix="«АРЕНДОДАТЕЛЬ»:", gap=0)
    p.hline(); p.y += 15
    p.para("Петров Пётр Петрович, 5 марта 1980 года рождения, ОГРНИП 312770000000001, "
           "ИНН 770000000001, паспорт: серия 45 00 № 123456, выдан 1 апреля 2010 года ОВД района "
           "Северный города Энска, код подразделения: 770-001, зарегистрирован по адресу: "
           "г. Энск, ул. Вымышленная, д. 7, кв. 12, с одной стороны, и",
           bold_prefix="Индивидуальный предприниматель")
    p.hline(); p.y += 15
    p.para("", bold_prefix="«АРЕНДАТОР»:", gap=0)
    p.hline(); p.y += 15
    p.para("(ОГРН 1027700000000, ИНН 7700000000, адрес местонахождения: 100000, г. Энск, "
           "ул. Торговая, д. 1), в лице представителя Сидорова Сидора Сидоровича, действующего "
           "на основании доверенности от 10 января 2026 года, с другой стороны,",
           bold_prefix="Общество с ограниченной ответственностью «Ромашка»")
    p.hline(); p.y += 15
    p.para("также далее именуемые совместно «Стороны», заключили настоящий договор о нижеследующем:")
    p.hline(); p.y += 30
    p.title("1. Предмет Договора")
    p.para("1.1. Арендодатель обязуется передать, а Арендатор принять за плату во временное "
           "владение и пользование нежилое помещение площадью 120,5 (сто двадцать целых пять "
           "десятых) кв. м, этаж 1, расположенное по адресу: г. Энск, пр. Центральный, д. 25.")
    p.para("1.2. Целевое назначение Помещения: розничная торговля продовольственными товарами.")
    return p


def page2() -> Page:
    p = Page()
    p.title("2. Платежи и расчёты")
    p.para("2.1. В первый месяц срока аренды ежемесячная арендная плата составляет "
           "1000 (одна тысяча) рублей.")
    p.para("2.2. Начиная со второго месяца ежемесячная арендная плата составляет "
           "185 000 (сто восемьдесят пять тысяч) рублей 00 копеек, НДС не облагается.")
    p.para("2.3. Обеспечительный платёж составляет 370 000 (триста семьдесят тысяч) рублей и "
           "вносится в течение 10 (десяти) рабочих дней с даты подписания Договора.")
    p.para("2.4. Справки и уведомления направляются по адресу электронной почты Арендодателя: "
           "petrov.demo@example.com, телефон для связи: +7 900 000-00-00.")
    p.y += 30
    p.title("Смета на ремонтные работы")
    rows = [("Демонтаж и вывоз мусора", "84 250,00"), ("Устройство полов", "312 480,50"),
            ("Внутренняя отделка", "1 205 300,00"), ("Электроснабжение", "268 915,75"),
            ("ИТОГО", "1 870 946,25")]
    x0, x1, x2 = LEFT, LEFT + 900, RIGHT
    top = p.y
    p.d.rectangle([x0, top, x2, top + 60 * len(rows)], outline=0, width=3)
    p.d.line([(x1, top), (x1, top + 60 * len(rows))], fill=0, width=3)
    for i, (name, sum_) in enumerate(rows):
        y = top + 60 * i
        if i:
            p.d.line([(x0, y), (x2, y)], fill=0, width=2)
        p.d.text((x0 + 15, y + 10), name, font=FB if name == "ИТОГО" else F, fill=0)
        p.d.text((x2 - 15 - p.d.textlength(sum_, font=F), y + 10), sum_, font=F, fill=0)
    p.y = top + 60 * len(rows) + 40
    p.para("Стоимость работ указана в рублях.")
    return p


def page3() -> Page:
    p = Page()
    p.title("10. Адреса и реквизиты Сторон")
    rows = [("АРЕНДОДАТЕЛЬ:", ""),
            ("ФИО:", "Индивидуальный предприниматель Петров Пётр Петрович"),
            ("Данные паспорта:", "паспорт: серия 45 00 № 123456, выдан 1 апреля 2010 года ОВД района Северный города Энска, код подразделения: 770-001"),
            ("Дата и место рождения:", "5 марта 1980 года рождения, г. Энск"),
            ("Адрес регистрации:", "г. Энск, ул. Вымышленная, д. 7, кв. 12"),
            ("ОГРНИП:", "312770000000001"),
            ("ИНН:", "770000000001"),
            ("АРЕНДАТОР:", ""),
            ("Наименование:", "ООО «Ромашка»"),
            ("Местонахождение:", "100000, г. Энск, ул. Торговая, д. 1")]
    x0, x1, x2 = LEFT - 20, LEFT + 520, RIGHT + 20
    y = p.y
    p.d.line([(x0, y), (x2, y)], fill=0, width=3)
    for label, value in rows:
        start = y
        p.y = y + 8
        if value:
            p.para(value, gap=0, left=x1 + 15)
        else:
            p.y += 46
        y_end = max(p.y + 8, y + 62)
        p.d.text((x0 + 15, y + 8), label, font=FB, fill=0)
        p.d.line([(x0, y_end), (x2, y_end)], fill=0, width=3)
        if value:
            p.d.line([(x1, start), (x1, y_end)], fill=0, width=3)
        p.d.line([(x0, start), (x0, y_end)], fill=0, width=3)
        p.d.line([(x2, start), (x2, y_end)], fill=0, width=3)
        y = y_end
    p.y = y + 60
    p.title("Подписи Сторон:")
    p.d.text((LEFT, p.y), "АРЕНДОДАТЕЛЬ: ______________ /П. П. Петров", font=F, fill=0)
    p.d.text((LEFT, p.y + 90), "АРЕНДАТОР: ______________ /С. С. Сидоров", font=F, fill=0)
    p.d.ellipse([LEFT + 600, p.y - 40, LEFT + 820, p.y + 180], outline=110, width=4)
    return p


def main():
    out = Path(__file__).with_name("sample_contract.pdf")
    doc = pymupdf.open()
    for n, page in enumerate((page1(), page2(), page3()), 1):
        img = page.scanned(n)
        pdf_page = doc.new_page(width=595.3, height=841.9)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        pdf_page.insert_image(pdf_page.rect, stream=buf.getvalue())
    doc.save(out, garbage=4, deflate=True)
    print(f"Готово: {out}")


if __name__ == "__main__":
    main()
