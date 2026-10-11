"""R1C offline fault rehearsal: no production SQL, providers or service lifecycle."""
import ast
import ctypes as C
import importlib.util
import json
from pathlib import Path
import os
import time

import pytest

ROOT = Path(__file__).absolute().parents[2]


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


supervisor = load("r1c_supervisor", "omi-r1-backup-supervisor.py")
owners = load("r1c_owners", "omi-r1-resource-owners.py")
EXPECTED = {
    "success": None, "verify_delay": None, "stall": "COPY_STALL", "deadline": "TOTAL_DEADLINE",
    "identity_loss": "IDENTITY_UNKNOWN", "missing_receipt": "MISSING_OR_INVALID_RECEIPT",
    "bogus_success": "PUBLISH_STATE_INVALID", "existing_partial": "EXISTING_OUTPUT_OR_PARTIAL",
    "journal_existing": "EXISTING_OUTPUT_OR_PARTIAL", "orphan": "ORPHAN_OR_UNCLASSIFIED_CHILD",
    "verify_deadline": "TOTAL_DEADLINE", "independent_deadline": "TOTAL_DEADLINE",
    "source_mutation": "SOURCE_CHANGED", "wal_mutation": "SOURCE_CHANGED",
    "corrupt_output": "CHILD_FAILED", "quick_check_extra": "INDEPENDENT_CHECK_FAILED",
    **{"forged_" + key: "RECEIPT_MISMATCH" for key in ("sha", "size", "revision", "source", "output", "contract", "counts")},
}


@pytest.fixture(scope="module")
def matrix():
    rows = []
    yield rows
    # Unique immutable evidence per run, including failures. Never overwrite history.
    stamp = str(time.time_ns())
    file = ROOT / "docs/exec-plans/active/us-r0-r5-20261009" / ("R1C-matrix-" + stamp + ".json")
    with file.open("x", encoding="utf-8") as f:
        json.dump(rows, f, indent=2)


@pytest.mark.parametrize("scenario", supervisor.SCENARIOS)
def test_real_fault_matrix(scenario, matrix):
    result = supervisor.rehearse(scenario)
    matrix.append(result)
    assert result.get("failure") == EXPECTED[scenario], result
    assert result["status"] == ("PASS" if EXPECTED[scenario] is None else "FAIL_CLOSED")
    assert all(row["cleanup_confirmed"] for row in result["children"])
    assert all(row["final_job_pids"] == [] for row in result["children"])
    assert result["elapsed_including_cleanup_seconds"] < 15
    directory = Path(result["directory"])
    if scenario in {"identity_loss", "orphan"}:
        assert result["manual_review"]
        assert all(not row["cancelled"] for row in result["children"])
    if scenario == "orphan":
        assert result["children"][0]["descendant_identities"]
    if scenario in {"stall", "deadline"}:
        assert result["children"][0]["cancelled"]
        assert (directory / "backup.sqlite3.partial").read_bytes() == b"owned partial"
        assert (directory / "backup.sqlite3.partial-journal").read_bytes() == b"owned journal"
    if scenario in {"existing_partial", "journal_existing"}:
        suffix = ".partial" if scenario == "existing_partial" else ".partial-journal"
        assert not result["children"]
        assert (directory / ("backup.sqlite3" + suffix)).read_bytes() == b"preserve exactly"
    if scenario in {"success", "verify_delay"}:
        assert result["children"][0]["copy_complete"]
        assert result["independent"]["quick_check"] == [["ok"]]
        assert result["independent"]["sha256"] == supervisor.digest(directory / "backup.sqlite3")
        assert result["independent"]["snapshot"]["counts"] == {"tw_financial_filing": 1}
    if scenario == "verify_deadline":
        assert result["children"][0]["copy_complete"]
        assert (directory / "backup.sqlite3.partial").is_file()
        assert not (directory / "backup.sqlite3").exists()
    if scenario == "independent_deadline":
        assert result["children"][-1]["phase"] == "verify"
    if scenario == "source_mutation":
        before = result["source_before"][0]
        after = supervisor.fingerprint(directory / "source.sqlite3")[0]
        assert before[1:3] == after[1:3]  # Same size AND mtime cannot hide mutation.
        assert before[3] != after[3]


@pytest.mark.parametrize("value", [
    ROOT / "data/open_market_intelligence.db",
    ROOT / "data/open_market_intelligence.db-wal",
    ROOT / "data/open_market_intelligence.db-shm",
    ROOT / ".tmp/g5a-preflight-20261009/backup/configured-canonical-20261009.sqlite3.partial",
    ROOT / ".tmp/g5a-preflight-20261009/backup/configured-canonical-20261009.sqlite3.partial-journal",
    ROOT / ".tmp/us-r0-r5-20261009/r1c-not-uuid/source.sqlite3",
])
def test_production_deny_before_metadata(monkeypatch, value):
    def forbidden(*args, **kwargs):
        pytest.fail("denied path caused metadata access")
    monkeypatch.setattr(Path, "lstat", forbidden)
    with pytest.raises(supervisor.Closed):
        supervisor.checked_path(value)


def test_retry_preserves_previous_run():
    result = supervisor.rehearse("stall")
    directory = Path(result["directory"])
    partial = directory / "backup.sqlite3.partial"
    before = partial.read_bytes()
    # Previous report is also immutable; reject without launching another child.
    with pytest.raises(FileExistsError):
        supervisor.supervise(directory, directory / "source.sqlite3", directory / "backup.sqlite3")
    assert partial.read_bytes() == before
    assert len(list(directory.glob("copy.json"))) == 1


