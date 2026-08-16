from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.db.migration_runner import database_status, init_database
from app.settings import settings


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_database(settings.database_path)
    yield


app = FastAPI(
    title=settings.app_name,
    version="0.2.0",
    description="Backend for Otello NAV Dashboard",
    lifespan=lifespan,
)

origins = [origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "otello-api",
        "environment": settings.app_env,
        "version": "0.2.0",
    }


@app.get("/api/system/database")
def system_database() -> dict:
    return database_status(settings.database_path)


@app.get("/api/dashboard/summary")
def dashboard_summary() -> dict:
    # Midlertidige eksempeldata. Erstattes av NAV-motor og markedsdata i senere faser.
    return {
        "nav_per_share": 24.82,
        "otec_price": 17.20,
        "nav_discount_pct": 30.7,
        "bmob3_price": 31.20,
        "brl_nok": 1.72,
        "estimated_cash_mnok": 112.4,
        "data_status": "demo",
    }
