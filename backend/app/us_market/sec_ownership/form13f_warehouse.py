from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import shutil
from typing import Any, Iterable, Iterator
import zipfile

import duckdb

from .archive import extract_zip_member, validate_zip_archive
from .form13f import table_members


WAREHOUSE_SCHEMA_VERSION = "omi.sec.13f.parquet.v3"


@dataclass(frozen=True)
class Form13FParquetBuild:
    holdings_path: Path
    holdings_sha256: str
    file_size_bytes: int
    row_count: int
    distinct_cusip_count: int
    total_reported_value_usd_text: str
    invalid_cusip_count: int
    invalid_value_count: int


def _sql_literal(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _configured_compression(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized not in {"zstd", "snappy", "gzip", "lz4_raw", "uncompressed"}:
        raise ValueError(f"Unsupported 13F Parquet compression: {value!r}")
    return normalized


def build_13f_holdings_parquet(
    *,
    archive_path: Path,
    output_path: Path,
    staging_dir: Path,
    dataset_release_id: int,
    period_key: str,
    source_sha256: str,
    max_archive_bytes: int,
    max_uncompressed_bytes: int,
    min_free_space_bytes: int,
    compression: str = "zstd",
) -> Form13FParquetBuild:
    inventory = validate_zip_archive(
        archive_path,
        max_archive_bytes=max_archive_bytes,
        max_uncompressed_bytes=max_uncompressed_bytes,
    )
    if inventory.sha256 != source_sha256:
        raise ValueError("13F source archive hash changed after discovery.")
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    disk = shutil.disk_usage(destination.parent)
    required_headroom = min_free_space_bytes + inventory.uncompressed_size_bytes
    if disk.free < required_headroom:
        raise ValueError(
            "Insufficient free space for 13F staging plus the configured safety headroom."
        )

    staging = Path(staging_dir)
    staging.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path) as archive:
        members = table_members(archive)
    info_path = extract_zip_member(
        archive_path,
        members["INFOTABLE"],
        staging / "INFOTABLE.tsv",
        max_bytes=max_uncompressed_bytes,
    )
    submission_path = extract_zip_member(
        archive_path,
        members["SUBMISSION"],
        staging / "SUBMISSION.tsv",
        max_bytes=max_uncompressed_bytes,
    )
    temporary = destination.with_name(f"{destination.name}.part")
    temporary.unlink(missing_ok=True)
    compression_value = _configured_compression(compression)

    input_sql = _sql_literal(info_path.resolve())
    submission_sql = _sql_literal(submission_path.resolve())
    output_sql = _sql_literal(temporary.resolve())
    source_hash_sql = _sql_literal(source_sha256)
    period_sql = _sql_literal(period_key)
    sql = f"""
        COPY (
          WITH submissions AS (
            SELECT
              trim(ACCESSION_NUMBER)::VARCHAR AS accession_number,
              try_strptime(trim(FILING_DATE), '%d-%b-%Y')::DATE AS filing_date
            FROM read_csv(
              {submission_sql},
              delim='\t', header=true, all_varchar=true, strict_mode=true,
              null_padding=false, ignore_errors=false, encoding='utf-8'
            )
          )
          SELECT
            {int(dataset_release_id)}::BIGINT AS dataset_release_id,
            {period_sql}::VARCHAR AS period_key,
            {source_hash_sql}::VARCHAR AS source_sha256,
            trim(i.ACCESSION_NUMBER)::VARCHAR AS accession_number,
            s.filing_date,
            try_cast(trim(i.INFOTABLE_SK) AS BIGINT) AS infotable_sk,
            row_number() OVER ()::BIGINT AS source_row_sequence,
            trim(i.NAMEOFISSUER)::VARCHAR AS issuer_name,
            trim(i.TITLEOFCLASS)::VARCHAR AS title_of_class,
            trim(i.CUSIP)::VARCHAR AS cusip_raw_text,
            CASE
              WHEN length(upper(regexp_replace(trim(i.CUSIP), '\\s+', '', 'g'))) = 9
                THEN upper(regexp_replace(trim(i.CUSIP), '\\s+', '', 'g'))
              ELSE NULL
            END::VARCHAR AS cusip,
            nullif(trim(i.FIGI), '')::VARCHAR AS filed_figi,
            trim(i.VALUE)::VARCHAR AS reported_value_raw_text,
            try_cast(replace(trim(i.VALUE), ',', '') AS DECIMAL(38, 0)) AS reported_value_raw,
            CASE
              WHEN s.filing_date >= DATE '2023-01-03' THEN 'usd'
              WHEN s.filing_date IS NOT NULL THEN 'usd_thousands'
              ELSE NULL
            END::VARCHAR AS reported_value_unit,
            (
              try_cast(replace(trim(i.VALUE), ',', '') AS DECIMAL(38, 0))
              * CASE WHEN s.filing_date < DATE '2023-01-03' THEN 1000 ELSE 1 END
            )::DECIMAL(38, 0) AS reported_value_usd,
            trim(i.SSHPRNAMT)::VARCHAR AS shares_or_principal_text,
            try_cast(replace(trim(i.SSHPRNAMT), ',', '') AS DECIMAL(38, 0)) AS shares_or_principal,
            upper(trim(i.SSHPRNAMTTYPE))::VARCHAR AS shares_or_principal_type,
            nullif(upper(trim(i.PUTCALL)), '')::VARCHAR AS put_call,
            upper(trim(i.INVESTMENTDISCRETION))::VARCHAR AS investment_discretion,
            nullif(trim(i.OTHERMANAGER), '')::VARCHAR AS other_manager_refs,
            trim(i.VOTING_AUTH_SOLE)::VARCHAR AS voting_authority_sole_text,
            try_cast(replace(trim(i.VOTING_AUTH_SOLE), ',', '') AS DECIMAL(38, 0)) AS voting_authority_sole,
            trim(i.VOTING_AUTH_SHARED)::VARCHAR AS voting_authority_shared_text,
            try_cast(replace(trim(i.VOTING_AUTH_SHARED), ',', '') AS DECIMAL(38, 0)) AS voting_authority_shared,
            trim(i.VOTING_AUTH_NONE)::VARCHAR AS voting_authority_none_text,
            try_cast(replace(trim(i.VOTING_AUTH_NONE), ',', '') AS DECIMAL(38, 0)) AS voting_authority_none,
            CASE
              WHEN s.filing_date IS NULL
                THEN 'US13F000_missing_filing_date'
              WHEN length(upper(regexp_replace(trim(i.CUSIP), '\\s+', '', 'g'))) <> 9
                THEN 'US13F001_invalid_cusip'
              WHEN try_cast(replace(trim(i.VALUE), ',', '') AS DECIMAL(38, 0)) IS NULL
                THEN 'US13F002_invalid_reported_value'
              WHEN try_cast(replace(trim(i.SSHPRNAMT), ',', '') AS DECIMAL(38, 0)) IS NULL
                THEN 'US13F003_invalid_shares_or_principal'
              ELSE NULL
            END::VARCHAR AS issue_code,
            sha256(concat_ws('|',
              trim(i.ACCESSION_NUMBER), trim(i.INFOTABLE_SK), trim(i.NAMEOFISSUER),
              trim(i.TITLEOFCLASS), trim(i.CUSIP), trim(i.FIGI), trim(i.VALUE), trim(i.SSHPRNAMT),
              trim(i.SSHPRNAMTTYPE), trim(i.PUTCALL), trim(i.INVESTMENTDISCRETION),
              trim(i.OTHERMANAGER), trim(i.VOTING_AUTH_SOLE), trim(i.VOTING_AUTH_SHARED),
              trim(i.VOTING_AUTH_NONE)
            ))::VARCHAR AS raw_row_hash
          FROM read_csv(
            {input_sql},
            delim='\t', header=true, all_varchar=true, strict_mode=true,
            null_padding=false, ignore_errors=false, encoding='utf-8'
          ) i
          LEFT JOIN submissions s ON s.accession_number = trim(i.ACCESSION_NUMBER)
        ) TO {output_sql} (
          FORMAT parquet,
          COMPRESSION {compression_value},
          ROW_GROUP_SIZE 100000,
          PARQUET_VERSION 'V2',
          KV_METADATA {{
            contract_version: '{WAREHOUSE_SCHEMA_VERSION}',
            period_key: {period_sql},
            source_sha256: {source_hash_sql}
          }}
        )
    """
    connection = duckdb.connect(config={"threads": 1})
    try:
        connection.execute(sql)
        summary = connection.execute(
            """
            SELECT
              count(*)::BIGINT,
              count(DISTINCT cusip)::BIGINT,
              coalesce(sum(reported_value_usd), 0)::VARCHAR,
              count(*) FILTER (WHERE issue_code = 'US13F001_invalid_cusip')::BIGINT,
              count(*) FILTER (
                WHERE reported_value_raw IS NULL OR reported_value_unit IS NULL
              )::BIGINT
            FROM read_parquet(?)
            """,
            [str(temporary.resolve())],
        ).fetchone()
    finally:
        connection.close()
        info_path.unlink(missing_ok=True)
        submission_path.unlink(missing_ok=True)
    if summary is None:
        temporary.unlink(missing_ok=True)
        raise ValueError("13F Parquet validation did not return a summary row.")
    if int(summary[4]):
        temporary.unlink(missing_ok=True)
        raise ValueError(
            "13F Parquet contains invalid reported-value rows; release not promoted."
        )
    temporary.replace(destination)
    return Form13FParquetBuild(
        holdings_path=destination,
        holdings_sha256=_sha256_file(destination),
        file_size_bytes=destination.stat().st_size,
        row_count=int(summary[0]),
        distinct_cusip_count=int(summary[1]),
        total_reported_value_usd_text=str(summary[2]),
        invalid_cusip_count=int(summary[3]),
        invalid_value_count=int(summary[4]),
    )


def query_13f_parquet(
    paths: Iterable[Path],
    sql: str,
    parameters: Iterable[Any] = (),
) -> list[dict[str, Any]]:
    resolved = [str(Path(path).resolve()) for path in paths]
    if not resolved:
        return []
    connection = duckdb.connect(config={"threads": 1})
    try:
        path_list = "[" + ",".join(_sql_literal(path) for path in resolved) + "]"
        connection.execute(
            f"CREATE TEMP VIEW holdings AS SELECT * FROM read_parquet({path_list}, union_by_name=true)"
        )
        cursor = connection.execute(sql, list(parameters))
        columns = [item[0] for item in cursor.description]
        return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]
    finally:
        connection.close()


