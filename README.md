# ABLLS-R Tracker Prototype

FastAPI-приложение с серверным рендерингом (`Jinja2`) и SQLite-базой для ведения оценивания по методике ABLLS-R.

## Требования

- Python 3.12+

## Быстрый запуск (Windows PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\python -m pip install -r requirements.txt
Copy-Item .env.example .env
.\.venv\Scripts\uvicorn app.main:app --reload
```

Откройте: `http://127.0.0.1:8000`

## Конфигурация

Проект читает переменные из файла `.env`:

- `SECRET_KEY` (по умолчанию используется dev-ключ)
- `DATABASE_URL` (по умолчанию `sqlite:///./ablls.db`)

Если `.env` отсутствует, приложение запускается со значениями по умолчанию.

## Логика ABLLS-R

- Каталог навыков ABLLS-R автоматически загружается из `docs/WordTables_Combined.xlsx` при старте сервера.
- В базу заполняется таблица `ablls_tasks` (коды навыков, критерии, максимальный балл).
- Оценивание выполняется по конкретному коду навыка (`A1`, `H12`, `Z4` и т.д.) с валидацией диапазона `0..max_score`.
- Отчеты и прогресс считаются по разделам ABLLS-R (`A..Z`, без `O`) на основе последних оценок по каждому навыку.

## Быстрая проверка

- Главная: `GET /` -> `200`
- Регистрация: `GET /auth/register`
- Оценивание: `GET /assessments` (для роли therapist)
- Прогресс: `GET /progress` (для роли parent)
- Отчеты: `GET /reports`
