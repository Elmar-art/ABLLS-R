from collections import defaultdict
from datetime import date, datetime, timezone
import io
from pathlib import Path
import re

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as pdf_canvas
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.ablls_catalog import SECTION_NAMES
from app.core.database import get_db
from app.models.ablls_task import ABLLSTask
from app.models.assessment import Assessment
from app.models.assignment import ChildParentAssignment, ChildTherapistAssignment
from app.models.audit_log import AuditLog
from app.models.child import Child
from app.models.edit_request import EditRequest
from app.models.user import User

router = APIRouter()
templates = Jinja2Templates(directory="templates")
SECTION_ORDER = list(SECTION_NAMES.keys())
PDF_FONT_REGULAR = "Helvetica"
PDF_FONT_BOLD = "Helvetica-Bold"
PDF_FONTS_READY = False


def _current_user(request: Request, db: Session):
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    return db.get(User, user_id)


def _base_context(request: Request, db: Session) -> dict:
    flash_message = request.session.pop("flash_success", None)
    return {
        "request": request,
        "current_user": _current_user(request, db),
        "flash_message": flash_message,
        "today": date.today().isoformat(),
        "role_labels": {
            "admin": "Администратор",
            "therapist": "Терапист",
            "parent": "Родитель",
        },
    }


def _set_flash(request: Request, message: str):
    request.session["flash_success"] = message


def _log_action(db: Session, user_id: str | None, action: str, details: str):
    db.add(AuditLog(user_id=user_id, action=action, details=details))


