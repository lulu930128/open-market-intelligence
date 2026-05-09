from fastapi import APIRouter

router = APIRouter()


@router.get("/")
def list_sources():
    return {
        "items": [],
        "message": "Source registry is not implemented yet.",
    }
