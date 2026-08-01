from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys
from typing import Any, Callable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.market.financial_basis_assessment import (  # noqa: E402
    TaiwanFinancialBasisAssessmentPackage,
    basis_assessment_package_hash,
)
from app.market.financial_evidence_package import (  # noqa: E402
    TaiwanFinancialEvidencePackage,
    evidence_package_hash,
)


PackageValidator = Callable[[Any], Any]
PackageHasher = Callable[[Any], str]

PACKAGE_TYPES: dict[str, tuple[PackageValidator, PackageHasher]] = {
    "omi.tw-financial-evidence.v1": (
        TaiwanFinancialEvidencePackage.model_validate,
        evidence_package_hash,
    ),
    "omi.tw-financial-basis-assessment.v1": (
        TaiwanFinancialBasisAssessmentPackage.model_validate,
        basis_assessment_package_hash,
    ),
}


def promote_package_payload(
    payload: dict[str, Any],
    *,
    package_id: str,
    reviewer: str,
    reviewed_at: str,
) -> tuple[dict[str, Any], str, str]:
    package_version = str(payload.get("package_version") or "")
    package_contract = PACKAGE_TYPES.get(package_version)
    if package_contract is None:
        raise ValueError(f"unsupported package_version: {package_version!r}")
    if payload.get("approval_scope") != "clone_only":
        raise ValueError("source package approval_scope must be 'clone_only'")
    if payload.get("review_status") != "approved":
        raise ValueError("source package review_status must be 'approved'")

    validator, hasher = package_contract
    source_package = validator(payload)
    promoted = deepcopy(payload)
    promoted["package_id"] = package_id.strip()
    promoted["approval_scope"] = "production"
    promoted["reviewer"] = reviewer.strip()
    promoted["reviewed_at"] = reviewed_at.strip()
    if not promoted["package_id"]:
        raise ValueError("production package_id is required")
    if not promoted["reviewer"]:
        raise ValueError("production reviewer is required")

    production_package = validator(promoted)
    source_hash = hasher(source_package)
    production_hash = hasher(production_package)
    return promoted, source_hash, production_hash


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Promote an approved clone-only Taiwan financial package into an "
            "auditable production-scope package. No database is modified."
        )
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--package-id", required=True)
    parser.add_argument("--reviewer", required=True)
    parser.add_argument(
        "--reviewed-at",
        required=True,
        help="Timezone-aware ISO 8601 production review timestamp.",
    )
    args = parser.parse_args()

    input_path = args.input.expanduser().resolve()
    output_path = args.output.expanduser().resolve()
    if not input_path.is_file():
        parser.error(f"input package does not exist: {input_path}")
    if output_path.exists():
        parser.error(f"refusing to overwrite existing output: {output_path}")
    if not output_path.parent.is_dir():
        parser.error(f"output directory does not exist: {output_path.parent}")

    try:
        source_payload = json.loads(input_path.read_text(encoding="utf-8"))
        promoted, source_hash, production_hash = promote_package_payload(
            source_payload,
            package_id=args.package_id,
            reviewer=args.reviewer,
            reviewed_at=args.reviewed_at,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))

    output_path.write_text(
        json.dumps(promoted, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "input": str(input_path),
                "output": str(output_path),
                "package_version": promoted["package_version"],
                "package_id": promoted["package_id"],
                "approval_scope": promoted["approval_scope"],
                "source_package_hash": source_hash,
                "production_package_hash": production_hash,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
