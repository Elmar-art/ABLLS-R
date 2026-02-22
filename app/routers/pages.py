from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.user import User

router = APIRouter()
templates = Jinja2Templates(directory="templates")


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
        "role_labels": {
            "admin": "Администратор",
            "therapist": "Терапист",
            "parent": "Родитель",
        },
    }


def _require_roles(request: Request, db: Session, allowed_roles: set[str]):
    user = _current_user(request, db)
    if not user:
        request.session["flash_success"] = "Сначала войдите в систему."
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


@router.get("/")
def index(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse("index.html", _base_context(request, db))


@router.get("/dashboard")
def dashboard(request: Request, db: Session = Depends(get_db)):
    _, response = _require_roles(request, db, {"admin", "therapist", "parent"})
    if response:
        return response
    return templates.TemplateResponse("dashboard.html", _base_context(request, db))


@router.get("/children")
def children(request: Request, db: Session = Depends(get_db)):
    _, response = _require_roles(request, db, {"admin", "therapist"})
    if response:
        return response
    return templates.TemplateResponse("children.html", _base_context(request, db))


@router.get("/assessments")
def assessments(request: Request, db: Session = Depends(get_db)):
    _, response = _require_roles(request, db, {"therapist"})
    if response:
        return response
    return templates.TemplateResponse("assessments.html", _base_context(request, db))


@router.get("/reports")
def reports(request: Request, db: Session = Depends(get_db)):
    _, response = _require_roles(request, db, {"admin", "therapist", "parent"})
    if response:
        return response
    return templates.TemplateResponse("reports.html", _base_context(request, db))


@router.get("/history")
def history(request: Request, db: Session = Depends(get_db)):
    _, response = _require_roles(request, db, {"admin"})
    if response:
        return response
    return templates.TemplateResponse("history.html", _base_context(request, db))


@router.get("/admin/users")
def admin_users(request: Request, db: Session = Depends(get_db)):
    _, response = _require_roles(request, db, {"admin"})
    if response:
        return response
    return templates.TemplateResponse("admin/users.html", _base_context(request, db))


@router.get("/admin/edit-requests")
def admin_edit_requests(request: Request, db: Session = Depends(get_db)):
    _, response = _require_roles(request, db, {"admin"})
    if response:
        return response
    return templates.TemplateResponse("admin/edit_requests.html", _base_context(request, db))


@router.get("/requests")
def edit_requests(request: Request, db: Session = Depends(get_db)):
    _, response = _require_roles(request, db, {"therapist"})
    if response:
        return response
    return templates.TemplateResponse("requests.html", _base_context(request, db))


@router.get("/progress")
def progress(request: Request, db: Session = Depends(get_db)):
    _, response = _require_roles(request, db, {"parent"})
    if response:
        return response
    return templates.TemplateResponse("progress.html", _base_context(request, db))
