from __future__ import annotations

import base64
from datetime import date
import json
from pathlib import Path
import shutil
import subprocess

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SERVICE_RUNNER = REPO_ROOT / "scripts" / "run-service-logged.ps1"
LAUNCHER = REPO_ROOT / "scripts" / "omi-launcher.ps1"
BIND_FAILURE_EXIT_CODE = 78


def _powershell() -> str:
    executable = shutil.which("powershell.exe") or shutil.which("powershell")
    if executable is None:
        pytest.skip("Windows PowerShell is required for launcher recovery tests.")
    return executable


def test_service_runner_classifies_backend_bind_failure_without_retry(tmp_path: Path) -> None:
    powershell = _powershell()
    child = tmp_path / "bind-failure-child.ps1"
    child.write_text(
        "Write-Output \"ERROR: [Errno 13] error while attempting to bind on address "
        "('127.0.0.1', 8400): [WinError 10013]\"\nexit 1\n",
        encoding="utf-8",
    )
    encoded_arguments = base64.b64encode(
        json.dumps(
            ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(child)],
            ensure_ascii=False,
        ).encode("utf-8")
    ).decode("ascii")

    result = subprocess.run(
        [
            powershell,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(SERVICE_RUNNER),
            "-ServiceName",
            "backend",
            "-RepoRoot",
            str(tmp_path),
            "-WorkingDirectory",
            str(tmp_path),
            "-FilePath",
            powershell,
            "-ArgumentsJsonBase64",
            encoded_arguments,
            "-LauncherPid",
            "0",
            "-MaxRestartAttempts",
            "3",
            "-RestartBackoffSecondsCsv",
            "0",
        ],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )

    log_path = tmp_path / "logs" / "backend" / date.today().isoformat() / "backend.log"
    log_text = log_path.read_text(encoding="utf-8-sig")
    assert result.returncode == BIND_FAILURE_EXIT_CODE
    assert log_text.count("Service child started.") == 1
    assert "Service bind failure classified for launcher port recovery." in log_text
    assert "Service restart scheduled." not in log_text


def test_launcher_rebuilds_frontend_after_bounded_backend_port_reselection() -> None:
    launcher_text = LAUNCHER.read_text(encoding="utf-8-sig")

    assert "$script:BackendBindFailureExitCode = 78" in launcher_text
    assert "$script:MaxBackendPortRecoveryAttempts = 3" in launcher_text
    assert "function Invoke-BackendBindFailureRecovery" in launcher_text
    recovery_body = launcher_text.split(
        "function Invoke-BackendBindFailureRecovery", 1
    )[1].split("function Stop-BackendService", 1)[0]
    assert "Find-AvailableBackendPort" in recovery_body
    assert "Update-BackendServiceUrls" in recovery_body
    assert "Stop-FrontendService" in recovery_body
    assert "Start-Backend" in recovery_body
    assert "Start-Frontend" in recovery_body


def test_launcher_uses_stable_frontend_bundling_and_bounded_health_recovery() -> None:
    launcher_text = LAUNCHER.read_text(encoding="utf-8-sig")

    assert '$script:FrontendDevBundlerArgument = "--webpack"' in launcher_text
    assert "$script:FrontendHealthRecoveryGraceSeconds = 30" in launcher_text
    assert "$script:FrontendHealthStableResetSeconds = 600" in launcher_text
    assert "$script:MaxFrontendHealthRecoveryAttempts = 1" in launcher_text

    start_body = launcher_text.split("function Start-Frontend", 1)[1].split(
        "function Start-Services", 1
    )[0]
    assert "$script:FrontendDevBundlerArgument" in start_body
    assert "-Arguments $frontendArguments" in start_body

    recovery_body = launcher_text.split(
        "function Invoke-FrontendHealthRecovery", 1
    )[1].split("function Stop-Services", 1)[0]
    assert "Stop-FrontendService" in recovery_body
    assert "Clear-FrontendDevOutput" in recovery_body
    assert "Start-Frontend" in recovery_body

    timer_body = launcher_text.split("$script:Timer.add_Tick({", 1)[1].split(
        "$script:ActivationTimer =", 1
    )[0]
    assert "$frontendProc -and (-not $script:IsPackagedRelease)" in timer_body
    assert "Invoke-FrontendHealthRecovery" in timer_body


def test_launcher_compiles_taskbar_listener_against_runtime_winforms_assemblies() -> None:
    launcher_text = LAUNCHER.read_text(encoding="utf-8-sig")

    assert "[System.Windows.Forms.Application].Assembly.Location" in launcher_text
    assert "[System.Windows.Forms.Message].Assembly.Location" in launcher_text
    assert "Add-Type -ReferencedAssemblies $winFormsReferences" in launcher_text
    assert 'Add-Type -ReferencedAssemblies @("System.Windows.Forms")' not in launcher_text
