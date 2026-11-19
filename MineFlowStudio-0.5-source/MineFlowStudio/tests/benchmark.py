from dataclasses import replace
from pathlib import Path
from statistics import median
from time import perf_counter
import os
import sys

from domain.models import ProcessingConfig
from fixtures.demo import benchmark_book
from services.importer import read_workbook, suggest
from services.processing import process


def measure(label, source, config):
    samples = [process(source, config) for _ in range(7)]
    result = samples[0]
    count = sum(len(e.refs) for e in result.excavations) + sum(len(c.refs) for c in result.contours)
    print(f"{label.ljust(17)} {count:5} строк, {len(result.excavations):4} групп, "
          f"медиана {1000 * median(r.elapsed for r in samples):6.1f} мс")


if len(sys.argv) > 1:
    then = perf_counter()
    source = read_workbook(Path(sys.argv[1]), os.environ.get("MINEFLOW_INPUT_KEY"))
    print(f"Расшифровка и чтение: {(perf_counter() - then) * 1000:.1f} мс")
    config = ProcessingConfig(*(suggest(sheet) for sheet in source.sheets[:2]))
    measure("Книга заказчика", source, replace(config, classification="geometry", numbering=True))

for count in (402, 1000, 10000):
    source = benchmark_book(count)
    measure("Синтетический", source, ProcessingConfig(suggest(source.sheets[0]), numbering=True))

