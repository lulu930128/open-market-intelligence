"""Enforce that the feasibility seam cannot become production stop authority."""
import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def test_fixture_opt_in_stays_out_of_launcher_and_runtime():
    runner = (ROOT / 'scripts/run-service-logged.ps1').read_text(encoding='utf-8-sig')
    branch = runner[runner.index('if ($GracefulStopFixture)'):runner.index('$logRoot =')]
    assert '[switch]$GracefulStopFixture' in runner
    assert 'exit $code' in branch and 'exit 79' in branch
    assert "$ServiceName -ne 'r1e-fixture'" in branch and '$LauncherPid -ne 0' in branch
    for path in ('scripts/omi-launcher.ps1', 'backend/app/runtime.py'):
        source = (ROOT / path).read_text(encoding='utf-8-sig')
        assert 'GracefulStopFixture' not in source
        assert 'omi-graceful-stop-fixture.ps1' not in source


def test_fixture_has_no_app_network_database_or_force_dependency():
    child = ROOT / 'backend/tests/fixtures/r1e_stop_child.py'
    tree = ast.parse(child.read_text(encoding='utf-8'))
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split('.')[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.add(node.module.split('.')[0])
    assert imports <= {'ctypes', 'datetime', 'json', 'os', 'pathlib', 'sys', 'threading', 'time'}
    helper = (ROOT / 'scripts/omi-graceful-stop-fixture.ps1').read_text()
    for forbidden in ('Stop-Process', 'taskkill', '.Kill(', 'Stop-ServiceProcessTree', 'Invoke-WebRequest', 'Start-Job'):
        assert forbidden not in helper
    assert helper.index('$stopIntent = $true') < helper.index("'stop-intent.json'") < helper.index("'request.json'")
