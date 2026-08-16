from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from app.us_market.errors import USMarketDataFetchError
from app.us_market.sec_ownership.form13f import normalize_cusip

from ._http import post as provider_post


PROVIDER_NAME = "openfigi"
OPENFIGI_MAPPING_URL = "https://api.openfigi.com/v3/mapping"


@dataclass(frozen=True)
class OpenFigiMappingJob:
    identifier_type: str
    identifier_value: str

    def request_payload(self) -> dict[str, str]:
        return {"idType": self.identifier_type, "idValue": self.identifier_value}


def cusip_mapping_job(value: str) -> OpenFigiMappingJob:
    cusip = normalize_cusip(value)
    if cusip is None:
        raise ValueError(f"Invalid CUSIP value: {value!r}")
    identifier_type = "ID_CINS" if cusip[0].isalpha() else "ID_CUSIP"
    return OpenFigiMappingJob(identifier_type=identifier_type, identifier_value=cusip)


def fetch_openfigi_mappings(
    jobs: Iterable[OpenFigiMappingJob],
    *,
    api_key: str | None,
    timeout_seconds: int,
) -> tuple[list[dict[str, Any]], str]:
    normalized = tuple(jobs)
    request_limit = 100 if str(api_key or "").strip() else 5
    if not normalized or len(normalized) > request_limit:
        raise ValueError(
            f"OpenFIGI mapping request must contain 1..{request_limit} jobs for the current credential mode."
        )
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if str(api_key or "").strip():
        headers["X-OPENFIGI-APIKEY"] = str(api_key).strip()
    response = provider_post(
        OPENFIGI_MAPPING_URL,
        provider=PROVIDER_NAME,
        resource="sec_13f_identifier_mapping",
        target=f"jobs:{len(normalized)}",
        timeout_seconds=max(int(timeout_seconds), 1),
        headers=headers,
        json=[job.request_payload() for job in normalized],
    )
    payload = response.json()
    if not isinstance(payload, list) or len(payload) != len(normalized):
        raise USMarketDataFetchError(
            "OpenFIGI mapping response did not preserve the request job cardinality."
        )
    if not all(isinstance(item, dict) for item in payload):
        raise USMarketDataFetchError("OpenFIGI mapping response contained an invalid result.")
    return payload, OPENFIGI_MAPPING_URL


__all__ = [
    "OPENFIGI_MAPPING_URL",
    "OpenFigiMappingJob",
    "cusip_mapping_job",
    "fetch_openfigi_mappings",
]
