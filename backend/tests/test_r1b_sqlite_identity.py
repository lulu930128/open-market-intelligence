"""B1 source/isolated tests; no application import, settings, env or live DB."""
import ast
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / 'backend/tests/fixtures/r1b_sqlite_identity.py'
spec = importlib.util.spec_from_file_location('r1b_sqlite_fixture', FIXTURE)
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


@pytest.mark.parametrize('case,expected,reason', [
    ('success', 'DISPOSABLE_BINDING_PASS', None),
    ('creator_redirect', 'BLOCKED', 'engine_connection_match'),
    ('memory', 'BLOCKED', 'connection_file_match'),
    ('retained_connection', 'BLOCKED', 'handle_closed'),
])
def test_real_child_engine_connection_os_handle_lifecycle(case, expected, reason):
    result = subprocess.run([sys.executable, '-B', str(FIXTURE), case],
                            capture_output=True, text=True, timeout=20)
    payload = json.loads(result.stdout)
    assert payload['verdict'] == expected, json.dumps(payload, indent=2)
    assert result.returncode == (0 if expected == 'DISPOSABLE_BINDING_PASS' else 2)
    assert payload['production_gate'] == 'BLOCKED'
    assert payload['database_handle_binding'] == 'UNKNOWN'
    assert payload['loaded_release_identity'] == 'UNKNOWN'
    assert payload['evidence']['pid'] != os.getpid()
    assert payload['evidence']['process_start_filetime'] > 0
    if reason:
        assert reason in payload['reasons']
    else:
        evidence = payload['evidence']
        identities = list(evidence['new_disk_handle_identities'].values())
        assert identities.count(evidence['expected_identity']) == 1
        assert evidence['expected_identity'] == evidence['connection_identity']


def test_native_identity_does_not_depend_on_python_stat_width(monkeypatch):
    original = Path.lstat

    def legacy_stat(path, *args, **kwargs):
        info = original(path, *args, **kwargs)
        return SimpleNamespace(st_file_attributes=info.st_file_attributes,
                               st_mode=info.st_mode, st_nlink=info.st_nlink,
                               st_dev=0, st_ino=0)

    monkeypatch.setattr(Path, 'lstat', legacy_stat)
    payload = fixture.run()
    assert payload['verdict'] == 'DISPOSABLE_BINDING_PASS', payload
    assert payload['evidence']['expected_identity'] != [0, 0]
    assert payload['production_gate'] == 'BLOCKED'


@pytest.mark.parametrize('fault', ['denied', 'partial', 'missing', 'wrong_identity'])
def test_handle_evidence_failure_is_blocked(monkeypatch, fault):
    if fault in {'denied', 'partial'}:
        original = fixture.OwnHandles.snapshot
        calls = 0

        def unavailable(self):
            nonlocal calls
            calls += 1
            if fault == 'denied' or calls == 2:
                raise fixture.EvidenceUnavailable('fixture snapshot failure')
            return original(self)
        monkeypatch.setattr(fixture.OwnHandles, 'snapshot', unavailable)
    else:
        monkeypatch.setattr(fixture.OwnHandles, 'disk_identity',
                            lambda self, h: None if fault == 'missing' else [-1, -1])
    payload = fixture.run()
    assert payload['verdict'] == 'BLOCKED'
    assert payload['database_handle_binding'] == 'UNKNOWN'
    assert ('complete_handle_snapshots' if fault in {'denied', 'partial'}
            else 'one_new_matching_handle') in payload['reasons']


def test_outside_scope_rejected_before_filesystem_access(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('Filesystem access outside disposable root')
    monkeypatch.setattr(Path, 'lstat', forbidden)
    with pytest.raises(fixture.EvidenceUnavailable, match='Outside disposable scope'):
        fixture.guarded_identity(Path('C:/never-read/example.sqlite'), Path('C:/fixture-only'))


def test_hardlink_alias_is_rejected(tmp_path):
    source = tmp_path / 'fixture.sqlite'
    source.write_bytes(b'fixture')
    os.link(source, tmp_path / 'alias.sqlite')
    with pytest.raises(fixture.EvidenceUnavailable, match='single-link'):
        fixture.guarded_identity(source, tmp_path)


def test_reparse_alias_is_rejected_before_following(monkeypatch):
    monkeypatch.setattr(Path, 'lstat', lambda self: SimpleNamespace(st_file_attributes=0x400))
    with pytest.raises(fixture.EvidenceUnavailable, match='Reparse'):
        fixture.guarded_identity(Path('C:/fixture-only/a.sqlite'), Path('C:/fixture-only'))


def test_path_identity_replacement_blocks(monkeypatch):
    original = fixture.guarded_identity
    calls = 0

    def changed(path, root):
        nonlocal calls
        calls += 1
        return [-1, -1] if calls == 3 else original(path, root)
    monkeypatch.setattr(fixture, 'guarded_identity', changed)
    payload = fixture.run()
    assert payload['verdict'] == 'BLOCKED'
    assert 'file_identity_stable' in payload['reasons']


def test_missing_evidence_never_passes():
    assert fixture.verdict({})['verdict'] == 'BLOCKED'


def test_current_source_diagnostic_stays_memory_only_without_application_import():
    # Execute the exact current function AST with isolated stand-ins. Importing
    # app.db.session would load real settings/.env, which this task forbids.
    tree = ast.parse((ROOT / 'backend/app/db/session.py').read_text('utf-8-sig'))
    function = next(node for node in tree.body
                    if isinstance(node, ast.FunctionDef) and node.name == 'database_binding_metadata')
    engine = SimpleNamespace(url='synthetic-url')
    namespace = dict(engine=engine, _binding_engine=engine, _binding_url=engine.url,
                     _binding_target={'kind': 'fixture'}, _binding_captured_at='fixture',
                     settings=SimpleNamespace(database_url=engine.url), make_url=lambda value: value,
                     ArgumentError=ValueError, os=SimpleNamespace(getpid=lambda: 42))
    exec(compile(ast.Module(body=[function], type_ignores=[]), '<source-diagnostic>', 'exec'), namespace)
    result = namespace['database_binding_metadata']()
    assert result['evidence_scope'] == 'loaded_engine_configuration_only'
    assert result['database_handle_binding'] == 'UNVERIFIED'
    assert result['loaded_release_identity'] == 'UNATTESTED'
    assert result['source_hash_basis'] is None


def test_fixture_has_no_production_import_or_arbitrary_target_interface():
    tree = ast.parse(FIXTURE.read_text('utf-8'))
    imports = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert not any(name == 'app' or name.startswith('app.') for name in imports if name)
    assert 'OpenProcess' not in FIXTURE.read_text('utf-8')
    with pytest.raises(ValueError, match='Unknown fixture case'):
        fixture.run('arbitrary-production-path')
