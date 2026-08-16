from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path, PurePosixPath
import shutil
import stat
from typing import BinaryIO, Iterable
import zipfile


@dataclass(frozen=True)
class ZipArchiveInventory:
    archive_size_bytes: int
    uncompressed_size_bytes: int
    entry_count: int
    sha256: str
    entries: tuple[tuple[str, int, int], ...]


def _safe_member_name(name: str) -> str:
    normalized = str(name or "").replace("\\", "/")
    member = PurePosixPath(normalized)
    if not normalized or normalized.startswith("/") or member.is_absolute():
        raise ValueError(f"Unsafe ZIP member path: {name!r}")
    if any(part in {"", ".", ".."} for part in member.parts):
        raise ValueError(f"Unsafe ZIP member path: {name!r}")
    if member.parts and ":" in member.parts[0]:
        raise ValueError(f"Unsafe ZIP member drive path: {name!r}")
    return member.as_posix()


def validate_zip_archive(
    path: Path,
    *,
    max_archive_bytes: int,
    max_uncompressed_bytes: int,
    max_entries: int = 128,
) -> ZipArchiveInventory:
    archive = Path(path)
    archive_size = archive.stat().st_size
    if archive_size <= 0 or archive_size > max_archive_bytes:
        raise ValueError(
            f"ZIP archive size {archive_size} is outside the allowed range 1..{max_archive_bytes}."
        )
    digest = hashlib.sha256()
    with archive.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)

    entries: list[tuple[str, int, int]] = []
    total_uncompressed = 0
    try:
        with zipfile.ZipFile(archive) as bundle:
            infos = bundle.infolist()
            if not infos or len(infos) > max_entries:
                raise ValueError(
                    f"ZIP entry count {len(infos)} is outside the allowed range 1..{max_entries}."
                )
            for info in infos:
                safe_name = _safe_member_name(info.filename)
                unix_mode = (info.external_attr >> 16) & 0xFFFF
                if stat.S_ISLNK(unix_mode):
                    raise ValueError(f"ZIP symlink entries are not allowed: {safe_name}")
                if info.flag_bits & 0x1:
                    raise ValueError(f"Encrypted ZIP entries are not allowed: {safe_name}")
                total_uncompressed += int(info.file_size)
                if total_uncompressed > max_uncompressed_bytes:
                    raise ValueError(
                        "ZIP uncompressed size exceeds the configured safety limit."
                    )
                entries.append((safe_name, int(info.compress_size), int(info.file_size)))
            bad_member = bundle.testzip()
            if bad_member is not None:
                raise ValueError(f"ZIP CRC validation failed for {bad_member}.")
    except zipfile.BadZipFile as exc:
        raise ValueError("Invalid ZIP archive.") from exc

    return ZipArchiveInventory(
        archive_size_bytes=archive_size,
        uncompressed_size_bytes=total_uncompressed,
        entry_count=len(entries),
        sha256=digest.hexdigest(),
        entries=tuple(entries),
    )


def write_bounded_stream(
    chunks: Iterable[bytes],
    destination: Path,
    *,
    max_bytes: int,
) -> tuple[Path, int, str]:
    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_name(f"{target.name}.part")
    digest = hashlib.sha256()
    written = 0
    try:
        with part.open("wb") as handle:
            for chunk in chunks:
                if not chunk:
                    continue
                written += len(chunk)
                if written > max_bytes:
                    raise ValueError("Downloaded archive exceeds the configured size limit.")
                handle.write(chunk)
                digest.update(chunk)
        if written <= 0:
            raise ValueError("Downloaded archive was empty.")
        part.replace(target)
    except Exception:
        part.unlink(missing_ok=True)
        raise
    return target, written, digest.hexdigest()


def extract_zip_member(
    archive_path: Path,
    member_name: str,
    destination: Path,
    *,
    max_bytes: int,
) -> Path:
    safe_name = _safe_member_name(member_name)
    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_name(f"{target.name}.part")
    try:
        with zipfile.ZipFile(archive_path) as bundle:
            info = bundle.getinfo(member_name)
            if info.filename.replace("\\", "/") != safe_name:
                raise ValueError("ZIP member name normalization mismatch.")
            unix_mode = (info.external_attr >> 16) & 0xFFFF
            if stat.S_ISLNK(unix_mode) or info.flag_bits & 0x1:
                raise ValueError(f"Unsafe ZIP member: {safe_name}")
            if info.file_size > max_bytes:
                raise ValueError(f"ZIP member exceeds the configured size limit: {safe_name}")
            written = 0
            with bundle.open(info) as source, part.open("wb") as output:
                while True:
                    chunk = source.read(1024 * 1024)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > max_bytes:
                        raise ValueError(f"ZIP member exceeds the configured size limit: {safe_name}")
                    output.write(chunk)
            if written != info.file_size:
                raise ValueError(f"ZIP member size mismatch: {safe_name}")
        part.replace(target)
    except Exception:
        part.unlink(missing_ok=True)
        raise
    return target


__all__ = [
    "ZipArchiveInventory",
    "extract_zip_member",
    "validate_zip_archive",
    "write_bounded_stream",
]
