from collections import defaultdict
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.templating import Jinja2Templates
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
                "name": task.section_name,
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

    latest_by_skill: dict[str, Assessment] = {}
    for row in rows:
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
        stats["section_name"] = task.section_name
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
    user, response = _require_roles(request, db, {"admin", "therapist", "parent"})
    if response:
        return response

    if user.role == "admin":
        visible_children = db.execute(select(Child).order_by(Child.full_name.asc())).scalars().all()
    elif user.role == "therapist":
        visible_children = _children_for_therapist(db, user.id)
    else:
        visible_children = _children_for_parent(db, user.id)

    selected_child_id = request.query_params.get("child_id")
    visible_child_ids = {child.id for child in visible_children}
    if selected_child_id not in visible_child_ids:
        selected_child_id = visible_children[0].id if visible_children else None

    tasks = _all_ablls_tasks(db)
    task_by_code = {task.code: task for task in tasks}

    selected_child = next((child for child in visible_children if child.id == selected_child_id), None)
    latest_by_skill = _latest_assessment_by_skill(db, selected_child_id) if selected_child_id else {}
    section_rows = _section_progress_rows(tasks, latest_by_skill) if selected_child else []

    recent_rows: list[Assessment] = []
    daily_points: list[dict] = []
    if selected_child:
        recent_rows = db.execute(
            select(Assessment)
            .where(Assessment.child_id == selected_child.id)
            .order_by(Assessment.assessment_date.desc(), Assessment.created_at.desc())
            .limit(80)
        ).scalars().all()

        all_rows = db.execute(
            select(Assessment)
            .where(Assessment.child_id == selected_child.id)
            .order_by(Assessment.assessment_date.asc(), Assessment.created_at.asc())
        ).scalars().all()

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

    context = _base_context(request, db)
    context.update(
        {
            "visible_children": visible_children,
            "selected_child": selected_child,
            "selected_child_id": selected_child_id,
            "section_rows": section_rows,
            "recent_assessments": recent_rows,
            "daily_points": daily_points,
            "task_by_code": task_by_code,
        }
    )
    return templates.TemplateResponse("reports.html", context)


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

    req.status = decision
    req.admin_comment = admin_comment.strip() or None
    req.reviewed_by = user.id
    req.reviewed_at = datetime.now(timezone.utc)
    _log_action(db, user.id, "review_edit_request", f"Запрос {req.id}: {decision}")
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

    section_tasks = [
        task for task in tasks if selected_section and task.section_code == selected_section
    ]

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
        }
    )
    return templates.TemplateResponse("requests.html", context)


@router.post("/requests")
def create_edit_request(
    request: Request,
    db: Session = Depends(get_db),
    child_id: str = Form(...),
    skill_code: str = Form(...),
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

    if not reason_clean:
        _set_flash(request, "Заполните причину запроса.")
        return RedirectResponse(
            url=f"/requests?section={task.section_code}",
            status_code=303,
        )

    db.add(
        EditRequest(
            child_id=child_id,
            therapist_id=user.id,
            area=task.code,
            reason=reason_clean,
            status="pending",
        )
    )
    _log_action(db, user.id, "create_edit_request", f"Запрос на навык ABLLS-R: {task.code}")
    db.commit()
    _set_flash(request, "Запрос отправлен.")
    return RedirectResponse(url=f"/requests?section={task.section_code}", status_code=303)


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
