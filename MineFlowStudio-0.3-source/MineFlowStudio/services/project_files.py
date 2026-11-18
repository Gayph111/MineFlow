"""Portable project settings and a link to the source workbook."""

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from domain.models import ProcessingConfig
from services.importer import config_from_dict

PROJECT_SUFFIX = ".mineflow.json"


@dataclass(frozen=True)
class ProjectFile:
    path: Path
    source: Path
    config: ProcessingConfig


def read_project(path: Path) -> ProjectFile:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("format") != "MineFlow Studio" or value.get("version") != 1:
        raise ValueError("Формат файла проекта не поддерживается.")
    try:
        source = Path(value["source"])
        if not source.is_absolute():
            source = path.parent / source
        config = config_from_dict(value["settings"])
    except (KeyError, TypeError, ValueError, AttributeError) as error:
        raise ValueError("В файле проекта повреждены путь или параметры.") from error
    return ProjectFile(path.resolve(), source.resolve(), config)


def write_project(project: ProjectFile) -> None:
    path, source = project.path.resolve(), project.source.resolve()
    if path == source:
        raise ValueError("Выберите имя проекта отдельно от исходной книги.")
    try:
        source_name = str(source.relative_to(path.parent))
    except ValueError:
        source_name = str(source)
    value = {"format": "MineFlow Studio", "version": 1, "source": source_name,
             "settings": asdict(project.config)}
    temporary = None
    try:
        with NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                suffix=".tmp", delete=False) as file:
            temporary = Path(file.name)
            json.dump(value, file, ensure_ascii=False, indent=2)
            file.write("\n")
        os.replace(temporary, path)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)

