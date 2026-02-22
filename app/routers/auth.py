from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import hash_password, verify_password
from app.core.database import get_db
from app.models.user import User
from app.routers.pages import templates

router = APIRouter(prefix="/auth", tags=["auth"])

ALLOWED_ROLES = {"admin", "therapist", "parent"}


def _is_valid_email(email: str) -> bool:
    if "@" not in email:
        return False
    local, domain = email.split("@", 1)
    return bool(local) and "." in domain


def _base_context(request: Request, db: Session) -> dict:
    user_id = request.session.get("user_id")
    current_user = db.get(User, user_id) if user_id else None
    flash_message = request.session.pop("flash_success", None)
    return {
        "request": request,
        "current_user": current_user,
        "flash_message": flash_message,
        "role_labels": {
            "admin": "Администратор",
            "therapist": "Терапист",
            "parent": "Родитель",
        },
    }


@router.get("/register")
def register_form(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(
        "auth/register.html",
        {**_base_context(request, db), "errors": [], "form": {}},
    )


@router.post("/register")
def register_user(
    request: Request,
    db: Session = Depends(get_db),
    email: str = Form(...),
    full_name: str = Form(...),
    role: str = Form(...),
    password: str = Form(...),
    password_confirm: str = Form(...),
):
    errors = []
    email = email.strip().lower()
    full_name = full_name.strip()
    role = role.strip().lower()

    if not _is_valid_email(email):
        errors.append("Введите корректный адрес электронной почты.")
    if not full_name:
        errors.append("Укажите имя и фамилию.")
    if role not in ALLOWED_ROLES:
        errors.append("Выберите корректную роль.")
    if len(password) < 8:
        errors.append("Введите не менее 8 символов.")
    if any(char.isspace() for char in password):
        errors.append("Пароль не должен содержать пробелы.")
    if password != password_confirm:
        errors.append("Пароли не совпадают.")

    if errors:
        return templates.TemplateResponse(
            "auth/register.html",
            {**_base_context(request, db), "errors": errors, "form": {
                "email": email,
                "full_name": full_name,
                "role": role,
            }},
            status_code=400,
        )

    user = User(
        email=email,
        full_name=full_name,
        role=role,
        password_hash=hash_password(password),
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return templates.TemplateResponse(
            "auth/register.html",
            {
                **_base_context(request, db),
                "errors": ["Этот email уже зарегистрирован. Войдите в систему."],
                "form": {"email": email, "full_name": full_name, "role": role},
            },
            status_code=400,
        )

    request.session["flash_success"] = "Регистрация прошла успешно. Войдите в систему."

    return RedirectResponse(url="/auth/login", status_code=303)


@router.get("/login")
def login_form(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(
        "auth/login.html",
        {**_base_context(request, db), "errors": [], "form": {}},
    )


@router.post("/login")
def login_user(
    request: Request,
    db: Session = Depends(get_db),
    email: str = Form(...),
    password: str = Form(...),
):
    errors = []
    email = email.strip().lower()
    user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()

    if len(password) < 8:
        errors.append("Введите не менее 8 символов.")
    if any(char.isspace() for char in password):
        errors.append("Пароль не должен содержать пробелы.")
    if not errors and (not user or not verify_password(password, user.password_hash)):
        errors.append("Неверный email или пароль.")

    if errors:
        return templates.TemplateResponse(
            "auth/login.html",
            {**_base_context(request, db), "errors": errors, "form": {"email": email}},
            status_code=400,
        )

    request.session["user_id"] = user.id
    request.session["role"] = user.role

    return RedirectResponse(url="/dashboard", status_code=303)


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/", status_code=303)