def _parse_date(raw_value: str | None) -> date | None:
    if not raw_value:
        return None
    try:
        return datetime.strptime(raw_value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _require_roles(request: Request, db: Session, allowed_roles: set[str]):
    user = _current_user(request, db)
    if not user:
        _set_flash(request, "Сначала войдите в систему.")
        return None, RedirectResponse(url="/auth/login", status_code=303)
    if user.role not in allowed_roles:
        context = _base_context(request, db)
        context["required_roles"] = [
            context["role_labels"].get(role, role) for role in sorted(allowed_roles)
        ]
        return user, templates.TemplateResponse(
            "forbidden.html",
            context,
            status_code=403,
        )
    return user, None


def _children_for_therapist(db: Session, therapist_id: str) -> list[Child]:
    child_ids = db.execute(
        select(ChildTherapistAssignment.child_id).where(
            ChildTherapistAssignment.therapist_id == therapist_id
        )
    ).scalars().all()
    if not child_ids:
        return []
    return db.execute(
        select(Child).where(Child.id.in_(child_ids)).order_by(Child.full_name.asc())
    ).scalars().all()


def _children_for_parent(db: Session, parent_id: str) -> list[Child]:
    child_ids = db.execute(
        select(ChildParentAssignment.child_id).where(
            ChildParentAssignment.parent_id == parent_id
        )
    ).scalars().all()
    if not child_ids:
        return []
    return db.execute(
        select(Child).where(Child.id.in_(child_ids)).order_by(Child.full_name.asc())
    ).scalars().all()


def _all_ablls_tasks(db: Session) -> list[ABLLSTask]:
    return db.execute(
        select(ABLLSTask).order_by(ABLLSTask.section_code.asc(), ABLLSTask.item_number.asc())
    ).scalars().all()


def _section_options(tasks: list[ABLLSTask]) -> list[dict]:
    seen = set()
    options = []
    for task in tasks:
        if task.section_code in seen:
            continue
        seen.add(task.section_code)
        options.append(
            {
                "code": task.section_code,
                "name": SECTION_NAMES.get(task.section_code, task.section_name or task.section_code),
            }
        )

    options.sort(
        key=lambda item: SECTION_ORDER.index(item["code"]) if item["code"] in SECTION_ORDER else 999
    )
    return options


def _latest_assessment_by_skill(db: Session, child_id: str) -> dict[str, Assessment]:
    rows = db.execute(
        select(Assessment)
        .where(Assessment.child_id == child_id)
        .order_by(Assessment.assessment_date.desc(), Assessment.created_at.desc())
    ).scalars().all()

    return _latest_assessment_by_skill_from_rows(rows)


def _latest_assessment_by_skill_from_rows(rows: list[Assessment]) -> dict[str, Assessment]:
    latest_by_skill: dict[str, Assessment] = {}
    for row in sorted(
        rows,
        key=lambda item: (item.assessment_date, item.created_at),
        reverse=True,
    ):
        skill_code = (row.area or "").strip().upper()
        if not skill_code or skill_code in latest_by_skill:
            continue
        latest_by_skill[skill_code] = row
    return latest_by_skill


def _section_progress_rows(
    tasks: list[ABLLSTask], latest_by_skill: dict[str, Assessment]
) -> list[dict]:
    section_stats: dict[str, dict] = defaultdict(
        lambda: {
            "section_name": "",
            "total": 0,
            "scored": 0,
            "mastered": 0,
            "relative_points": 0.0,
            "max_points": 0.0,
        }
    )

    for task in tasks:
        stats = section_stats[task.section_code]
        stats["section_name"] = SECTION_NAMES.get(
            task.section_code, task.section_name or task.section_code
        )
        stats["total"] += 1
        stats["max_points"] += float(task.max_score)

        latest = latest_by_skill.get(task.code)
        if latest is None:
            continue

        stats["scored"] += 1
        stats["relative_points"] += float(latest.score)
        if latest.score >= task.max_score:
            stats["mastered"] += 1

    rows = []
    for section_code, stats in section_stats.items():
        total = stats["total"] or 1
        mastered = stats["mastered"]
        completion_pct = round((mastered / total) * 100, 1)
        score_pct = 0.0
        if stats["max_points"] > 0:
            score_pct = round((stats["relative_points"] / stats["max_points"]) * 100, 1)

        rows.append(
            {
                "section_code": section_code,
                "section_name": stats["section_name"],
                "total": stats["total"],
                "scored": stats["scored"],
                "mastered": mastered,
                "completion_pct": completion_pct,
                "score_pct": score_pct,
            }
        )

    rows.sort(
        key=lambda item: SECTION_ORDER.index(item["section_code"])
        if item["section_code"] in SECTION_ORDER
        else 999
    )
    return rows


def _tracking_level_for_task(task: ABLLSTask, latest: Assessment | None) -> tuple[str, str]:
    if latest is None:
        return "ablls-level-none", "Не оценено"

    max_score = max(int(task.max_score or 1), 1)
    ratio = float(latest.score) / float(max_score)

    if ratio >= 1.0:
        if latest.is_prompted:
            return "ablls-level-mastered-prompted", "Освоено с подсказкой"
        return "ablls-level-mastered-independent", "Освоено самостоятельно"
    if ratio >= 0.5:
        return "ablls-level-mid", "В процессе (от 50%)"
    return "ablls-level-low", "В процессе (до 50%)"


def _tracking_columns(
    tasks: list[ABLLSTask], latest_by_skill: dict[str, Assessment]
) -> tuple[list[dict], dict]:
    by_section: dict[str, dict[int, ABLLSTask]] = defaultdict(dict)
    section_names: dict[str, str] = {}

    for task in tasks:
        by_section[task.section_code][task.item_number] = task
        section_names[task.section_code] = SECTION_NAMES.get(
            task.section_code, task.section_name or task.section_code
        )

    section_codes = sorted(
        by_section.keys(),
        key=lambda code: SECTION_ORDER.index(code) if code in SECTION_ORDER else 999,
    )

    columns: list[dict] = []
    totals = {
        "none": 0,
        "low": 0,
        "mid": 0,
        "mastered_prompted": 0,
        "mastered_independent": 0,
    }

    for section_code in section_codes:
        section_tasks = by_section[section_code]
        max_item = max(section_tasks.keys()) if section_tasks else 0
        rows: list[dict] = []

        for item_number in range(max_item, 0, -1):
            task = section_tasks.get(item_number)
            if not task:
                rows.append(
                    {
                        "has_task": False,
                        "code": "",
                        "level_class": "ablls-level-gap",
                        "title": "",
                    }
                )
                continue

            latest = latest_by_skill.get(task.code)
            level_class, level_label = _tracking_level_for_task(task, latest)
            if level_class == "ablls-level-none":
                totals["none"] += 1
            elif level_class == "ablls-level-low":
                totals["low"] += 1
            elif level_class == "ablls-level-mid":
                totals["mid"] += 1
            elif level_class == "ablls-level-mastered-prompted":
                totals["mastered_prompted"] += 1
            elif level_class == "ablls-level-mastered-independent":
                totals["mastered_independent"] += 1

            if latest is None:
                title = f"{task.code}: не оценено"
            else:
                mode = "с подсказкой" if latest.is_prompted else "самостоятельно"
                title = (
                    f"{task.code}: {latest.score}/{task.max_score}, {mode}, "
                    f"{latest.assessment_date.isoformat()}"
                )

            rows.append(
                {
                    "has_task": True,
                    "code": task.code,
                    "level_class": level_class,
                    "title": title,
                }
            )

        columns.append(
            {
                "section_code": section_code,
                "section_name": section_names.get(section_code, section_code),
                "rows": rows,
            }
        )

    return columns, totals


def _ensure_pdf_fonts() -> tuple[str, str]:
    global PDF_FONTS_READY, PDF_FONT_REGULAR, PDF_FONT_BOLD
    if PDF_FONTS_READY:
        return PDF_FONT_REGULAR, PDF_FONT_BOLD

    candidates = [
        (
            "ABLLSRegular",
            "ABLLSBold",
            Path("C:/Windows/Fonts/arial.ttf"),
            Path("C:/Windows/Fonts/arialbd.ttf"),
        ),
        (
            "ABLLSRegular",
            "ABLLSBold",
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        ),
    ]

    for regular_name, bold_name, regular_path, bold_path in candidates:
        if not regular_path.exists() or not bold_path.exists():
            continue
        try:
            pdfmetrics.registerFont(TTFont(regular_name, str(regular_path)))
            pdfmetrics.registerFont(TTFont(bold_name, str(bold_path)))
            PDF_FONT_REGULAR = regular_name
            PDF_FONT_BOLD = bold_name
            break
        except Exception:
            continue

    PDF_FONTS_READY = True
    return PDF_FONT_REGULAR, PDF_FONT_BOLD


def _pdf_level_color(level_class: str):
    color_map = {
        "ablls-level-none": colors.HexColor("#F6F9FB"),
        "ablls-level-low": colors.HexColor("#F3BFBA"),
        "ablls-level-mid": colors.HexColor("#F5E4AA"),
        "ablls-level-mastered-prompted": colors.HexColor("#BEDCF3"),
        "ablls-level-mastered-independent": colors.HexColor("#BFE7C7"),
        "ablls-level-gap": colors.HexColor("#F3F5F4"),
    }
    return color_map.get(level_class, colors.white)


def _short_text(value: str, limit: int) -> str:
    normalized = " ".join((value or "").split())
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[: max(1, limit - 1)]}..."


