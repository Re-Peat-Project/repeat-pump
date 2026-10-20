"""One QSS theme for the wizard. The wizard paints its own backgrounds, so it looks the same in QGIS light and dark themes."""

INK, MUTED = "#17261F", "#4C5E57"
RAIL, RAIL_TEXT, RAIL_MUTED = "#0F2B26", "#F2F7F4", "#9FB5AD"
GROUND, CARD, LINE = "#F4F1EA", "#FFFFFF", "#E3DECF"
TEAL, TEAL_DARK, TEAL_TINT = "#1F8A8A", "#1F6F6F", "#E4F1EE"
AMBER, AMBER_TINT, AMBER_TEXT, AMBER_LINE = "#F2A93B", "#FFF1DC", "#7A4300", "#EBC689"
GREEN, GREEN_TINT, GREEN_TEXT = "#2E9E7B", "#E4F4EC", "#14573D"
RED, RED_TINT, RED_TEXT = "#C0392B", "#FBE5E1", "#7B1F15"

QSS = f"""
#wizard {{ background: {GROUND}; color: {INK}; font-family: "Segoe UI", "Noto Sans", "Helvetica Neue", sans-serif; font-size: 10pt; }}
#wizard QLabel {{ background: transparent; }}

/* ---------- rail ---------- */
#rail {{ background: {RAIL}; }}
#rail QLabel {{ color: {RAIL_TEXT}; }}
#brandTitle {{ font-size: 13pt; font-weight: 800; }}
#brandSub, #railNote {{ color: {RAIL_MUTED}; font-size: 8.5pt; }}
#runChip {{ background: rgba(255,255,255,0.07); border-radius: 10px; }}
#runChipTitle {{ font-weight: 600; }}
#runChipSub {{ color: {RAIL_MUTED}; font-size: 8.5pt; }}
#railBtn {{ background: transparent; color: {RAIL_TEXT}; border: 1px solid rgba(255,255,255,0.25); border-radius: 8px; padding: 6px 10px; }}
#railBtn:hover {{ background: rgba(255,255,255,0.10); }}

#stageRow {{ background: transparent; border: none; border-left: 3px solid transparent; border-radius: 8px; text-align: left; padding: 0; }}
#stageRow:hover {{ background: rgba(255,255,255,0.06); }}
#stageRow[current="true"] {{ background: rgba(255,255,255,0.11); border-left: 3px solid #7FD1C4; }}
#stageRow[current="true"][status="needs_review"] {{ border-left: 3px solid {AMBER}; }}
#stageRow[current="true"][status="failed"] {{ border-left: 3px solid #E8786B; }}
#stageName {{ color: {RAIL_TEXT}; font-weight: 600; }}
#stageRow[status="locked"] #stageName {{ color: {RAIL_MUTED}; }}
#stageSub {{ color: {RAIL_MUTED}; font-size: 8.5pt; }}
#stageRow[status="needs_review"] #stageSub {{ color: #F6C06A; }}
#stageRow[status="failed"] #stageSub {{ color: #F2A097; }}
#stageRow[status="stale"] #stageSub {{ color: #F6C06A; }}
#stageRow[current="true"][status="stale"] {{ border-left: 3px solid {AMBER}; }}
#badge {{ border-radius: 14px; font-weight: 700; font-size: 9pt; }}
#badge[status="done"] {{ background: {GREEN}; color: white; }}
#badge[status="ready"], #badge[status="running"] {{ background: transparent; border: 2px solid #7FD1C4; color: #9BE3D6; }}
#badge[status="needs_review"] {{ background: {AMBER}; color: #2A1A00; }}
#badge[status="failed"] {{ background: #E8786B; color: #2A0804; }}
#badge[status="skipped"] {{ background: transparent; border: 2px dashed {RAIL_MUTED}; color: {RAIL_MUTED}; }}
#badge[status="stale"] {{ background: transparent; border: 2px solid {AMBER}; color: {AMBER}; }}
#badge[status="locked"] {{ background: rgba(255,255,255,0.08); color: {RAIL_MUTED}; }}

/* ---------- header and footer ---------- */
#header {{ background: {GROUND}; border-bottom: 1px solid #DDD8CB; }}
#footer {{ background: #EFEBDF; border-top: 1px solid #DDD8CB; }}
#crumb {{ color: {MUTED}; font-size: 9pt; }}
#chip {{ background: #E7E2D4; border-radius: 10px; padding: 2px 10px; font-weight: 600; font-size: 8.5pt; }}
#footerNote {{ color: {AMBER_TEXT}; font-weight: 600; }}
#lang {{ background: transparent; color: {MUTED}; border: 1px solid #C9C3B3; padding: 3px 10px; font-weight: 700; font-size: 8.5pt; }}
#lang:checked {{ background: {TEAL_DARK}; color: white; border: 1px solid {TEAL_DARK}; }}
#lang:hover:!checked {{ background: rgba(0,0,0,0.05); }}
QCheckBox#learn {{ spacing: 8px; font-weight: 600; }}
QCheckBox#learn::indicator {{ width: 34px; height: 18px; border-radius: 9px; background: #B7B09D; }}
QCheckBox#learn::indicator:checked {{ background: {TEAL_DARK}; }}

/* ---------- body ---------- */
#body {{ background: {GROUND}; border: none; }}
#bodyInner {{ background: {GROUND}; }}
#eyebrow {{ color: {TEAL_DARK}; font-weight: 700; font-size: 8.5pt; letter-spacing: 1px; }}
#eyebrow[tone="review"] {{ color: {AMBER_TEXT}; }}
#eyebrow[tone="failed"] {{ color: {RED_TEXT}; }}
#title {{ font-size: 21pt; font-weight: 800; }}
#purpose {{ color: #3B4D46; font-size: 11pt; }}
#cardTitle {{ font-weight: 700; font-size: 11pt; }}
#hint {{ color: {MUTED}; font-size: 9pt; }}

#card {{ background: {CARD}; border: 1px solid {LINE}; border-radius: 14px; }}
#learnCard {{ background: {TEAL_TINT}; border-radius: 14px; }}
#learnRef {{ color: {TEAL_DARK}; font-weight: 600; font-size: 8.5pt; }}

#tile {{ background: {CARD}; border: 1px solid {LINE}; border-radius: 14px; }}
#tile[warn="true"] {{ background: {AMBER_TINT}; border: 1px solid {AMBER_LINE}; }}
#tileLabel {{ color: {MUTED}; font-weight: 600; font-size: 8.5pt; }}
#tileValue {{ font-size: 22pt; font-weight: 800; }}
#tile[warn="true"] #tileValue {{ color: {AMBER_TEXT}; }}
#tile[warn="true"] #tileLabel {{ color: #5E3500; }}
#tileNote {{ color: {MUTED}; font-size: 8.5pt; }}

#callout {{ border-radius: 12px; border: 1px solid {AMBER_LINE}; background: {AMBER_TINT}; }}
#callout QLabel {{ color: #5E3500; }}
#callout[tone="error"] {{ border: 1px solid #E8A59D; background: {RED_TINT}; }}
#callout[tone="error"] QLabel {{ color: {RED_TEXT}; }}
#callout[tone="info"] {{ border: 1px solid #B6D9D3; background: {TEAL_TINT}; }}
#callout[tone="info"] QLabel {{ color: #164E4E; }}

#paramLabel {{ font-weight: 600; }}
#paramHelp {{ color: {MUTED}; font-size: 8.5pt; }}
#paramProposed {{ color: {AMBER_TEXT}; font-size: 8.5pt; font-weight: 600; }}
#progressFrame {{ background: {AMBER_TINT}; border-top: 1px solid {AMBER_LINE}; }}
QProgressBar {{ background: #DCE5E0; border: none; border-radius: 4px; }}
QProgressBar::chunk {{ background: {TEAL}; border-radius: 4px; }}
#paramUnit {{ color: {MUTED}; }}
#wizard QLineEdit, #wizard QComboBox, #wizard QgsFileWidget {{ border: 1px solid #C9C3B3; border-radius: 8px; padding: 6px 8px; background: #FBFAF6; color: {INK}; }}
#wizard QLineEdit[missing="true"], #wizard QComboBox[missing="true"] {{ border: 2px solid #D98A1F; background: #FFF6E6; }}
#wizard QLineEdit[invalid="true"] {{ border: 2px solid {RED}; background: {RED_TINT}; }}
#wizard QLineEdit:focus, #wizard QComboBox:focus {{ border: 2px solid {TEAL}; }}
#wizard QPlainTextEdit {{ background: #101C19; color: #D7E5DF; font-family: Consolas, "DejaVu Sans Mono", monospace; font-size: 8.5pt; border-radius: 10px; padding: 8px; }}

#primary {{ background: {TEAL_DARK}; color: white; border: none; border-radius: 10px; padding: 10px 22px; font-weight: 700; font-size: 10.5pt; }}
#primary:hover {{ background: #195C5C; }}
#primary:disabled {{ background: #CFCABB; color: #5E6A64; }}
#primary[danger="true"] {{ background: #8A4B00; }}
#secondary {{ background: transparent; color: {TEAL_DARK}; border: 1px solid {TEAL_DARK}; border-radius: 10px; padding: 10px 18px; font-weight: 700; }}
#secondary:hover {{ background: rgba(31,111,111,0.08); }}
#secondary:disabled {{ color: #8A948F; border: 1px solid #B7B09D; }}
#ghost {{ background: transparent; color: {INK}; border: 1px solid #B7B09D; border-radius: 10px; padding: 10px 18px; font-weight: 700; }}
#ghost:hover {{ background: rgba(0,0,0,0.04); }}
#ghost:disabled {{ color: #8A948F; }}
#link {{ background: transparent; border: none; color: {TEAL_DARK}; font-weight: 600; text-align: left; padding: 2px 0; }}
#link:hover {{ text-decoration: underline; }}
"""

CHECK_SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{c}" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12.5l4.5 4.5L19 7"/></svg>'
LOCK_SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{c}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/></svg>'
DROP_SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{c}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3c3.5 4.2 6 7.2 6 10.5a6 6 0 0 1-12 0C6 10.2 8.5 7.2 12 3z"/><path d="M9 14.5a3 3 0 0 0 3 2.5"/></svg>'
WARN_SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{c}" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l10 18H2z"/><path d="M12 10v5M12 18.5v.1"/></svg>'
