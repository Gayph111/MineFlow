from pathlib import Path

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

ASSETS = Path(__file__).with_name("assets")
CHECKMARK = (ASSETS / "checkmark.svg").as_posix()
PARTIAL_CHECK = (ASSETS / "partial-check.svg").as_posix()

STYLES = f"""
QWidget {{
  background: {BG};
  color: {TEXT};
  font-family: 'Segoe UI';
  font-size: 13px;
}}
QLabel {{ background: transparent; }}
#sidebar {{
  background: #141D27;
  border-right: 1px solid #293949;
}}
#header {{
  background: #151F2A;
  border-bottom: 1px solid #2A3A4C;
}}
#status {{ background: #141C25; border-top: 1px solid #283747; }}
#chartBar {{ background: #1B2937; }}
#panel, #stat {{
  background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #1E2A38, stop:1 #1A242F);
  border: 1px solid #35485B;
  border-radius: 10px;
}}
#panel QWidget[plain="true"], QScrollArea, QScrollArea > QWidget > QWidget {{
  background: transparent;
}}
#brand {{ font-weight: 700; font-size: 19px; }}
#brandIcon {{
  background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #294F70, stop:1 #1A344D);
  color: #B9DEFF;
  border: 1px solid #426380;
  border-radius: 10px;
  font-weight: 750;
  font-size: 16px;
}}
#title {{ font-weight: 650; font-size: 25px; }}
#section {{ font-size: 16px; font-weight: 650; }}
#statValue {{ font-size: 27px; font-weight: 650; color: #F2F7FD; }}
#muted {{ color: {MUTED}; }}
#accent {{ color: {PRIMARY}; font-weight: 600; }}
#warning {{ color: {ORE}; }}
#success {{ color: {SUCCESS}; }}
#badge {{
  background: #203448;
  color: #9DD5FF;
  border: 1px solid #324E68;
  border-radius: 8px;
  padding: 6px 10px;
}}
QPushButton {{
  background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #2A3C4E, stop:1 #233343);
  border: 1px solid #41586E;
  border-radius: 8px;
  padding: 7px 13px;
  font-weight: 600;
  min-height: 19px;
}}
QPushButton:hover {{ background: #334C64; border-color: #6987A5; }}
QPushButton:pressed {{ background: #203246; }}
QPushButton:checked {{ background: #244663; color: #C8E7FF; border-color: #579DCE; }}
QPushButton:focus, QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
  border: 1px solid {PRIMARY};
}}
QPushButton:disabled {{ color: #8091A3; background: #202A36; }}
QPushButton[primary="true"] {{
  color: #081B2C;
  background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #6AB8FF, stop:1 #439DF1);
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
QPushButton[nav="true"]:checked {{ color: #D4EBFF; background: #243C52; border-color: #426483; }}
QPushButton[nav="true"]:hover {{ background: #1E2D3D; }}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit {{
  background: #121D29;
  border: 1px solid #43596F;
  border-radius: 7px;
  padding: 5px 8px;
  min-height: 22px;
  selection-background-color: #25537B;
}}
QLineEdit:hover, QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover {{
  border-color: #668099;
}}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {{
  background: #18212B;
  color: #8091A3;
  border-color: #304151;
}}
QComboBox QAbstractItemView {{
  background: {SURFACE};
  selection-background-color: #2C506D;
  outline: none;
  padding: 3px;
}}
QCheckBox {{ background: transparent; spacing: 9px; min-height: 24px; }}
QCheckBox::indicator, QAbstractItemView::indicator {{
  width: 18px;
  height: 18px;
  border: 1px solid #8BA3BA;
  border-radius: 5px;
  background: #111D29;
}}
QCheckBox::indicator:hover, QAbstractItemView::indicator:hover {{
  border-color: #9CD1FF;
  background: #233B50;
}}
QCheckBox::indicator:checked, QAbstractItemView::indicator:checked {{
  background: #65B5FF;
  border-color: #9AD0FF;
  image: url("{CHECKMARK}");
}}
QCheckBox::indicator:indeterminate, QAbstractItemView::indicator:indeterminate {{
  background: #65B5FF;
  border-color: #9AD0FF;
  image: url("{PARTIAL_CHECK}");
}}
QCheckBox::indicator:disabled, QAbstractItemView::indicator:disabled {{
  border-color: #526578;
  background: #1C2835;
}}
QCheckBox::indicator:checked:disabled, QAbstractItemView::indicator:checked:disabled {{
  background: #7D9BB5;
  border-color: #8AA5BE;
}}
QCheckBox:disabled {{ color: #8396A9; }}
QGroupBox {{
  background: #1B2734;
  border: 1px solid #40566B;
  border-radius: 10px;
  margin-top: 16px;
  padding: 19px 14px 12px;
  font-weight: 650;
}}
QGroupBox::title {{
  subcontrol-origin: margin;
  left: 13px;
  padding: 0 7px;
  color: #D4E6F7;
}}
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
  background: #26394B;
  color: #D9E8F5;
  border: none;
  border-right: 1px solid {BORDER};
  padding: 6px 9px;
}}
QTableView::item {{ padding: 3px 7px; }}
QTableView::item:hover {{ background: #21374B; }}
QTableView::item:selected {{ background: #2A567A; color: #FFFFFF; }}
QSplitter::handle {{ background: #2D3D4C; }}
QSplitter::handle:hover {{ background: #6388A9; }}
QScrollBar:vertical {{ background: #16212B; width: 10px; }}
QScrollBar:horizontal {{ background: #16212B; height: 10px; }}
QScrollBar::handle {{ background: #486079; border-radius: 4px; min-height: 20px; min-width: 20px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0px; width: 0px; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QProgressBar {{
  border: 1px solid {BORDER};
  background: #101923;
  border-radius: 4px;
  text-align: center;
}}
QProgressBar::chunk {{ background: #2D729F; border-radius: 4px; }}
QToolTip {{
  background: #203246;
  color: #F0F6FC;
  border: 1px solid #6688A6;
  border-radius: 7px;
  padding: 9px 11px;
  font-size: 12px;
}}
"""

