from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.core.ablls_catalog import ensure_ablls_catalog
from app.core.config import settings
from app.core.database import Base, SessionLocal, engine
from app.core.runtime_schema import ensure_runtime_schema
from app import models as app_models
from app.routers import auth, pages

app = FastAPI(title="ABLLS-R Tracker Prototype")

app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key,
    same_site="lax",
)

app.mount("/static", StaticFiles(directory="static"), name="static")

app.include_router(pages.router)
app.include_router(auth.router)


@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)
    ensure_runtime_schema(engine)
    with SessionLocal() as db:
        ensure_ablls_catalog(db, "docs/WordTables_Combined.xlsx")
