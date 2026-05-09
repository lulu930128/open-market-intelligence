from fastapi import APIRouter

router = APIRouter()


@router.get("/premarket")
def get_premarket_report():
    return {
        "report_type": "premarket",
        "content": "Premarket report is not generated yet.",
    }


@router.get("/aftermarket")
def get_aftermarket_report():
    return {
        "report_type": "aftermarket",
        "content": "Aftermarket report is not generated yet.",
    }
