"""R1B isolated diagnostic contracts; no live DB, provider or lifecycle actions."""
import builtins
import importlib.util
import json
import os
from pathlib import Path
import subprocess

import pytest
from sqlalchemy.engine import make_url

from app.db import session
from app.routers.system import health_check

ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = ROOT / "scripts/omi-launcher.ps1"


@pytest.mark.parametrize("value", [
    "postgresql://private_user:db_password@example.test/account?token=private_token",
    "sqlite:///file:private.db?uri=true&password=private_token",
    "sqlite:///relative.db", "sqlite:///:memory:", "sqlite://",
])
def test_url_diagnostic_never_exposes_credentials_or_guesses_file(value):
    result = session._database_target_metadata(make_url(value))
    assert result["path_sha256"] is None
    rendered = json.dumps(result)
    for secret in ("private_user", "db_password", "example.test", "account", "private_token", "relative.db"):
        assert secret not in rendered


def test_absolute_target_fingerprint_without_filesystem_resolution(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("filesystem IO forbidden")
    path = tmp_path / "missing-parent" / "unopened.db"
    url = make_url("sqlite:///" + path.as_posix())
    monkeypatch.setattr(Path, "resolve", forbidden)
    monkeypatch.setattr(Path, "stat", forbidden)
    monkeypatch.setattr(builtins, "open", forbidden)
    result = session._database_target_metadata(url)
    assert result["kind"] == "sqlite_absolute_path"
    assert len(result["path_sha256"]) == 64
    assert str(path) not in json.dumps(result)


def test_health_is_no_connect_no_disk_no_release_hash(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("health attempted IO")
    monkeypatch.setattr(session.engine, "connect", forbidden)
    monkeypatch.setattr(session.engine, "raw_connection", forbidden)
    monkeypatch.setattr(session, "SessionLocal", forbidden)
    monkeypatch.setattr(Path, "read_bytes", forbidden)
    monkeypatch.setattr(Path, "read_text", forbidden)
    monkeypatch.setattr(Path, "resolve", forbidden)
    monkeypatch.setattr(builtins, "open", forbidden)
    first = health_check()["runtime"]["database_binding"]
    second = health_check()["runtime"]["database_binding"]
    assert first == second
    assert first["pid"] == os.getpid()
    assert first["loaded_release_identity"] == "UNATTESTED"
    assert first["database_handle_binding"] == "UNVERIFIED"
    assert first["source_hash_basis"] is None


def test_engine_replacement_and_settings_drift_are_visible(monkeypatch):
    monkeypatch.setattr(session.settings, "database_url", "malformed:db_password")
    assert session.database_binding_metadata()["settings_match_engine_url"] is False
    monkeypatch.setattr(session, "engine", object())
    result = session.database_binding_metadata()
    assert result["engine_object_unchanged"] is False
    assert result["target"] == {"kind": "unknown", "path_sha256": None}
    assert "db_password" not in json.dumps(result)


def powershell(code):
    # Synthetic PowerShell function harness, never a service runner.
    import base64
    encoded = base64.b64encode(code.encode("utf-16-le")).decode("ascii")
    return subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
                          capture_output=True, text=True, timeout=30)


@pytest.mark.parametrize("inventory", ["denied", "partial", "available"])
def test_launcher_unknown_coverage_never_passes_or_leaks_arguments(inventory):
    source = LAUNCHER.read_text("utf-8-sig")
    function = source[source.index("function Get-OmiStopDiagnostic"):source.index('if ($LauncherAction -eq "Diagnose")')]
    mock = {
        "denied": 'throw "private_token"',
        "partial": '[pscustomobject]@{ProcessId=42;ParentProcessId=7;CommandLine=$null}',
        "available": '[pscustomobject]@{ProcessId=42;ParentProcessId=7;CommandLine="C:\\fake-omi\\scripts\\omi-launcher.ps1 private_token";CreationDate="fixture"}',
    }[inventory]
    code = '$ErrorActionPreference="Stop"\n' + function + '\nfunction Get-CimInstance { ' + mock + ' }\n'
    code += 'Get-OmiStopDiagnostic -Root "C:\\fake-omi" -Ports @(1) | ConvertTo-Json -Depth 6'
    result = powershell(code)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["verdict"] == "BLOCKED"
    assert payload["handle_coverage"] == "UNKNOWN"
    assert payload["writers_drained"] is False
    assert payload["graceful_shutdown_proven"] is False
    assert "private_token" not in result.stdout
    if inventory == "denied":
        assert payload["process_inventory"] == "UNKNOWN"
        assert payload["processes_observed"] is None
        assert payload["unclassified_processes"] is None
    if inventory == "partial":
        assert payload["unclassified_processes"] == 1
    if inventory == "available":
        assert payload["repo_candidates"][0]["pid"] == 42


@pytest.mark.parametrize("packaged", [False, True])
def test_diagnose_exits_before_gui_env_and_lifecycle(tmp_path, packaged):
    source = LAUNCHER.read_text("utf-8-sig")
    # Run the actual early branch; any fallthrough fails loudly before UI setup.
    prefix = source[:source.index('Add-Type -AssemblyName System.Windows.Forms')]
    script = tmp_path / "scripts" / "omi-launcher.ps1"
    script.parent.mkdir()
    if packaged:
        (tmp_path / "release-manifest.json").write_text("{}", encoding="utf-8")
    script.write_text(prefix + '\nthrow "UNSAFE_GUI_FALLTHROUGH"\n', encoding="utf-8")
    code = 'function Get-CimInstance { throw "denied" }; & ' + "'" + str(script).replace("'", "''") + "' -LauncherAction Diagnose; exit $LASTEXITCODE"
    result = powershell(code)
    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["lifecycle_actions"] == 0
    assert payload["launcher_mode"] == ("packaged_candidate" if packaged else "source_candidate")
    assert payload["loaded_launcher_identity"] == "UNATTESTED"
    assert not (tmp_path / "logs").exists()
    assert "UNSAFE_GUI_FALLTHROUGH" not in result.stderr


def test_diagnostic_failure_never_falls_through_to_run(tmp_path):
    source = LAUNCHER.read_text("utf-8-sig")
    prefix = source[:source.index('Add-Type -AssemblyName System.Windows.Forms')]
    # A mode filesystem failure remains UNKNOWN; no fallback lifecycle or GUI.
    script = tmp_path / "omi-launcher.ps1"
    script.write_text(prefix + '\nthrow "UNSAFE_GUI_FALLTHROUGH"\n', encoding="utf-8")
    code = 'function Get-CimInstance { throw "denied" }; function Test-Path { throw "private_token" }; & '
    code += "'" + str(script).replace("'", "''") + "' -LauncherAction Diagnose; exit $LASTEXITCODE"
    result = powershell(code)
    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["launcher_mode"] == "UNKNOWN"
    assert "launcher_mode_unavailable" in payload["unknown_reasons"]
    assert "private_token" not in result.stdout


def test_canonical_backup_exact_restore_drift_and_existing_destination_fail_closed(tmp_path, monkeypatch):
    # The retired local WIP ZIP helper was never a production owner. Exercise
    # the schema-maintenance backup owner and the tracked rehearsal path guard.
    import hashlib
    import shutil
    import sqlite3

    spec = importlib.util.spec_from_file_location(
        "r1b_canonical_backup", ROOT / "scripts/backup-omi-sqlite.py",
    )
    backup = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(backup)
    spec = importlib.util.spec_from_file_location(
        "r1b_rehearsal_guard", ROOT / "scripts/omi-r1-backup-supervisor.py",
    )
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    monkeypatch.setattr(guard, "BASE", tmp_path)
    directory = tmp_path / ("r1c-" + "a" * 32)
    directory.mkdir()
    source = guard.checked_path(directory / "source.sqlite3")
    payload = b"\xef\xbb\xbfWIP\r\n\x00exact bytes\n"
    with sqlite3.connect(source) as db:
        db.execute("CREATE TABLE alembic_version(version_num TEXT)")
        db.execute("INSERT INTO alembic_version VALUES ('fixture_revision')")
        db.execute("CREATE TABLE evidence(value BLOB)")
        db.execute("INSERT INTO evidence VALUES (?)", (payload,))
    before = source.read_bytes()
    output = guard.checked_path(directory / "backup.sqlite3")

    def run(destination):
        return backup.backup_sqlite_database(
            source=source, output=guard.checked_path(destination),
            integrity_check="full", max_seconds=10,
        )

    receipt = run(output)
    restored = directory / "independent-restore.sqlite3"
    shutil.copyfile(output, restored)
    with sqlite3.connect(restored.as_uri() + "?mode=ro", uri=True) as db:
        assert db.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
        assert db.execute("SELECT value FROM evidence").fetchone()[0] == payload
    assert receipt["contract_version"] == "omi.sqlite-backup.v1"
    assert receipt["snapshot"]["revision"] == "fixture_revision"
    assert receipt["sha256"] == hashlib.sha256(restored.read_bytes()).hexdigest()
    assert receipt["size_bytes"] == restored.stat().st_size
    assert source.read_bytes() == before
    published = output.read_bytes()
    with pytest.raises(ValueError, match="refusing to overwrite existing backup"):
        run(output)
    assert output.read_bytes() == published
    assert source.read_bytes() == before

    snapshot = backup._database_snapshot
    calls = []

    def mutate_after_source_snapshot(connection):
        observed = snapshot(connection)
        calls.append(observed)
        if len(calls) == 1:
            # A real concurrent revision change between observation and copy.
            with sqlite3.connect(source) as writer:
                writer.execute("UPDATE alembic_version SET version_num = 'parallel_edit'")
        return observed

    monkeypatch.setattr(backup, "_database_snapshot", mutate_after_source_snapshot)
    drift = directory / "drift.sqlite3"
    with pytest.raises(ValueError, match="backup snapshot differs from source"):
        run(drift)
    assert len(calls) == 2
    assert calls[0]["revision"] == "fixture_revision"
    assert calls[1]["revision"] == "parallel_edit"
    assert not drift.exists()
    partial = directory / "drift.sqlite3.partial"
    retained = partial.read_bytes()
    with pytest.raises(ValueError, match="partial backup already exists"):
        run(drift)
    assert partial.read_bytes() == retained
    with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as db:
        assert db.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "parallel_edit"
        assert db.execute("SELECT value FROM evidence").fetchone()[0] == payload
    assert output.read_bytes() == published

    # Rejected paths must fail lexically, before even inspecting the filesystem.
    monkeypatch.setattr(Path, "lstat", lambda *_: pytest.fail("rejected path inspected"))
    for unsafe in (directory / "../../escape.sqlite3", directory / "../escape.sqlite3",
                   directory / ".env", directory / "data/example.db"):
        with pytest.raises(guard.Closed):
            guard.checked_path(unsafe)
