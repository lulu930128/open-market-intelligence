"""Derive JobService production submission and owner evidence without app imports.

This is source evidence, not a runtime call-graph proof. Dynamic calls remain
visible as unresolved evidence. No provider, DB, scheduler or app startup.
"""
import ast
import json
from pathlib import Path


def inventory(root: Path):
    modules = {}
    for path in sorted((root / "backend/app").rglob("*.py")):
        module = ".".join(path.relative_to(root / "backend").with_suffix("").parts)
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        imports = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and not node.level:
                imports.update({a.asname or a.name: node.module + "." + a.name for a in node.names})
            elif isinstance(node, ast.Import):
                imports.update({a.asname or a.name: a.name for a in node.names})
        functions = {n.name: n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        modules[module] = (path, tree, imports, functions)

    def resolve(module, node):
        name = ast.unparse(node)
        head, _, tail = name.partition(".")
        imports, functions = modules[module][2:]
        if head in imports:
            return imports[head] + ("." + tail if tail else "")
        if name in functions:
            return module + "." + name
        return None

    def locate(name):
        mod, _, fn = name.rpartition(".")
        return modules.get(mod, (None, None, None, {}))[3].get(fn)

    submissions, unresolved = {}, []
    for module, (path, tree, _, functions) in modules.items():
        if module == "app.jobs.service":
            continue  # Generic forwarding is the inventory sink, not an entry.
        for node in ast.walk(tree):
            candidates = []
            if isinstance(node, ast.Call):
                candidates = [kw.value for kw in node.keywords if kw.arg == "task"]
                if ast.unparse(node.func).endswith("submit_job_task") and node.args:
                    candidates.append(node.args[0])
            # The canonical retry router returns (task, arguments, request).
            elif module == "app.routers.jobs" and isinstance(node, ast.Return) and isinstance(node.value, ast.Tuple):
                candidates = node.value.elts[:1]
            for candidate in candidates:
                name = resolve(module, candidate)
                if name and locate(name):
                    job_types = [ast.unparse(kw.value) for kw in node.keywords if kw.arg == "job_type"] if isinstance(node, ast.Call) else []
                    submissions.setdefault(name, []).append({"path": path.relative_to(root).as_posix(), "line": node.lineno,
                                                           "job_type_expression": job_types})
                else:
                    unresolved.append({"module": module, "line": node.lineno, "expression": ast.unparse(candidate)})

    def evidence(name, depth=0, visited=None):
        visited = set() if visited is None else visited
        if name in visited or depth > 2:
            return []
        visited.add(name)
        node = locate(name)
        if node is None:
            return []
        module = name.rpartition(".")[0]
        calls = [n for n in ast.walk(node) if isinstance(n, ast.Call)]
        owners = sorted({target for call in calls if (target := resolve(module, call.func))
                         and target.startswith("app.") and not target.startswith(("app.jobs.service.", "app.jobs.cooperative."))})
        row = {"function": name, "path": modules[module][0].relative_to(root).as_posix(),
               "line": node.lineno, "loops": sorted(n.lineno for n in ast.walk(node) if isinstance(n, (ast.For, ast.While))),
               "transactions": [{"line": c.lineno, "call": ast.unparse(c.func)} for c in calls
                                if ast.unparse(c.func).endswith((".commit", ".rollback"))],
               "request_timeouts": [{"line": c.lineno, "value": ast.unparse(kw.value)} for c in calls
                                    for kw in c.keywords if kw.arg in ("timeout", "timeout_seconds")],
               "calls": owners}
        result = [row]
        for owner in owners:
            result.extend(evidence(owner, depth + 1, visited))
        return result

    policy_tree = modules["app.jobs.resumption"][1]
    assignments = {node.targets[0].id: node.value for node in policy_tree.body
                   if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)}
    queued = ast.literal_eval(assignments["QUEUED_TASKS"].args[0])
    periods = ast.literal_eval(assignments["PERIOD_TASK_OWNERS"])
    bounded_owners = ast.literal_eval(assignments["OWNER_TASKS"])
    handoffs = ast.literal_eval(assignments["ORIGINAL_HANDOFF_TASKS"].args[0])
    outcome = ast.literal_eval(assignments["RADAR_OUTCOME_TASK"])
    rows = []
    for name, refs in sorted(submissions.items()):
        identity = tuple(name.rsplit(".", 1))
        boundary = periods.get(identity) or bounded_owners.get(identity)
        if boundary == "us_eod_symbols":
            boundary += "_US_only_TW_venue_BLOCKED"
        if identity == outcome:
            boundary = "canonical_outcome_evaluation_commit_or_rollback"
        if name == "app.jobs.backfill_tasks.run_taiwan_broker_branch_market_refresh_job":
            boundary = "canonical_broker_stock_commit"
        rows.append({"task": name, "submissions": refs, "owner_evidence": evidence(name),
                     "business_side_effects": "DB writes; Dispatch also external mail" if identity not in queued else "DB/provider work or child admission; see owner evidence",
                     "queued_resume": ("allowlisted_not_started" if identity in queued else
                                       "original_owner_unstarted_claim_handoff" if identity in handoffs else
                                       "BLOCKED_original_state_machine_only"),
                     "running_resume": boundary or "BLOCKED_no_audited_running_descriptor",
                     "max_uninterruptible_wall_seconds": None,
                     "duration_limit": "No proven hard wall bound; HTTP timeouts are inactivity bounds. JobService deadline fails closed and retains Future."})
    return {"tasks": rows, "unresolved_forwarding": unresolved,
            "counts": {"reachable": len(rows), "running_checkpoint": sum(row["running_resume"].startswith("BLOCKED") is False for row in rows),
                       "queued_only": sum(row["queued_resume"] == "allowlisted_not_started" and row["running_resume"].startswith("BLOCKED") for row in rows),
                       "original_owner_blocked": sum(identity not in queued and identity not in handoffs for identity in (tuple(row["task"].rsplit(".", 1)) for row in rows)),
                       "original_owner_handoff": sum(tuple(row["task"].rsplit(".", 1)) in handoffs for row in rows),
                       "proven_bounded_run_to_completion": 0}}


if __name__ == "__main__":
    print(json.dumps(inventory(Path(__file__).resolve().parents[1]), indent=2, ensure_ascii=True))
