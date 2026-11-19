from dataclasses import replace

from domain.models import OreBody, ProcessingConfig, SheetData, WorkbookData
from services.importer import suggest


def demo_book() -> WorkbookData:
    headers = ("EAST", "NORTH", "RL", "JOIN", "РУДНОЕ_ТЕЛО", "ВИД_РАБОТ", "PAIR_ID")
    work = [headers]
    contour = [headers]
    for level in (-350, -375):
        contour += [(x, y, level, "ring", "Учебное", None, None)
                    for x, y in [(10, 8), (30, 8), (30, 32), (10, 32), (10, 8)]]
        for key, points, category, pair in (
            ("A", [(1, 11), (9, 11)], "ГПР", "Подход 1"),
            ("B", [(12, 11), (26, 11)], "НР", "Подход 1"),
            ("C", [(0, 18), (40, 18)], None, None),
            ("D", [(12, 23), (23, 23), (26, 30)], "НР", None),
            ("E", [(14, 28), ("нет числа", 28)], None, None),
        ):
            work += [(x, y, level, key, "Учебное", category, pair) for x, y in points]
    return WorkbookData("Учебный пример", (SheetData("Демо выработки", tuple(work)),
                        SheetData("Демо контуры", tuple(contour))), synthetic=True)


def demo_config() -> ProcessingConfig:
    work, contour = demo_book().sheets
    return ProcessingConfig(suggest(work), suggest(contour), (OreBody("Учебное", "U"),),
                            numbering=True, unit="условные единицы")


def benchmark_book(n: int) -> WorkbookData:
    data = demo_book()
    header = data.sheets[0].rows[0]
    rows = tuple((i % 2 + i // 2, i // 100, -350 - (i // 2 % 7) * 25,
                  f"B{i // 2}", "Учебное", "ГПР", None) for i in range(n))
    return replace(data, name=f"Синтетический набор {n}", sheets=(SheetData("Синтетика", (header, *rows)),))

