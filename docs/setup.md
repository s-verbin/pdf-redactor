# Запуск на новом компьютере (VS Code)

Инструкция для разработки и проверки на рабочем компьютере: Windows, macOS или Linux.
Установка на сервер как службы описана в [руководстве администратора](admin-guide.md).

## 1. Что переносить

| Переносить | Не переносить |
|---|---|
| `app/`, `docs/`, `deploy/`, `.vscode/` | `.venv/` — привязана к ОС и путям, создаётся заново |
| `requirements.txt`, `.env.example`, `.gitignore`, `README.md` | `data/`, `debug/` — задачи и отладочные файлы **с персональными данными из документов** |
| `tessdata/` — необязательно, модели можно скачать (шаг 3) | `__pycache__/`, `.DS_Store`, `.claude/`, `.env` |

Без `tessdata/` проект весит меньше 1 МБ.

> **Windows:** положите проект в папку с путём **только из латинских букв**, например
> `C:\redactor`. Tesseract на Windows часто не может загрузить модели из путей с кириллицей
> (`...\пдф_очистка\...`).

## 2. Установить программы

**Python 3.11 или новее** (проверено на 3.14):
- Windows: установщик с python.org, при установке отметьте **Add python.exe to PATH**;
- macOS: `brew install python`;
- Linux: `apt install python3 python3-venv`.

**Tesseract OCR 4 или новее:**
- Windows: установщик UB Mannheim (github.com/UB-Mannheim/tesseract/wiki). Путь по умолчанию —
  `C:\Program Files\Tesseract-OCR`. В PATH он не добавляется, поэтому путь нужно указать в `.env`
  (шаг 5);
- macOS: `brew install tesseract`;
- Linux: `apt install tesseract-ocr` (Ubuntu/Astra), `dnf install tesseract` (РЕД ОС).

**VS Code** с расширением **Python** (Microsoft). При открытии проекта VS Code сам предложит
рекомендованные расширения.

## 3. Языковые модели OCR

Нужны две модели: **`rus.traineddata`** (19 МБ) и **`eng.traineddata`** (23 МБ). Других не
нужно. Есть три способа, выберите любой.

**А. Перенести папку `tessdata/`** из исходного проекта.

**Б. Скачать в папку `tessdata/` проекта** (нужен доступ к github.com). Это те же файлы,
на которых сервис проверялся.

Windows (PowerShell, из папки проекта):
```powershell
mkdir tessdata
Invoke-WebRequest https://github.com/tesseract-ocr/tessdata/raw/main/rus.traineddata -OutFile tessdata\rus.traineddata
Invoke-WebRequest https://github.com/tesseract-ocr/tessdata/raw/main/eng.traineddata -OutFile tessdata\eng.traineddata
```

macOS / Linux:
```bash
mkdir -p tessdata
curl -L -o tessdata/rus.traineddata https://github.com/tesseract-ocr/tessdata/raw/main/rus.traineddata
curl -L -o tessdata/eng.traineddata https://github.com/tesseract-ocr/tessdata/raw/main/eng.traineddata
```

**В. Поставить русский язык вместе с Tesseract**, а папку `tessdata/` не создавать:
- Windows: в установщике UB Mannheim раскройте *Additional language data* и отметьте *Russian*;
- Linux: `apt install tesseract-ocr-rus` / `dnf install tesseract-langpack-rus`;
- macOS: `brew install tesseract-lang` (все языки, около 650 МБ).

Если в `tessdata/` проекта есть хотя бы одна модель, сервис берёт модели только оттуда.
Если папки нет или она пуста — использует модели, установленные с Tesseract.

Модели из дистрибутивов Linux и установщика Windows могут отличаться версией от тех, на которых
сервис проверялся (вариант Б), и распознавать немного иначе.

## 4. Открыть проект и создать окружение

1. VS Code → **File → Open Folder** → папка проекта.
2. Откройте терминал: **Terminal → New Terminal**.
3. Создайте окружение и поставьте пакеты:

Windows (PowerShell):
```powershell
py -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

macOS / Linux:
```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

4. Выберите интерпретатор: **Ctrl+Shift+P** (на Mac — Cmd+Shift+P) → *Python: Select
   Interpreter* → вариант с `.venv`. После этого новые терминалы VS Code будут открываться
   с активированным окружением, и F5 будет запускать код в нём.

Если PowerShell пишет, что выполнение скриптов запрещено, это касается только автоматической
активации окружения. Команды вида `.venv\Scripts\python ...` работают и без неё.

**Без интернета** пакеты ставятся из заранее скачанных wheel-файлов. На машине с интернетом,
с той же ОС и той же версией Python:
```bash
python -m pip download -r requirements.txt -d wheels
```
Перенесите папку `wheels` и установите пакеты из неё:
```bash
python -m pip install --no-index --find-links wheels -r requirements.txt
```

## 5. Настройки (необязательно)

Всё работает без `.env`. Если нужно что-то поменять, скопируйте `.env.example` в `.env`.
На Windows, если Tesseract не в PATH, добавьте в `.env`:

```
TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe
```

LLM по умолчанию выключена, и включать её не нужно.