def query_13f_parquet_context(
    paths: Iterable[Path],
    sql: str,
    *,
    identifier_mappings: Iterable[tuple[str, str]] = (),
    filing_context: Iterable[tuple[str, int, int, str, str]] = (),
    parameters: Iterable[Any] = (),
) -> list[dict[str, Any]]:
    resolved = [str(Path(path).resolve()) for path in paths]
    if not resolved:
        return []
    connection = duckdb.connect(config={"threads": 1})
    try:
        path_list = "[" + ",".join(_sql_literal(path) for path in resolved) + "]"
        connection.execute(
            f"CREATE TEMP VIEW holdings AS SELECT * FROM read_parquet({path_list}, union_by_name=true)"
        )
        connection.execute(
            "CREATE TEMP TABLE identifier_map (cusip VARCHAR PRIMARY KEY, symbol VARCHAR NOT NULL)"
        )
        mappings = list(identifier_mappings)
        if mappings:
            connection.executemany(
                "INSERT INTO identifier_map VALUES (?, ?)",
                mappings,
            )
        connection.execute(
            """
            CREATE TEMP TABLE filing_context (
              accession_number VARCHAR PRIMARY KEY,
              manager_id BIGINT NOT NULL,
              dataset_release_id BIGINT NOT NULL,
              report_period VARCHAR NOT NULL,
              effective_status VARCHAR NOT NULL
            )
            """
        )
        filings = list(filing_context)
        if filings:
            connection.executemany(
                "INSERT INTO filing_context VALUES (?, ?, ?, ?, ?)",
                filings,
            )
        cursor = connection.execute(sql, list(parameters))
        columns = [item[0] for item in cursor.description]
        return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]
    finally:
        connection.close()


