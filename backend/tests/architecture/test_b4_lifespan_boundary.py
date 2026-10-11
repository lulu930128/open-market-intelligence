"""The B4 fixture cannot become production lifecycle authority."""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_b4_branch_is_terminal_default_off_and_fixed_command():
    runner=(ROOT/'scripts/run-service-logged.ps1').read_text(encoding='utf-8-sig')
    branch=runner[runner.index('if ($UvicornLifespanFixture)'):runner.index('if ($GracefulStopFixture)')]
    assert '[switch]$UvicornLifespanFixture' in runner
    for required in ("$ServiceName -cne 'r1-b4-disposable'", "$json -cne '[]'", '$LauncherPid -ne 0',
                     'exit $code', 'exit 79', 'Verified base interpreter required'):
        assert required in branch
    for path in ['scripts/omi-launcher.ps1','backend/app/runtime.py','backend/app/main.py']:
        assert 'UvicornLifespanFixture' not in (ROOT/path).read_text(encoding='utf-8-sig')


def test_child_only_executes_hash_bound_owner_ast_and_no_network_listener():
    source=(ROOT/'backend/tests/fixtures/b4_lifespan_child.py').read_text(encoding='utf-8')
    tree=ast.parse(source)
    imports={n.module for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)}
    assert not any(name and name.startswith('app.') for name in imports)
    calls={ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n,ast.Call)}
    assert not {'runtime.start','create_engine','socket.socket','subprocess.Popen'} & calls
    assert 'server.serve(sockets=[])' in source and 'server.should_exit = True' in source
    assert 'install_guard()' in source
    assert not any(isinstance(n,ast.ClassDef) and n.name in {'RuntimeCoordinator','SessionDrainResult','PublisherDrainResult'}
                   for n in ast.walk(tree))


def test_helper_has_no_force_fallback_or_production_root():
    source=(ROOT/'scripts/omi-graceful-stop-fixture.ps1').read_text(encoding='utf-8-sig')
    for forbidden in ('Stop-Process','taskkill','.Kill(', 'Stop-ServiceProcessTree','Invoke-WebRequest'):
        assert forbidden not in source
    assert 'B4 task-private fixture root required' in source
    assert source.index('$stopIntent = $true') < source.index("'stop-intent.json'") < source.index("'request.json'")
