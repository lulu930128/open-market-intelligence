"""Configured schema/head checks use only disposable SQLite metadata."""
import sqlite3
from pathlib import Path
import sys

import pytest

from test_schema_maintenance import maintenance, database, observed_runtime
from app.db import migrations
from test_owned_lifecycle_convergence import CS_SETUP
from test_runtime_launcher_recovery import _run_isolated_launcher


@pytest.mark.parametrize("revision,upgrade,expected", [
    ("HEAD", False, True), ("HEAD", True, False),
    ("20261009_0092", False, False), ("20261009_0092", True, True),
    ("unknown", False, False), ("unknown", True, False),
])
def test_start_and_schema_upgrade_have_distinct_pre_stop_gates(database, revision, upgrade, expected):
    with sqlite3.connect(database) as db:
        db.execute("UPDATE alembic_version SET version_num=?", (
            migrations.get_head_revision() if revision == "HEAD" else revision,))
    before = database.read_bytes()
    proof = maintenance.start_compatibility(database_url=f"sqlite:///{database.as_posix()}",
                                           lock_path=database.parent / "schema.lock", upgrade=upgrade)
    assert proof["compatible"] is expected
    assert database.read_bytes() == before
    assert not (database.parent / "schema.lock").exists()


@pytest.mark.parametrize("mismatch", ["database", "lock", "live_binding"])
def test_wrong_configured_or_live_target_rejected_before_stop(database, monkeypatch, mismatch):
    observed = observed_runtime(database)
    if mismatch == "live_binding":
        observed["health"]["runtime"]["database_binding"]["target"]["path_sha256"] = "wrong"
    monkeypatch.setattr(maintenance, "read_runtime", lambda _: observed)
    before = database.read_bytes()
    proof = maintenance.start_compatibility(database_url=f"sqlite:///{database.as_posix()}",
        lock_path=database.parent / "schema.lock", upgrade=True,
        database=database.with_name("wrong.db") if mismatch == "database" else database,
        schema_lock=database.parent / ("wrong.lock" if mismatch == "lock" else "schema.lock"),
        base_url="http://127.0.0.1:1")
    assert not proof["compatible"]
    assert database.read_bytes() == before


def test_missing_db_is_never_created(tmp_path):
    path = tmp_path / "missing.db"
    assert not maintenance.start_compatibility(database_url=f"sqlite:///{path.as_posix()}",
        lock_path=tmp_path / "schema.lock")["compatible"]
    assert not path.exists()


def test_upgrade_selector_returns_only_configured_readonly_target(database):
    before = database.read_bytes()
    lock = database.parent / "schema.lock"
    proof = maintenance.start_compatibility(database_url=f"sqlite:///{database.as_posix()}",
                                            lock_path=lock, upgrade=True)
    assert proof["compatible"] is True
    assert proof["configured_target"] == {"database_path": str(database), "schema_lock_path": str(lock)}
    assert database.read_bytes() == before and not lock.exists()
    normal = maintenance.start_compatibility(database_url=f"sqlite:///{database.as_posix()}", lock_path=lock)
    assert normal["configured_target"] is None


@pytest.mark.parametrize("target", ["relative", "wrong-name", "noncanonical"])
def test_upgrade_selector_refuses_unknown_lock_target(database, target):
    lock = {"relative": Path("schema.lock"), "wrong-name": database.parent / "other.lock",
            "noncanonical": database.parent / ".." / database.parent.name / "schema.lock"}[target]
    proof = maintenance.start_compatibility(database_url=f"sqlite:///{database.as_posix()}",
                                            lock_path=lock, upgrade=True)
    assert proof["compatible"] is False and not proof.get("configured_target")


@pytest.mark.parametrize("present", [True, False])
def test_native_upgrade_selector_never_requires_caller_paths(tmp_path, present):
    (tmp_path / "scripts").mkdir()
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv/pyvenv.cfg").write_text(f"executable = {sys.executable}\n")
    (tmp_path / "scripts/omi-schema-maintenance.py").write_text(
        'import json, sys\nassert sys.argv[1:] == ["CheckStart", "--upgrade"]\n'
        'print(json.dumps({"contract":"omi.start-compatibility.v1","compatible":True,'
        '"configured_target":{"database_path":"fixture.db","schema_lock_path":"schema.lock"}}))\n'
        f'raise SystemExit({0 if present else 2})\n')
    check = r'''
$accepted=$false
try {
    $proof=[Omi.OwnedShutdown.ProductionSession]::ReadStartCompatibility('ROOT','','','',$true)|ConvertFrom-Json
    $accepted=$proof.configured_target.database_path -eq 'fixture.db'
} catch {if ($_.Exception.Message -notmatch 'RESTART_COMPATIBILITY_NOT_ATTESTED') {throw}}
if ($accepted -ne EXPECTED) {throw 'CONFIGURED_SELECTOR_BYPASSED'}
'''
    _run_isolated_launcher(tmp_path, CS_SETUP + check.replace("ROOT", str(tmp_path)).replace("EXPECTED", "$true" if present else "$false"))


@pytest.mark.parametrize("success", [True, False])
def test_native_fixed_inspector_drains_stderr_and_checks_exit(tmp_path, success):
    (tmp_path / "scripts").mkdir()
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv/pyvenv.cfg").write_text(f"executable = {sys.executable}\n")
    (tmp_path / "scripts/omi-schema-maintenance.py").write_text(
        'import json, sys\nassert sys.argv[1] == "CheckStart"\n'
        'sys.stderr.write("fixture diagnostics\\n")\n'
        'print(json.dumps({"contract":"omi.start-compatibility.v1","compatible":True}))\n'
        f'raise SystemExit({0 if success else 2})\n')
    check = r'''
$accepted=$false
try {
    $proof=[Omi.OwnedShutdown.ProductionSession]::ReadStartCompatibility('ROOT','','','',$false)|ConvertFrom-Json
    $accepted=$proof.compatible
} catch {if ($_.Exception.Message -notmatch 'RESTART_COMPATIBILITY_NOT_ATTESTED') {throw}}
if ($accepted -ne EXPECTED) {throw 'INSPECTOR_EXIT_NOT_CHECKED'}
'''
    _run_isolated_launcher(tmp_path, CS_SETUP + check.replace("ROOT", str(tmp_path)).replace("EXPECTED", "$true" if success else "$false"))