def iter_13f_parquet_context(
    paths: Iterable[Path],
    sql: str,
    *,
    identifier_mappings: Iterable[tuple[str, str]] = (),
    filing_context: Iterable[tuple[str, int, int, str, str]] = (),
    parameters: Iterable[Any] = (),
    fetch_size: int = 10_000,
    memory_limit: str | None = None,
    temp_directory: Path | None = None,
) -> Iterator[dict[str, Any]]:
    """Stream a bounded DuckDB result without materializing it in Python."""
    if fetch_size < 1:
        raise ValueError("fetch_size must be positive.")
    resolved = [str(Path(path).resolve()) for path in paths]
    if not resolved:
        return
    config: dict[str, Any] = {"threads": 1}
    if memory_limit:
        config["memory_limit"] = memory_limit
    temp_root = Path(temp_directory) if temp_directory is not None else None
    if temp_root is not None:
        temp_root.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect(config=config)
    try:
        if temp_root is not None:
            connection.execute(f"SET temp_directory = {_sql_literal(temp_root.resolve())}")
        path_list = "[" + ",".join(_sql_literal(path) for path in resolved) + "]"
        connection.execute(
            f"CREATE TEMP VIEW holdings AS SELECT * FROM read_parquet({path_list}, union_by_name=true)"
        )
        connection.execute(
            "CREATE TEMP TABLE identifier_map (cusip VARCHAR PRIMARY KEY, symbol VARCHAR NOT NULL)"
        )
        mappings = list(identifier_mappings)
        if mappings:
            connection.executemany(
                "INSERT INTO identifier_map VALUES (?, ?)",
                mappings,
            )
        connection.execute(
            """
            CREATE TEMP TABLE filing_context (
              accession_number VARCHAR PRIMARY KEY,
              manager_id BIGINT NOT NULL,
              dataset_release_id BIGINT NOT NULL,
              report_period VARCHAR NOT NULL,
              effective_status VARCHAR NOT NULL
            )
            """
        )
        filings = list(filing_context)
        if filings:
            connection.executemany(
                "INSERT INTO filing_context VALUES (?, ?, ?, ?, ?)",
                filings,
            )
        cursor = connection.execute(sql, list(parameters))
        columns = [item[0] for item in cursor.description]
        while batch := cursor.fetchmany(fetch_size):
            for row in batch:
                yield dict(zip(columns, row, strict=True))
    finally:
        connection.close()


__all__ = [
    "Form13FParquetBuild",
    "WAREHOUSE_SCHEMA_VERSION",
    "build_13f_holdings_parquet",
    "iter_13f_parquet_context",
    "query_13f_parquet",
    "query_13f_parquet_context",
]
