#!/usr/bin/env bash
# Собирает архив для установки в закрытом контуре.
# Запускать на машине С интернетом, с той же ОС/архитектурой и той же версией Python, что на сервере.
set -euo pipefail
cd "$(dirname "$0")/.."

rm -rf dist && mkdir -p dist/redactor
python3 -m pip download -r requirements.txt -d dist/redactor/wheels
cp -r app tessdata docs requirements.txt .env.example README.md deploy dist/redactor/
tar -czf dist/redactor.tar.gz -C dist redactor
echo "Готово: dist/redactor.tar.gz"
