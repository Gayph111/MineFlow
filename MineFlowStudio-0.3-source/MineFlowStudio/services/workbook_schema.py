"""Versioned contract between the XLSX exporters and independent readers."""

import json

EXPORT_TAG = "MineFlow Studio • export v2"
EXPORT_TAGS = {EXPORT_TAG, "MineFlow Studio • export v1"}
SUMMARY_HEADERS = (
    "ID", "Группа Excel", "Горизонт", "Рудное тело", "Категория Excel",
    "Категория обработки", "Положение", "Длина расчётная", "ДЛИНА из Excel",
    "ID пары", "Связанные ID", "Пробный номер", "Пробная маркировка", "Стартовый EAST",
    "Стартовый NORTH", "Лист", "Первая строка", "Точек", "Копия контура",
    "Длина начало–конец", "CODE Excel", "Пробное имя на кириллице", "Статус обозначения",
    "STRING и TUN_NAME из примера", "Имя на кириллице из примера", "ВИД_РАБОТ из примера", "Источник примера",
)
ROW_HEADERS = ("ID объекта", "Исходный лист", "Строка Excel")
CONTOUR_HEADERS = ("Группа", "Горизонт", "Рудное тело", "Полигон валиден", "Лист", "Строка Excel")
ISSUE_HEADERS = ("Уровень", "Код", "Сообщение", "Исходный лист", "Строка Excel")



DELIVERY_PROPERTY = "MineFlowWorkingData"
SHEET_ROLES = {
    "axes": "Оси",
    "segments": "Участки",
    "points": "Точки участков",
    "links": "Связи участков",
}
HEADINGS = {
    "axes": ("ID оси", "JOIN", "Горизонт", "Рудное тело", "Лист Excel", "Первая строка", "Последняя строка",
             "Исходных точек", "Длина оси", "Роль", "STRING / TUN_NAME из образца", "Имя из образца",
             "ВИД_РАБОТ из образца", "Источник образца"),
    "segments": ("ID участка", "ID оси", "JOIN", "Порядок", "Горизонт", "Рудное тело",
                 "Категория", "ВИД_РАБОТ", "Длина", "Длина начало–конец", "Основание категории",
                 "EAST начала", "NORTH начала", "RL начала", "EAST конца", "NORTH конца", "RL конца",
                 "Номер по настройкам", "Обозначение по настройкам", "Имя по настройкам", "Статус"),
    "points": ("ID участка", "Фрагмент", "Порядок точки", "EAST", "NORTH", "RL", "Происхождение", "Строки Excel"),
    "links": ("Участок Порода", "Участок Руда", "Горизонт", "Рудное тело", "Основание", "Статус"),
}

CATEGORY = {"P": "Порода", "R": "Руда"}
WORK_KIND = {"P": "ГПР", "R": "НР"}


def manifest(book):
    if DELIVERY_PROPERTY not in book.custom_doc_props.names:
        return {}
    try:
        value = json.loads(book.custom_doc_props[DELIVERY_PROPERTY].value)
        names = value["sheets"]
        if (value["version"] != 1 or set(names) != set(SHEET_ROLES)
                or not all(isinstance(title, str) and title in book.sheetnames for title in names.values())
                or len(set(names.values())) != len(SHEET_ROLES)):
            return {}
        return value
    except (ValueError, TypeError, KeyError, AttributeError):
        return {}