def _report_payload(db: Session, query_params) -> dict:
    visible_children = db.execute(select(Child).order_by(Child.full_name.asc())).scalars().all()

    selected_child_id = query_params.get("child_id")
    visible_child_ids = {child.id for child in visible_children}
    if selected_child_id not in visible_child_ids:
        selected_child_id = visible_children[0].id if visible_children else None

    tasks = _all_ablls_tasks(db)
    task_by_code = {task.code: task for task in tasks}
    sections = _section_options(tasks)
    valid_section_codes = {section["code"] for section in sections}

    selected_section = (query_params.get("section") or "ALL").strip().upper()
    if selected_section != "ALL" and selected_section not in valid_section_codes:
        selected_section = "ALL"

    selected_mode = (query_params.get("mode") or "ALL").strip().lower()
    if selected_mode not in {"ALL", "independent", "prompted"}:
        selected_mode = "ALL"

    selected_skill_code = (query_params.get("skill_code") or "").strip().upper()

    date_from_input = (query_params.get("date_from") or "").strip()
    date_to_input = (query_params.get("date_to") or "").strip()
    selected_date_from = _parse_date(date_from_input)
    selected_date_to = _parse_date(date_to_input)
    if selected_date_from and selected_date_to and selected_date_from > selected_date_to:
        selected_date_from, selected_date_to = selected_date_to, selected_date_from

    selected_child = next((child for child in visible_children if child.id == selected_child_id), None)

    recent_rows: list[Assessment] = []
    daily_points: list[dict] = []
    filtered_assessment_count = 0
    latest_by_skill: dict[str, Assessment] = {}

    filtered_tasks_for_summary = tasks
    if selected_section != "ALL":
        filtered_tasks_for_summary = [
            task for task in filtered_tasks_for_summary if task.section_code == selected_section
        ]
    if selected_skill_code:
        filtered_tasks_for_summary = [
            task for task in filtered_tasks_for_summary if task.code.startswith(selected_skill_code)
        ]

    section_rows: list[dict] = []
    tracking_columns: list[dict] = []
    tracking_totals = {
        "none": 0,
        "low": 0,
        "mid": 0,
        "mastered_prompted": 0,
        "mastered_independent": 0,
    }
    if selected_child:
        query = select(Assessment).where(Assessment.child_id == selected_child.id)

        if selected_date_from:
            query = query.where(Assessment.assessment_date >= selected_date_from)
        if selected_date_to:
            query = query.where(Assessment.assessment_date <= selected_date_to)

        if selected_mode == "independent":
            query = query.where(Assessment.is_prompted.is_(False))
        elif selected_mode == "prompted":
            query = query.where(Assessment.is_prompted.is_(True))

        if selected_section != "ALL" or selected_skill_code:
            filtered_skill_codes = [task.code for task in filtered_tasks_for_summary]
            if filtered_skill_codes:
                query = query.where(Assessment.area.in_(filtered_skill_codes))
            else:
                query = query.where(Assessment.area == "__NO_MATCH__")

        recent_rows = db.execute(
            query.order_by(Assessment.assessment_date.desc(), Assessment.created_at.desc()).limit(80)
        ).scalars().all()

        all_rows = db.execute(
            query.order_by(Assessment.assessment_date.asc(), Assessment.created_at.asc())
        ).scalars().all()
        filtered_assessment_count = len(all_rows)

        latest_by_skill = _latest_assessment_by_skill_from_rows(all_rows)
        section_rows = _section_progress_rows(filtered_tasks_for_summary, latest_by_skill)
        tracking_columns, tracking_totals = _tracking_columns(
            filtered_tasks_for_summary,
            latest_by_skill,
        )

        by_day: dict[str, dict[str, int]] = defaultdict(
            lambda: {"independent": 0, "prompted": 0}
        )
        for row in all_rows:
            if row.score <= 0:
                continue
            day_key = row.assessment_date.isoformat()
            if row.is_prompted:
                by_day[day_key]["prompted"] += 1
            else:
                by_day[day_key]["independent"] += 1

        daily_points = [
            {
                "date": day,
                "independent": values["independent"],
                "prompted": values["prompted"],
            }
            for day, values in sorted(by_day.items(), key=lambda item: item[0])
        ]

    return {
        "visible_children": visible_children,
        "selected_child": selected_child,
        "selected_child_id": selected_child_id,
        "sections": sections,
        "selected_section": selected_section,
        "selected_mode": selected_mode,
        "selected_skill_code": selected_skill_code,
        "selected_date_from": selected_date_from.isoformat() if selected_date_from else "",
        "selected_date_to": selected_date_to.isoformat() if selected_date_to else "",
        "filtered_assessment_count": filtered_assessment_count,
        "section_rows": section_rows,
        "tracking_columns": tracking_columns,
        "tracking_totals": tracking_totals,
        "recent_assessments": recent_rows,
        "daily_points": daily_points,
        "task_by_code": task_by_code,
        "filtered_tasks_for_summary": filtered_tasks_for_summary,
        "latest_by_skill": latest_by_skill,
    }


