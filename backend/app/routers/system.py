import sys

from fastapi import APIRouter

from app.config import PROJECT_ROOT, settings

router = APIRouter()


@router.get("/health")
def health_check():
    return {
        "status": "ok",
        "app_name": settings.app_name,
        "environment": settings.app_env,
        "runtime": {
            "project_root": str(PROJECT_ROOT),
            "backend_dir": str(PROJECT_ROOT / "backend"),
            "python_executable": sys.executable,
            "python_version": sys.version.split()[0],
        },
    }