def test_hardlink_rejected():
    directory = supervisor.fresh_fixture()
    alias = directory / "alias"
    os.link(directory / "source.sqlite3", alias)
    with pytest.raises(supervisor.Closed, match="HARDLINK_DENIED"):
        supervisor.checked_path(alias)


@pytest.mark.parametrize("suffix", ["-wal", "-shm"])
def test_existing_sidecar_content_mutation_even_with_stable_metadata(suffix):
    directory = supervisor.fresh_fixture()
    source = directory / "source.sqlite3"
    sidecar = Path(str(source) + suffix)
    sidecar.write_bytes(b"before")
    s = sidecar.stat()
    before = supervisor.fingerprint(source)
    sidecar.write_bytes(b"after!")
    os.utime(sidecar, ns=(s.st_atime_ns, s.st_mtime_ns))
    after = supervisor.fingerprint(source)
    index = 1 if suffix == "-wal" else 2
    assert before[index][1:3] == after[index][1:3]
    assert before[index][3] != after[index][3]


@pytest.mark.parametrize("budget", [0, -1, float("inf"), float("nan"), 31])
def test_invalid_budget_cannot_launch(monkeypatch, budget):
    directory = supervisor.fresh_fixture()
    monkeypatch.setattr(supervisor.subprocess, "Popen", lambda *a, **k: pytest.fail("launched"))
    with pytest.raises(supervisor.Closed, match="INVALID_BUDGET"):
        supervisor.supervise(directory, directory / "source.sqlite3", directory / "backup.sqlite3", total=budget)


def test_reparse_rejected(monkeypatch):
    directory = supervisor.BASE / ("r1c-" + "0" * 32)
    real = Path.lstat
    class Reparse:
        st_mode = 0
        st_file_attributes = 0x400
    monkeypatch.setattr(Path, "lstat", lambda p: Reparse() if p == directory else real(p))
    with pytest.raises(supervisor.Closed, match="REPARSE_DENIED"):
        supervisor.checked_path(directory / "source.sqlite3")


def test_all_quick_check_rows_and_strict_receipt():
    verification = {"quick_check": [["ok"], ["error"]], "size_bytes": 1, "sha256": "a" * 64,
                    "snapshot": {"revision": supervisor.REVISION, "counts": {}}}
    receipt = {"contract_version": "omi.sqlite-backup.v1", "source": "s", "output": "o",
               "size_bytes": 1, "sha256": "a" * 64, "snapshot": verification["snapshot"], "integrity_check": "ok"}
    with pytest.raises(supervisor.Closed, match="INDEPENDENT_CHECK_FAILED"):
        supervisor.validate_receipt(receipt, Path("s"), Path("o"), verification)
    verification["quick_check"] = [["ok"]]
    receipt["size_bytes"] = True
    with pytest.raises(supervisor.Closed, match="RECEIPT_MISMATCH"):
        supervisor.validate_receipt(receipt, Path("s"), Path("o"), verification)


def test_no_lifecycle_or_second_backup_domain():
    text = (ROOT / "scripts/omi-r1-backup-supervisor.py").read_text(encoding="utf-8")
    tree = ast.parse(text)
    assert not any(isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                   and node.func.attr in {"backup", "kill", "terminate", "system"} for node in ast.walk(tree))
    for token in ("taskkill", "omi-launcher", "uvicorn", "RmShutdown", "RmRestart"):
        assert token not in text
    rm = (ROOT / "scripts/omi-r1-resource-owners.py").read_text(encoding="utf-8")
    names = {node.attr for node in ast.walk(ast.parse(rm)) if isinstance(node, ast.Attribute) and node.attr.startswith("Rm")}
    assert names == {"RmStartSession", "RmRegisterResources", "RmGetList", "RmEndSession"}
    assert "sqlite3" not in rm and "stat(" not in rm


class FakeRM:
    def __init__(self, mode):
        self.mode, self.ended, self.resources = mode, False, []

    def RmStartSession(self, session, flags, key):
        return 5 if self.mode == "start_denied" else 0

    def RmRegisterResources(self, session, count, names, apps, applist, services, service_list):
        self.resources.extend(names[:count])
        assert apps == services == 0
        return 5 if self.mode == "register_denied" else 0

    def RmGetList(self, session, needed, count, entries, reason):
        if self.mode == "get_denied":
            return 5
        if self.mode in {"positive", "churn", "end_denied"}:
            needed._obj.value = 1
            if entries is None or self.mode == "churn":
                return 234
            count._obj.value = 1
            entries[0].process.pid = 123
            ticks = 134360000000000000
            entries[0].process.started.dwLowDateTime = ticks & 0xFFFFFFFF
            entries[0].process.started.dwHighDateTime = ticks >> 32
        return 0

    def RmEndSession(self, session):
        self.ended = True
        return 5 if self.mode == "end_denied" else 0


@pytest.mark.parametrize("mode", ["positive", "empty", "start_denied", "register_denied", "get_denied", "churn", "end_denied"])
def test_resource_probe_positive_only(mode):
    api = FakeRM(mode)
    result = owners.query("WAL", api)
    assert result["writer_absence"] == "UNKNOWN"
    assert api.ended == (mode != "start_denied")
    assert api.resources in ([], [owners.RESOURCES["WAL"]])
    if mode == "positive":
        assert result["status"] == "POSITIVE_MATCHES"
        assert result["positive_matches"][0]["pid"] == 123
        assert result["positive_matches"][0]["resource_role"] == "WAL"
    else:
        assert result["status"].startswith("UNKNOWN")
        assert not result["positive_matches"]


def test_offline_guard_active():
    import socket
    with pytest.raises(RuntimeError, match="offline guard"):
        socket.getaddrinfo("r1c.invalid", 443)
