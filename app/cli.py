"""Обработка из командной строки (для проверки и пакетной работы).

    python -m app.cli входной.pdf [-o выход.pdf] [--kind auto|contract|act] [--keep all|suggested|1,15]
                      [--no-llm] [--debug папка]
"""
import argparse
import json
import logging
import time
from dataclasses import asdict
from pathlib import Path

from .pipeline import process


def main():
    ap = argparse.ArgumentParser(description="Обезличивание сканов договоров аренды")
    ap.add_argument("input")
    ap.add_argument("-o", "--output")
    ap.add_argument("--kind", default="auto", choices=["auto", "contract", "act"])
    ap.add_argument("--keep", default="all",
                    help="какие страницы оставить: all, suggested (стр. 1 и с подписями) или номера через запятую")
    ap.add_argument("--no-llm", action="store_true")
    ap.add_argument("--debug", help="папка для PNG закрашенных страниц")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    src = Path(a.input)
    dst = Path(a.output) if a.output else src.with_name(src.stem + "_обезличено.pdf")
    if a.debug:
        Path(a.debug).mkdir(parents=True, exist_ok=True)
    t = time.time()
    data, report = process(src.read_bytes(), a.kind, use_llm=False if a.no_llm else None,
                           progress=lambda s: print("…", s), debug_dir=a.debug, keep=a.keep)
    dst.write_bytes(data)
    print(json.dumps(asdict(report), ensure_ascii=False, indent=1))
    print(f"Готово за {time.time() - t:.0f} c → {dst}")


if __name__ == "__main__":
    main()