## 6. Проверить окружение

В VS Code: **Run and Debug** (Ctrl+Shift+D) → *Проверка окружения* → F5. Или в терминале VS Code
(после шага 4 окружение `.venv` в нём уже активно; иначе вместо `python` пишите
`.venv\Scripts\python` на Windows или `.venv/bin/python` на macOS/Linux):

```bash
python -m app.check
```

Должно получиться примерно так:
```
✅ Версия Python подходит
✅ Python-пакеты установлены
✅ Tesseract 5.5.2
✅ Языки OCR: rus+eng (из ...\tessdata)
✅ Каталог задач доступен для записи: ...\data
✅ LLM выключена — работают только правила

Всё готово, можно запускать.
```

Если какой-то пункт отмечен ❌, под ним написано, что сделать.

## 7. Запустить

**Веб-сервис:** Run and Debug → *Сервис (http://localhost:8088)* → F5. Откройте в браузере
http://localhost:8088. Остановка — Shift+F5. В этом режиме работают точки останова.

То же в терминале:
```bash
python -m uvicorn app.main:app --port 8088
```

Для разработки с автоматическим перезапуском при изменении кода добавьте `--reload`.

**Один файл без веб-интерфейса:** Run and Debug → *Обработать PDF без веб-интерфейса* → F5 →
введите путь к PDF. Результат `<имя>_обезличено.pdf` появится рядом с исходным файлом, а
закрашенные страницы в PNG — в папке `debug/`. Из терминала:

```bash
python -m app.cli "C:\docs\договор.pdf" --debug debug
python -m app.cli договор.pdf --keep suggested     # только стр. 1 и страница с подписями
```

## 8. Собрать программу для Windows (exe)

Из проекта можно собрать папку `PDFRedactor` с `PDFRedactor.exe`, которая работает на другом
Windows-компьютере без Python, Tesseract и прав администратора.

**Что нужно на машине сборки:** шаги 2–3 этой инструкции (Python 3.11+, Tesseract, модели
`rus.traineddata` и `eng.traineddata` в `tessdata/`) и путь к проекту латиницей.

**Сборка:** двойной клик по `build_windows.bat` в корне проекта. Скрипт:

1. проверит файлы проекта и модели;
2. найдёт Python, создаст `.venv` и поставит пакеты и PyInstaller;
3. найдёт Tesseract — в `TESSERACT_CMD` из `.env`, в профиле пользователя, в Program Files или
   через `where`;
4. соберёт программу (`launcher.py` — точка входа: запускает сервис на свободном порту
   `127.0.0.1` и открывает браузер);
5. скопирует Tesseract в `dist\PDFRedactor\tesseract` и упакует всё в `dist\PDFRedactor.zip`.

Первый запуск — 5–10 минут (установка пакетов), повторные — 1–3 минуты. Если Tesseract не нашёлся
сам, укажите его папку и запустите скрипт из той же консоли:

```
set TESSERACT_DIR=C:\путь\к\Tesseract-OCR
build_windows.bat
```

**На другом компьютере:** распаковать `PDFRedactor.zip` в папку с путём латиницей (например,
`C:\PDFRedactor`) и запустить `PDFRedactor.exe`. Окно консоли показывает адрес; закрыли окно —
программа остановилась. Задачи хранятся в `%LOCALAPPDATA%\pdf-redactor`.

**Подпись и защита Windows.** Exe не подписан. При запуске скачанного файла SmartScreen может
показать «Windows защитила ваш компьютер» → «Подробнее» → «Выполнить в любом случае»; архив,
перенесённый на флешке или через сетевую папку, обычно запускается без предупреждения.
Корпоративный антивирус может с подозрением отнестись к неподписанной сборке PyInstaller —
тогда нужен сертификат подписи кода или исключение от IT. Подписать: `signtool sign /fd SHA256
/tr http://timestamp.digicert.com /td SHA256 /sha1 <отпечаток> dist\PDFRedactor\PDFRedactor.exe`.

Запустить программу без сборки, прямо из исходников (удобно для проверки перед сборкой):
`.venv\Scripts\python launcher.py`.

## Частые проблемы

| Симптом | Решение |
|---|---|
| `python` / `py` не найден | Переустановите Python с галочкой *Add to PATH* и перезапустите VS Code |
| `No module named ...` | Не выбран интерпретатор `.venv` (шаг 4) или не установлены пакеты |
| `Tesseract не найден` | Установите Tesseract; на Windows укажите `TESSERACT_CMD` в `.env` |
| `Tesseract не видит языки: rus` | Нет `rus.traineddata` (шаг 3). На Windows проверьте, что в пути к проекту нет кириллицы |
| `Address already in use` / порт 8088 занят | Запустите на другом порту: `--port 8090` |
| Страница в браузере не открывается | Сервис слушает только этот компьютер. Для доступа с других компьютеров добавьте `--host 0.0.0.0` (и учтите, что авторизации нет) |
| Договор обрабатывается очень долго | Норма — около 3,5 минуты на 33 страницы. На слабых ноутбуках дольше |

После работы с реальными документами удаляйте папки `data/` и `debug/`: в них остаются страницы
с персональными данными.
