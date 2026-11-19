import os
from pathlib import Path
import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from app.ui.main_window import MainWindow
from app.ui.style import STYLES
from services.project_files import PROJECT_SUFFIX


def main() -> int:
    os.environ["QT_API"] = "pyside6"
    app = QApplication(sys.argv)
    app.setApplicationName("MineFlow Studio")
    app.setApplicationVersion("0.5")
    app.setStyle("Fusion")
    app.setStyleSheet(STYLES)
    window = MainWindow()
    window.show()
    if len(sys.argv) > 1:
        path = Path(sys.argv[1])
        command = window.open_project if path.name.lower().endswith(PROJECT_SUFFIX) else window.open_file
        QTimer.singleShot(0, lambda: command(path))
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())