def _build_report_pdf(payload: dict) -> bytes:
    regular_font, bold_font = _ensure_pdf_fonts()
    page_width, page_height = landscape(A4)
    margin = 24.0
    buffer = io.BytesIO()
    pdf = pdf_canvas.Canvas(buffer, pagesize=landscape(A4))

    selected_child = payload["selected_child"]
    tracking_columns = payload["tracking_columns"]
    tracking_totals = payload["tracking_totals"]
    section_rows = payload["section_rows"]
    selected_section = payload["selected_section"]
    selected_mode = payload["selected_mode"]
    selected_skill_code = payload["selected_skill_code"]
    selected_date_from = payload["selected_date_from"]
    selected_date_to = payload["selected_date_to"]
    filtered_tasks = payload["filtered_tasks_for_summary"]

    filters: list[str] = []
    if selected_section != "ALL":
        filters.append(f"Раздел: {selected_section}")
    if selected_mode == "independent":
        filters.append("Режим: самостоятельно")
    elif selected_mode == "prompted":
        filters.append("Режим: с подсказкой")
    if selected_skill_code:
        filters.append(f"Код: {selected_skill_code}")
    if selected_date_from:
        filters.append(f"С: {selected_date_from}")
    if selected_date_to:
        filters.append(f"По: {selected_date_to}")

    legend_rows = [
        ("ablls-level-none", f"Не оценено ({tracking_totals['none']})"),
        ("ablls-level-low", f"До 50% ({tracking_totals['low']})"),
        ("ablls-level-mid", f"От 50% до максимума ({tracking_totals['mid']})"),
        (
            "ablls-level-mastered-prompted",
            f"Освоено с подсказкой ({tracking_totals['mastered_prompted']})",
        ),
        (
            "ablls-level-mastered-independent",
            f"Освоено самостоятельно ({tracking_totals['mastered_independent']})",
        ),
    ]

    def draw_header(title_suffix: str = "") -> float:
        y = page_height - margin
        pdf.setFillColor(colors.HexColor("#1E3444"))
        pdf.setFont(bold_font, 14)
        pdf.drawString(margin, y, "ABLLS-R Skills Tracking Report")
        if title_suffix:
            pdf.setFont(regular_font, 9)
            pdf.drawRightString(page_width - margin, y + 1, title_suffix)

        y -= 18
        pdf.setFont(bold_font, 11)
        pdf.drawString(margin, y, f"Ребенок: {selected_child.full_name}")
        pdf.setFont(regular_font, 9)
        pdf.drawRightString(page_width - margin, y, f"Дата отчета: {date.today().isoformat()}")

        y -= 13
        pdf.setFont(regular_font, 8.5)
        filter_text = ", ".join(filters) if filters else "Без дополнительных фильтров"
        pdf.drawString(margin, y, f"Фильтры: {filter_text}")

        y -= 14
        x = margin
        for level_class, label in legend_rows:
            item_width = 118
            if x + item_width > page_width - margin:
                x = margin
                y -= 12
            pdf.setFillColor(_pdf_level_color(level_class))
            pdf.setStrokeColor(colors.HexColor("#7A8F88"))
            pdf.rect(x, y - 8, 10, 10, fill=1, stroke=1)
            pdf.setFillColor(colors.HexColor("#2E4C60"))
            pdf.setFont(regular_font, 7.6)
            pdf.drawString(x + 14, y - 1, label)
            x += item_width

        y -= 17
        total_skills = len(filtered_tasks)
        assessed = total_skills - tracking_totals["none"]
        in_progress = tracking_totals["low"] + tracking_totals["mid"]
        summary = (
            f"Всего навыков: {total_skills}    Оценено: {assessed}    "
            f"В процессе: {in_progress}    "
            f"Освоено сам.: {tracking_totals['mastered_independent']}    "
            f"Освоено с подсказкой: {tracking_totals['mastered_prompted']}"
        )
        pdf.setFillColor(colors.HexColor("#355062"))
        pdf.setFont(regular_font, 8.4)
        pdf.drawString(margin, y, summary)
        return y - 12

    map_columns = tracking_columns or []
    if not map_columns:
        map_top = draw_header()
        pdf.setFont(regular_font, 11)
        pdf.setFillColor(colors.HexColor("#4A6271"))
        pdf.drawString(margin, map_top - 20, "Нет данных для построения карты навыков.")
    else:
        start = 0
        page_index = 1
        column_width = 58.0
        code_width = 34.0
        cell_width = 14.0
        while start < len(map_columns):
            if page_index > 1:
                pdf.showPage()
            map_top = draw_header(f"Карта навыков, стр. {page_index}")
            map_bottom = margin + 34
            available_width = page_width - (margin * 2)
            available_height = max(120.0, map_top - map_bottom)
            columns_per_page = max(1, int(available_width // column_width))
            chunk = map_columns[start : start + columns_per_page]
            start += columns_per_page

            max_rows = 1
            for column in chunk:
                row_count = len([row for row in column["rows"] if row.get("has_task")])
                max_rows = max(max_rows, row_count)

            cell_height = max(4.0, min(8.3, (available_height - 18) / max_rows))
            row_step = cell_height + 0.8

            pdf.setStrokeColor(colors.HexColor("#B7C9BF"))
            pdf.rect(
                margin - 4,
                map_bottom - 18,
                available_width + 8,
                available_height + 20,
                fill=0,
                stroke=1,
            )

            for idx, column in enumerate(chunk):
                x = margin + (idx * column_width)
                rows = [row for row in column["rows"] if row.get("has_task")]
                pdf.setFont(regular_font, 5.6)
                for row_idx, row in enumerate(rows):
                    y = map_top - (row_idx * row_step) - cell_height
                    pdf.setFillColor(colors.HexColor("#5C6E7B"))
                    pdf.drawRightString(x + code_width - 2, y + (cell_height * 0.2), row["code"])
                    pdf.setFillColor(_pdf_level_color(row["level_class"]))
                    pdf.setStrokeColor(colors.HexColor("#7A8F88"))
                    pdf.rect(x + code_width, y, cell_width, cell_height, fill=1, stroke=1)

                label_center = x + code_width + (cell_width / 2)
                pdf.setFillColor(colors.HexColor("#24455C"))
                pdf.setFont(bold_font, 7.2)
                pdf.drawCentredString(label_center, map_bottom - 9, column["section_code"])
                pdf.setFont(regular_font, 5.6)
                pdf.drawCentredString(
                    label_center,
                    map_bottom - 17,
                    _short_text(column["section_name"], 16),
                )
            page_index += 1

    pdf.showPage()
    y = page_height - margin
    pdf.setFillColor(colors.HexColor("#1E3444"))
    pdf.setFont(bold_font, 14)
    pdf.drawString(margin, y, "Сводка прогресса по разделам")
    pdf.setFont(regular_font, 9)
    pdf.drawRightString(page_width - margin, y + 1, "ABLLS-R")

    y -= 18
    pdf.setFont(bold_font, 11)
    pdf.drawString(margin, y, f"Ребенок: {selected_child.full_name}")
    y -= 14

    info_rows = [
        f"Не оценено: {tracking_totals['none']}",
        f"До 50%: {tracking_totals['low']}",
        f"От 50% до максимума: {tracking_totals['mid']}",
        f"Освоено с подсказкой: {tracking_totals['mastered_prompted']}",
        f"Освоено самостоятельно: {tracking_totals['mastered_independent']}",
    ]
    pdf.setFont(regular_font, 8.8)
    for line in info_rows:
        pdf.drawString(margin, y, line)
        y -= 12

    y -= 4
    table_headers = ["Раздел", "Освоено", "Оценено", "Всего", "Выполнение %", "Средний балл %"]
    col_widths = [250, 70, 70, 62, 95, 95]
    row_height = 15
    table_x = margin
    table_right = table_x + sum(col_widths)

    def draw_table_header(current_y: float) -> float:
        pdf.setFillColor(colors.HexColor("#E2F0E8"))
        pdf.setStrokeColor(colors.HexColor("#AAC0B4"))
        pdf.rect(table_x, current_y - row_height, table_right - table_x, row_height, fill=1, stroke=1)
        cursor_x = table_x
        pdf.setFillColor(colors.HexColor("#365062"))
        pdf.setFont(bold_font, 8)
        for header, width in zip(table_headers, col_widths):
            pdf.drawString(cursor_x + 3, current_y - 10.5, header)
            cursor_x += width
        return current_y - row_height

    y = draw_table_header(y)
    pdf.setFont(regular_font, 8)
    for row in section_rows:
        if y < margin + 24:
            pdf.showPage()
            y = page_height - margin
            pdf.setFillColor(colors.HexColor("#1E3444"))
            pdf.setFont(bold_font, 11)
            pdf.drawString(margin, y, "Сводка прогресса по разделам (продолжение)")
            y -= 16
            y = draw_table_header(y)
            pdf.setFont(regular_font, 8)

        values = [
            f"{row['section_code']} - {_short_text(row['section_name'], 36)}",
            str(row["mastered"]),
            str(row["scored"]),
            str(row["total"]),
            str(row["completion_pct"]),
            str(row["score_pct"]),
        ]
        pdf.setFillColor(colors.white)
        pdf.setStrokeColor(colors.HexColor("#D0DDD6"))
        pdf.rect(table_x, y - row_height, table_right - table_x, row_height, fill=1, stroke=1)
        cursor_x = table_x
        pdf.setFillColor(colors.HexColor("#344F61"))
        for value, width in zip(values, col_widths):
            pdf.drawString(cursor_x + 3, y - 10.5, _short_text(value, 46))
            cursor_x += width
        y -= row_height

    pdf.save()
    buffer.seek(0)
    return buffer.getvalue()


@router.get("/")
def index(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse("index.html", _base_context(request, db))


@router.get("/favicon.ico", include_in_schema=False)
def favicon():
    return Response(status_code=204)


@router.get("/dashboard")
def dashboard(request: Request, db: Session = Depends(get_db)):
    _, response = _require_roles(request, db, {"admin", "therapist", "parent"})
    if response:
        return response
    return templates.TemplateResponse("dashboard.html", _base_context(request, db))


@router.get("/children")
def children(request: Request, db: Session = Depends(get_db)):
    user, response = _require_roles(request, db, {"admin", "therapist"})
    if response:
        return response

    context = _base_context(request, db)
    if user.role == "admin":
        children_list = db.execute(
            select(Child).order_by(Child.created_at.desc())
        ).scalars().all()
        therapists = db.execute(
            select(User).where(User.role == "therapist").order_by(User.full_name.asc())
        ).scalars().all()
        parents = db.execute(
            select(User).where(User.role == "parent").order_by(User.full_name.asc())
        ).scalars().all()
        t_assignments = db.execute(select(ChildTherapistAssignment)).scalars().all()
        p_assignments = db.execute(select(ChildParentAssignment)).scalars().all()

        therapist_map = {u.id: u for u in therapists}
        parent_map = {u.id: u for u in parents}
        child_therapists: dict[str, list[User]] = {c.id: [] for c in children_list}
        child_parents: dict[str, list[User]] = {c.id: [] for c in children_list}

        for row in t_assignments:
            therapist = therapist_map.get(row.therapist_id)
            if therapist and row.child_id in child_therapists:
                child_therapists[row.child_id].append(therapist)
        for row in p_assignments:
            parent = parent_map.get(row.parent_id)
            if parent and row.child_id in child_parents:
                child_parents[row.child_id].append(parent)

        context.update(
            {
                "children_list": children_list,
                "therapists": therapists,
                "parents": parents,
                "child_therapists": child_therapists,
                "child_parents": child_parents,
            }
        )
    else:
        context["assigned_children"] = _children_for_therapist(db, user.id)

    return templates.TemplateResponse("children.html", context)


@router.post("/children")
def create_child(
    request: Request,
    db: Session = Depends(get_db),
    full_name: str = Form(...),
    birth_date: str = Form(""),
    notes: str = Form(""),
):
    user, response = _require_roles(request, db, {"admin"})
    if response:
        return response

    name = full_name.strip()
    if not name:
        _set_flash(request, "Укажите ФИО ребенка.")
        return RedirectResponse(url="/children", status_code=303)

    child = Child(
        full_name=name,
        birth_date=_parse_date(birth_date),
        notes=notes.strip() or None,
        created_by=user.id,
    )
    db.add(child)
    _log_action(db, user.id, "create_child", f"Создан ребенок: {name}")
    db.commit()
    _set_flash(request, "Ребенок добавлен.")
    return RedirectResponse(url="/children", status_code=303)


@router.post("/children/{child_id}/assign-therapist")
def assign_therapist(
    child_id: str,
    request: Request,
    db: Session = Depends(get_db),
    therapist_id: str = Form(...),
):
    user, response = _require_roles(request, db, {"admin"})
    if response:
        return response

    child = db.get(Child, child_id)
    therapist = db.get(User, therapist_id)
    if not child or not therapist or therapist.role != "therapist":
        _set_flash(request, "Некорректный ребенок или терапист.")
        return RedirectResponse(url="/children", status_code=303)

    exists = db.execute(
        select(ChildTherapistAssignment).where(
            ChildTherapistAssignment.child_id == child_id,
            ChildTherapistAssignment.therapist_id == therapist_id,
        )
    ).scalar_one_or_none()
    if not exists:
        db.add(ChildTherapistAssignment(child_id=child_id, therapist_id=therapist_id))
        _log_action(
            db,
            user.id,
            "assign_therapist",
            f"Назначен терапист {therapist.email} ребенку {child.full_name}",
        )
        db.commit()
    _set_flash(request, "Терапист назначен.")
    return RedirectResponse(url="/children", status_code=303)


@router.post("/children/{child_id}/assign-parent")
def assign_parent(
    child_id: str,
    request: Request,
    db: Session = Depends(get_db),
    parent_id: str = Form(...),
):
    user, response = _require_roles(request, db, {"admin"})
    if response:
        return response

    child = db.get(Child, child_id)
    parent = db.get(User, parent_id)
    if not child or not parent or parent.role != "parent":
        _set_flash(request, "Некорректный ребенок или родитель.")
        return RedirectResponse(url="/children", status_code=303)

    exists = db.execute(
        select(ChildParentAssignment).where(
            ChildParentAssignment.child_id == child_id,
            ChildParentAssignment.parent_id == parent_id,
        )
    ).scalar_one_or_none()
    if not exists:
        db.add(ChildParentAssignment(child_id=child_id, parent_id=parent_id))
        _log_action(
            db,
            user.id,
            "assign_parent",
            f"Назначен родитель {parent.email} ребенку {child.full_name}",
        )
        db.commit()
    _set_flash(request, "Родитель назначен.")
    return RedirectResponse(url="/children", status_code=303)


@router.get("/assessments")
def assessments(request: Request, db: Session = Depends(get_db)):
    user, response = _require_roles(request, db, {"therapist"})
    if response:
        return response

    assigned_children = _children_for_therapist(db, user.id)
    assigned_child_ids = {child.id for child in assigned_children}

    tasks = _all_ablls_tasks(db)
    task_by_code = {task.code: task for task in tasks}
    sections = _section_options(tasks)

    selected_child_id = request.query_params.get("child_id")
    if selected_child_id not in assigned_child_ids:
        selected_child_id = assigned_children[0].id if assigned_children else None

    selected_section = request.query_params.get("section")
    valid_sections = {section["code"] for section in sections}
    if selected_section not in valid_sections:
        selected_section = sections[0]["code"] if sections else None

    section_tasks = [
        task for task in tasks if selected_section and task.section_code == selected_section
    ]

    latest_by_skill = {}
    recent_rows: list[Assessment] = []
    if selected_child_id:
        latest_by_skill = _latest_assessment_by_skill(db, selected_child_id)
        recent_rows = db.execute(
            select(Assessment)
            .where(Assessment.child_id == selected_child_id)
            .order_by(Assessment.assessment_date.desc(), Assessment.created_at.desc())
            .limit(80)
        ).scalars().all()

    context = _base_context(request, db)
    context.update(
        {
            "assigned_children": assigned_children,
            "sections": sections,
            "selected_child_id": selected_child_id,
            "selected_section": selected_section,
            "section_tasks": section_tasks,
            "task_by_code": task_by_code,
            "latest_by_skill": latest_by_skill,
            "recent_assessments": recent_rows,
        }
    )
    return templates.TemplateResponse("assessments.html", context)


@router.post("/assessments")
def create_assessment(
    request: Request,
    db: Session = Depends(get_db),
    child_id: str = Form(...),
    skill_code: str = Form(...),
    score: int = Form(...),
    is_prompted: bool = Form(False),
    assessment_date: str = Form(...),
    comment: str = Form(""),
):
    user, response = _require_roles(request, db, {"therapist"})
    if response:
        return response

    allowed_child_ids = {child.id for child in _children_for_therapist(db, user.id)}
    if child_id not in allowed_child_ids:
        _set_flash(request, "Вы можете оценивать только назначенных вам детей.")
        return RedirectResponse(url="/assessments", status_code=303)

    task = db.get(ABLLSTask, skill_code.strip().upper())
    if not task:
        _set_flash(request, "Навык ABLLS-R не найден.")
        return RedirectResponse(url="/assessments", status_code=303)

    if score < 0 or score > task.max_score:
        _set_flash(request, f"Для {task.code} допустимая оценка: 0..{task.max_score}.")
        return RedirectResponse(
            url=f"/assessments?child_id={child_id}&section={task.section_code}",
            status_code=303,
        )

    parsed_date = _parse_date(assessment_date)
    if not parsed_date:
        _set_flash(request, "Укажите корректную дату оценки.")
        return RedirectResponse(
            url=f"/assessments?child_id={child_id}&section={task.section_code}",
            status_code=303,
        )

    existing_assessment_id = db.execute(
        select(Assessment.id).where(
            Assessment.child_id == child_id,
            Assessment.area == task.code,
        )
    ).scalar_one_or_none()
    if existing_assessment_id:
        _set_flash(
            request,
            (
                "Навык уже оценен. Повторное изменение возможно только через "
                "запрос на редактирование с причиной."
            ),
        )
        return RedirectResponse(
            url=f"/requests?section={task.section_code}&child_id={child_id}&skill_code={task.code}",
            status_code=303,
        )

    db.add(
        Assessment(
            child_id=child_id,
            therapist_id=user.id,
            area=task.code,
            score=score,
            is_prompted=is_prompted,
            assessment_date=parsed_date,
            comment=comment.strip() or None,
        )
    )
    child = db.get(Child, child_id)
    mode_label = "с подсказкой" if is_prompted else "самостоятельно"
    _log_action(
        db,
        user.id,
        "create_assessment",
        (
            f"Оценка ABLLS-R {task.code}={score} ({mode_label}) "
            f"для {child.full_name if child else child_id}"
        ),
    )
    db.commit()
    _set_flash(request, "Оценка по навыку ABLLS-R сохранена.")
    return RedirectResponse(
        url=f"/assessments?child_id={child_id}&section={task.section_code}",
        status_code=303,
    )


@router.get("/knowledge-base")
def knowledge_base(request: Request, db: Session = Depends(get_db)):
    _, response = _require_roles(request, db, {"admin", "therapist", "parent"})
    if response:
        return response

    tasks = _all_ablls_tasks(db)
    sections = _section_options(tasks)

    section_codes = {section["code"] for section in sections}
    selected_section = request.query_params.get("section")
    if selected_section == "ALL":
        filtered_tasks = tasks
    else:
        if selected_section not in section_codes:
            selected_section = sections[0]["code"] if sections else "ALL"
        filtered_tasks = [task for task in tasks if task.section_code == selected_section]

    context = _base_context(request, db)
    context.update(
        {
            "sections": sections,
            "selected_section": selected_section,
            "knowledge_tasks": filtered_tasks,
            "knowledge_total": len(tasks),
            "knowledge_visible": len(filtered_tasks),
        }
    )
    return templates.TemplateResponse("knowledge_base.html", context)


@router.get("/reports")
def reports(request: Request, db: Session = Depends(get_db)):
    _, response = _require_roles(request, db, {"admin", "therapist", "parent"})
    if response:
        return response

    report_data = _report_payload(db, request.query_params)
    context = _base_context(request, db)
    context.update(report_data)
    return templates.TemplateResponse("reports.html", context)


@router.get("/reports/pdf")
def reports_pdf(request: Request, db: Session = Depends(get_db)):
    _, response = _require_roles(request, db, {"admin", "therapist", "parent"})
    if response:
        return response

    report_data = _report_payload(db, request.query_params)
    selected_child = report_data.get("selected_child")
    if not selected_child:
        _set_flash(request, "Выберите ребенка, чтобы сформировать PDF-отчет.")
        return RedirectResponse(url="/reports", status_code=303)

    pdf_bytes = _build_report_pdf(report_data)
    safe_date = date.today().isoformat()
    safe_name = re.sub(r"[^A-Za-z0-9_-]+", "_", selected_child.full_name or "child").strip("_")
    if not safe_name:
        safe_name = "child"
    filename = f"ablls_report_{safe_name}_{safe_date}.pdf"
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
    }
    return Response(content=pdf_bytes, media_type="application/pdf", headers=headers)


@router.get("/history")
def history(request: Request, db: Session = Depends(get_db)):
    _, response = _require_roles(request, db, {"admin"})
    if response:
        return response

    logs = db.execute(
        select(AuditLog).order_by(AuditLog.created_at.desc()).limit(200)
    ).scalars().all()
    users = db.execute(select(User)).scalars().all()
    user_map = {user.id: user for user in users}
    context = _base_context(request, db)
    context.update({"logs": logs, "log_user_map": user_map})
    return templates.TemplateResponse("history.html", context)


@router.get("/admin/users")
def admin_users(request: Request, db: Session = Depends(get_db)):
    _, response = _require_roles(request, db, {"admin"})
    if response:
        return response

    users = db.execute(select(User).order_by(User.created_at.desc())).scalars().all()
    context = _base_context(request, db)
    context.update({"users": users})
    return templates.TemplateResponse("admin/users.html", context)


@router.get("/admin/edit-requests")
def admin_edit_requests(request: Request, db: Session = Depends(get_db)):
    _, response = _require_roles(request, db, {"admin"})
    if response:
        return response

    reqs = db.execute(
        select(EditRequest).order_by(EditRequest.created_at.desc())
    ).scalars().all()
    children = db.execute(select(Child)).scalars().all()
    users = db.execute(select(User)).scalars().all()
    child_map = {child.id: child for child in children}
    user_map = {user.id: user for user in users}

    req_skill_codes = sorted({(req.area or "").strip().upper() for req in reqs if req.area})
    req_tasks = []
    if req_skill_codes:
        req_tasks = db.execute(select(ABLLSTask).where(ABLLSTask.code.in_(req_skill_codes))).scalars().all()
    req_task_map = {task.code: task for task in req_tasks}

    context = _base_context(request, db)
    context.update(
        {
            "edit_requests": reqs,
            "edit_request_child_map": child_map,
            "edit_request_user_map": user_map,
            "edit_request_task_map": req_task_map,
        }
    )
    return templates.TemplateResponse("admin/edit_requests.html", context)


@router.post("/admin/edit-requests/{request_id}/decision")
def set_edit_request_decision(
    request_id: str,
    request: Request,
    db: Session = Depends(get_db),
    decision: str = Form(...),
    admin_comment: str = Form(""),
):
    user, response = _require_roles(request, db, {"admin"})
    if response:
        return response

    req = db.get(EditRequest, request_id)
    if not req:
        _set_flash(request, "Запрос не найден.")
        return RedirectResponse(url="/admin/edit-requests", status_code=303)

    if decision not in {"approved", "rejected"}:
        _set_flash(request, "Некорректное решение.")
        return RedirectResponse(url="/admin/edit-requests", status_code=303)

    if req.status != "pending":
        _set_flash(request, "Запрос уже обработан ранее.")
        return RedirectResponse(url="/admin/edit-requests", status_code=303)

    if decision == "approved":
        task = db.get(ABLLSTask, (req.area or "").strip().upper())
        if not task:
            _set_flash(request, "Нельзя применить запрос: навык ABLLS-R не найден.")
            return RedirectResponse(url="/admin/edit-requests", status_code=303)

        if req.requested_score is None or req.requested_assessment_date is None:
            _set_flash(
                request,
                "Нельзя применить запрос без нового балла и даты. Попросите тераписта создать новый запрос.",
            )
            return RedirectResponse(url="/admin/edit-requests", status_code=303)

        if req.requested_score < 0 or req.requested_score > task.max_score:
            _set_flash(
                request,
                f"Нельзя применить запрос: новый балл вне диапазона 0..{task.max_score}.",
            )
            return RedirectResponse(url="/admin/edit-requests", status_code=303)

        applied_assessment = Assessment(
            child_id=req.child_id,
            therapist_id=req.therapist_id,
            area=task.code,
            score=req.requested_score,
            is_prompted=bool(req.requested_is_prompted),
            assessment_date=req.requested_assessment_date,
            comment=req.requested_comment,
        )
        db.add(applied_assessment)
        db.flush()
        req.applied_assessment_id = applied_assessment.id

    req.status = decision
    req.admin_comment = admin_comment.strip() or None
    req.reviewed_by = user.id
    req.reviewed_at = datetime.now(timezone.utc)
    _log_action(
        db,
        user.id,
        "review_edit_request",
        (
            f"Запрос {req.id}: {decision} "
            f"(child={req.child_id}, skill={req.area}, applied={req.applied_assessment_id or '-'})"
        ),
    )
    db.commit()
    _set_flash(request, "Решение по запросу сохранено.")
    return RedirectResponse(url="/admin/edit-requests", status_code=303)


@router.get("/requests")
def edit_requests(request: Request, db: Session = Depends(get_db)):
    user, response = _require_roles(request, db, {"therapist"})
    if response:
        return response

    assigned_children = _children_for_therapist(db, user.id)
    child_map = {child.id: child for child in assigned_children}

    tasks = _all_ablls_tasks(db)
    task_by_code = {task.code: task for task in tasks}
    sections = _section_options(tasks)

    selected_section = request.query_params.get("section")
    valid_sections = {section["code"] for section in sections}
    if selected_section not in valid_sections:
        selected_section = sections[0]["code"] if sections else None

    selected_request_child_id = (request.query_params.get("child_id") or "").strip()
    allowed_child_ids = {child.id for child in assigned_children}
    if selected_request_child_id not in allowed_child_ids:
        selected_request_child_id = ""

    selected_request_skill_code = (request.query_params.get("skill_code") or "").strip().upper()

    section_tasks = [
        task for task in tasks if selected_section and task.section_code == selected_section
    ]
    section_task_codes = {task.code for task in section_tasks}
    if selected_request_skill_code not in section_task_codes:
        selected_request_skill_code = ""

    reqs = db.execute(
        select(EditRequest)
        .where(EditRequest.therapist_id == user.id)
        .order_by(EditRequest.created_at.desc())
    ).scalars().all()

    context = _base_context(request, db)
    context.update(
        {
            "assigned_children": assigned_children,
            "my_edit_requests": reqs,
            "my_edit_request_child_map": child_map,
            "task_by_code": task_by_code,
            "sections": sections,
            "selected_section": selected_section,
            "section_tasks": section_tasks,
            "selected_request_child_id": selected_request_child_id,
            "selected_request_skill_code": selected_request_skill_code,
        }
    )
    return templates.TemplateResponse("requests.html", context)


@router.post("/requests")
def create_edit_request(
    request: Request,
    db: Session = Depends(get_db),
    child_id: str = Form(...),
    skill_code: str = Form(...),
    requested_score: int = Form(...),
    requested_is_prompted: bool = Form(False),
    assessment_date: str = Form(...),
    requested_comment: str = Form(""),
    reason: str = Form(...),
):
    user, response = _require_roles(request, db, {"therapist"})
    if response:
        return response

    allowed_child_ids = {child.id for child in _children_for_therapist(db, user.id)}
    if child_id not in allowed_child_ids:
        _set_flash(request, "Нельзя отправить запрос для неназначенного ребенка.")
        return RedirectResponse(url="/requests", status_code=303)

    reason_clean = reason.strip()
    task = db.get(ABLLSTask, skill_code.strip().upper())
    if not task:
        _set_flash(request, "Навык ABLLS-R не найден.")
        return RedirectResponse(url="/requests", status_code=303)

    existing_assessment = db.execute(
        select(Assessment.id).where(
            Assessment.child_id == child_id,
            Assessment.area == task.code,
        )
    ).scalar_one_or_none()
    if not existing_assessment:
        _set_flash(
            request,
            "Для этого навыка еще нет первичной оценки. Сначала внесите первую оценку в Оценивании.",
        )
        return RedirectResponse(
            url=f"/assessments?child_id={child_id}&section={task.section_code}",
            status_code=303,
        )

    if requested_score < 0 or requested_score > task.max_score:
        _set_flash(request, f"Для {task.code} допустимый новый балл: 0..{task.max_score}.")
        return RedirectResponse(
            url=f"/requests?section={task.section_code}&child_id={child_id}&skill_code={task.code}",
            status_code=303,
        )

    parsed_date = _parse_date(assessment_date)
    if not parsed_date:
        _set_flash(request, "Укажите корректную дату для нового значения.")
        return RedirectResponse(
            url=f"/requests?section={task.section_code}&child_id={child_id}&skill_code={task.code}",
            status_code=303,
        )

    if not reason_clean:
        _set_flash(request, "Заполните причину запроса.")
        return RedirectResponse(
            url=f"/requests?section={task.section_code}",
            status_code=303,
        )

    existing_pending = db.execute(
        select(EditRequest.id).where(
            EditRequest.therapist_id == user.id,
            EditRequest.child_id == child_id,
            EditRequest.area == task.code,
            EditRequest.status == "pending",
        )
    ).scalar_one_or_none()
    if existing_pending:
        _set_flash(request, "По этому навыку уже есть незавершенный запрос.")
        return RedirectResponse(
            url=f"/requests?section={task.section_code}&child_id={child_id}&skill_code={task.code}",
            status_code=303,
        )

    db.add(
        EditRequest(
            child_id=child_id,
            therapist_id=user.id,
            area=task.code,
            reason=reason_clean,
            requested_score=requested_score,
            requested_is_prompted=requested_is_prompted,
            requested_assessment_date=parsed_date,
            requested_comment=requested_comment.strip() or None,
            status="pending",
        )
    )
    mode_label = "с подсказкой" if requested_is_prompted else "самостоятельно"
    _log_action(
        db,
        user.id,
        "create_edit_request",
        (
            f"Запрос на изменение {task.code}: {requested_score}/{task.max_score}, "
            f"{mode_label}, дата {parsed_date.isoformat()}"
        ),
    )
    db.commit()
    _set_flash(request, "Запрос отправлен.")
    return RedirectResponse(
        url=f"/requests?section={task.section_code}&child_id={child_id}&skill_code={task.code}",
        status_code=303,
    )


@router.get("/progress")
def progress(request: Request, db: Session = Depends(get_db)):
    user, response = _require_roles(request, db, {"parent"})
    if response:
        return response

    children = _children_for_parent(db, user.id)
    child_ids = {child.id for child in children}
    selected_child_id = request.query_params.get("child_id")
    if selected_child_id not in child_ids:
        selected_child_id = children[0].id if children else None

    selected_child = next((child for child in children if child.id == selected_child_id), None)
    tasks = _all_ablls_tasks(db)
    task_by_code = {task.code: task for task in tasks}

    latest_by_skill = _latest_assessment_by_skill(db, selected_child_id) if selected_child_id else {}
    section_rows = _section_progress_rows(tasks, latest_by_skill) if selected_child else []

    recent_rows: list[Assessment] = []
    if selected_child:
        recent_rows = db.execute(
            select(Assessment)
            .where(Assessment.child_id == selected_child.id)
            .order_by(Assessment.assessment_date.desc(), Assessment.created_at.desc())
            .limit(80)
        ).scalars().all()

    context = _base_context(request, db)
    context.update(
        {
            "children": children,
            "selected_child": selected_child,
            "selected_child_id": selected_child_id,
            "section_rows": section_rows,
            "recent_assessments": recent_rows,
            "task_by_code": task_by_code,
        }
    )
    return templates.TemplateResponse("progress.html", context)
