from __future__ import annotations

import argparse
import csv
import io
import json
from pathlib import Path, PurePosixPath
import re
import zipfile


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audit raw CUSIP and VALUE shapes in SEC 13F ZIPs.")
    parser.add_argument("archives", nargs="+", type=Path)
    parser.add_argument("--sample-limit", type=int, default=10)
    return parser


def _audit(path: Path, *, sample_limit: int) -> dict:
    counts = {"rows": 0, "invalid_cusip": 0, "invalid_value": 0}
    samples: list[dict[str, str | None]] = []
    with zipfile.ZipFile(path) as archive:
        member = next(
            name
            for name in archive.namelist()
            if PurePosixPath(name).name.upper() == "INFOTABLE.TSV"
        )
        with archive.open(member) as raw:
            rows = csv.DictReader(
                io.TextIOWrapper(raw, encoding="utf-8-sig", newline=""),
                delimiter="\t",
            )
            for row in rows:
                counts["rows"] += 1
                cusip = re.sub(r"\s+", "", str(row.get("CUSIP") or "").strip().upper())
                value = str(row.get("VALUE") or "").strip().replace(",", "")
                invalid_cusip = len(cusip) != 9
                try:
                    int(value)
                    invalid_value = False
                except ValueError:
                    invalid_value = True
                counts["invalid_cusip"] += int(invalid_cusip)
                counts["invalid_value"] += int(invalid_value)
                if (invalid_cusip or invalid_value) and len(samples) < sample_limit:
                    samples.append(
                        {
                            "accession_number": row.get("ACCESSION_NUMBER"),
                            "issuer_name": row.get("NAMEOFISSUER"),
                            "cusip": row.get("CUSIP"),
                            "value": row.get("VALUE"),
                        }
                    )
    return {"archive": str(path.resolve()), **counts, "samples": samples}


def main() -> int:
    args = _parser().parse_args()
    result = [_audit(path, sample_limit=max(args.sample_limit, 0)) for path in args.archives]
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
