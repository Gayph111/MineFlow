BG = "#10151C"
SURFACE = "#1B2430"
ELEVATED = "#253444"
BORDER = "#344454"
PRIMARY = "#4DA8FF"
ORE = "#FF9F43"
SUCCESS = "#38C9A0"
ERROR = "#FF6675"
TEXT = "#EAF0F6"
MUTED = "#A7B5C5"

STYLES = f"""
QWidget {{
  background: {BG};
  color: {TEXT};
  font-family: 'Segoe UI';
  font-size: 13px;
}}
QLabel {{ background: transparent; }}
#sidebar, #header, #status, #chartBar {{ background: #141C25; }}
#panel, #stat {{
  background: {SURFACE};
  border: 1px solid {BORDER};
  border-radius: 10px;
}}
#panel QWidget[plain="true"], QScrollArea, QScrollArea > QWidget > QWidget {{
  background: transparent;
}}
#brand {{ font-weight: 700; font-size: 19px; }}
#brandIcon {{
  background: #1C3D59;
  color: #80C5FF;
  border-radius: 10px;
  font-weight: 750;
  font-size: 16px;
}}
#title {{ font-weight: 700; font-size: 25px; }}
#section {{ font-size: 16px; font-weight: 650; }}
#statValue {{ font-size: 25px; font-weight: 700; }}
#muted {{ color: {MUTED}; }}
#accent {{ color: {PRIMARY}; font-weight: 600; }}
#warning {{ color: {ORE}; }}
#success {{ color: {SUCCESS}; }}
#badge {{
  background: #203448;
  color: #9DD5FF;
  border-radius: 8px;
  padding: 6px 10px;
}}
QPushButton {{
  background: {ELEVATED};
  border: 1px solid {BORDER};
  border-radius: 8px;
  padding: 7px 13px;
  font-weight: 600;
  min-height: 19px;
}}
QPushButton:hover {{ background: #31465B; border-color: #52708D; }}
QPushButton:pressed {{ background: #203246; }}
QPushButton:focus, QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
  border: 1px solid {PRIMARY};
}}
QPushButton:disabled {{ color: #8091A3; background: #202A36; }}
QPushButton[primary="true"] {{
  color: #101C28;
  background: {PRIMARY};
  border-color: {PRIMARY};
}}
QPushButton[primary="true"]:hover {{ background: #78BCFF; }}
QPushButton[primary="true"]:disabled {{ background: #26394B; color: #9AACBD; border-color: #31485E; }}
QPushButton[nav="true"] {{
  text-align: left;
  padding: 10px 14px;
  color: {MUTED};
  background: transparent;
  border: 1px solid transparent;
}}
QPushButton[nav="true"]:checked {{ color: #A6D6FF; background: #23384C; border-color: #36516B; }}
QPushButton[nav="true"]:hover {{ background: #1E2D3D; }}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit {{
  background: #141E29;
  border: 1px solid {BORDER};
  border-radius: 7px;
  padding: 5px 8px;
  min-height: 22px;
  selection-background-color: #25537B;
}}
QComboBox QAbstractItemView {{
  background: {SURFACE};
  selection-background-color: #2C506D;
  outline: none;
  padding: 3px;
}}
QCheckBox {{ background: transparent; spacing: 7px; }}
QGroupBox {{
  background: {SURFACE};
  border: 1px solid {BORDER};
  border-radius: 10px;
  margin-top: 12px;
  padding: 16px 10px 8px;
  font-weight: 650;
}}
QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 6px; }}
QTableView {{
  background: #141D27;
  alternate-background-color: {SURFACE};
  border: 1px solid {BORDER};
  border-radius: 7px;
  gridline-color: #263746;
  selection-background-color: #255479;
  selection-color: {TEXT};
}}
QHeaderView::section {{
  background: {ELEVATED};
  color: {TEXT};
  border: none;
  border-right: 1px solid {BORDER};
  padding: 6px 9px;
}}
QScrollBar:vertical {{ background: #16212B; width: 10px; }}
QScrollBar:horizontal {{ background: #16212B; height: 10px; }}
QScrollBar::handle {{ background: #486079; border-radius: 4px; min-height: 20px; min-width: 20px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0px; width: 0px; }}
QProgressBar {{
  border: 1px solid {BORDER};
  background: #101923;
  border-radius: 4px;
  text-align: center;
}}
QProgressBar::chunk {{ background: #2D729F; border-radius: 4px; }}
QToolTip {{ background: {ELEVATED}; color: {TEXT}; border: 1px solid {BORDER}; }}
"""

