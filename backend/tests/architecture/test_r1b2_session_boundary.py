"""API owner adoption cannot become a global writer certificate."""
import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def source(path):
    return ast.parse((ROOT / path).read_text(encoding="utf-8-sig"))


def calls(node):
    return {ast.unparse(n.func) for n in ast.walk(node) if isinstance(n, ast.Call)}


def test_default_dependency_keeps_lazy_session_close_without_drain_or_sql():
    tree = source("backend/app/db/session.py")
    dependency = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "get_db")
    assert calls(dependency) == {"get_draining_db"}
    assert not any(isinstance(n, ast.ClassDef) and any("Session" in ast.unparse(b) for b in n.bases)
                   for n in tree.body)
    for n in tree.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in {
            "require_session_scope_admission", "begin_session_scope_drain",
            "session_scope_drain_status", "drain_session_scopes",
        }:
            assert not any(c.rsplit(".", 1)[-1] in {
                "commit", "rollback", "execute", "connect", "close", "SessionLocal",
            } for c in calls(n))


def test_production_lifespan_enables_canonical_owner_fences():
    tree = source("backend/app/runtime.py")
    lifespan = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "lifespan")
    constructor = next(n for n in ast.walk(lifespan)
                       if isinstance(n, ast.Call) and ast.unparse(n.func) == "RuntimeCoordinator")
    assert not constructor.args
    assert {kw.arg: ast.literal_eval(kw.value) for kw in constructor.keywords} == {
        "drain_owned_sessions": True, "drain_engine_connections": True,
    }
    init = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "__init__"
                and any(a.arg == "drain_owned_sessions" for a in n.args.kwonlyargs))
    defaults = dict(zip((a.arg for a in init.args.kwonlyargs), init.args.kw_defaults))
    assert ast.literal_eval(defaults["drain_owned_sessions"]) is False
    assert "get_draining_db" not in (ROOT / "backend/app/main.py").read_text(encoding="utf-8-sig")


def test_session_scope_cannot_claim_global_writer_coverage():
    tree = source("backend/app/db/session.py")
    result = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "SessionDrainResult")
    field = next(n for n in result.body if isinstance(n, ast.AnnAssign)
                 and ast.unparse(n.target) == "all_writers_drained")
    assert ast.literal_eval(field.value) is False
    # No broad event/engine instrumentation was added to the private seam.
    scope = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "owned_session")
    assert not any(c.startswith("event.") or c.rsplit(".", 1)[-1] in {"commit", "rollback", "execute"}
                   for c in calls(scope))
