"""Обращение к внутренней LLM (OpenAI-совместимый API) за списком фрагментов для закрытия."""
import json
import re

from openai import OpenAI

from . import config

SYSTEM = """Ты помогаешь обезличивать скан-копии договоров аренды нежилых помещений перед передачей в муниципальную службу.
Тебе дают распознанный (OCR) текст одной страницы, по строкам. В тексте возможны опечатки распознавания.

Найди ВСЕ фрагменты, которые нужно закрыть:
- money — любые денежные суммы (цифрами и прописью, с рублями/копейками, НДС, арендная плата, платежи, штрафы).
- passport — паспортные данные АРЕНДОДАТЕЛЯ (серия, номер, кем и когда выдан, код подразделения).
- address — адреса АРЕНДОДАТЕЛЯ-собственника: регистрации, проживания, для корреспонденции (только сам адрес, без слов-подписей вроде «зарегистрирована по адресу:»).
- birth — дата рождения и место рождения АРЕНДОДАТЕЛЯ.
- phone — телефоны АРЕНДОДАТЕЛЯ.
- email — электронная почта АРЕНДОДАТЕЛЯ.

НЕ закрывай: ФИО, ИНН, ОГРН/ОГРНИП, банковские реквизиты, номер и дату договора, адрес и площадь арендуемого помещения/объекта/здания, кадастровые номера, любые данные АРЕНДАТОРА (название, его адрес, представитель, доверенность), площади в кв. м, мощности, объёмы.

Ответ — только JSON без пояснений:
{"items": [{"category": "<money|passport|address|birth|phone|email>", "text": "<фрагмент дословно, как в тексте>"}]}
Фрагмент копируй символ в символ из текста (включая опечатки OCR), он может занимать несколько строк — тогда соедини строки через пробел.
Если ничего нет — {"items": []}."""


def _client() -> OpenAI:
    return OpenAI(base_url=config.LLM_BASE_URL, api_key=config.LLM_API_KEY,
                  timeout=config.LLM_TIMEOUT, max_retries=1)


def find_sensitive(lines: list[str], doc_kind: str) -> list[dict]:
    body = "\n".join(f"[{i + 1}] {ln}" for i, ln in enumerate(lines))
    kind = "акт приёма-передачи" if doc_kind == "act" else "договор аренды"
    resp = _client().chat.completions.create(
        model=config.LLM_MODEL,
        temperature=0,
        messages=[
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": f"Документ: {kind}.\nТекст страницы:\n{body}"},
        ],
    )
    return parse(resp.choices[0].message.content or "")


def parse(content: str) -> list[dict]:
    content = re.sub(r"<think>[\s\S]*?</think>", "", content)  # reasoning-модели
    m = re.search(r"\{[\s\S]*\}", content)
    if not m:
        return []
    data = json.loads(m.group(0))
    items = data.get("items", []) if isinstance(data, dict) else []
    return [i for i in items if isinstance(i, dict)]
