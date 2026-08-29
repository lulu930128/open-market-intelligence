from __future__ import annotations

import argparse
import ast
from collections import Counter
from dataclasses import dataclass
import json
from pathlib import Path
import re
import sys
from typing import Any, Iterable, Mapping, Sequence

import tomllib


SCHEMA_VERSION = 1


class ArchitectureConfigError(ValueError):
    pass


@dataclass(frozen=True, order=True)
class ViolationKey:
    rule: str
    path: str
    occurrence: str


@dataclass(frozen=True, order=True)
class Violation:
    key: ViolationKey
    line: int
    detail: str

    def to_dict(self) -> dict[str, object]:
        return {
            "rule": self.key.rule,
            "path": self.key.path,
            "occurrence": self.key.occurrence,
            "line": self.line,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class DebtEntry:
    id: str
    key: ViolationKey
    reason: str
    owner: str
    closure_gate: str


@dataclass(frozen=True)
class Evaluation:
    violations: tuple[Violation, ...]
    debt: tuple[DebtEntry, ...]
    undeclared: tuple[Violation, ...]
    stale: tuple[DebtEntry, ...]

    @property
    def passed(self) -> bool:
        return not self.undeclared and not self.stale


@dataclass(frozen=True)
class ImportFact:
    module: str
    symbol: str
    line: int


@dataclass(frozen=True)
class CallFact:
    name: str
    symbol: str
    line: int
    node: ast.Call


class PythonFactCollector(ast.NodeVisitor):
    def __init__(self) -> None:
        self.scope: list[str] = []
        self.imports: list[ImportFact] = []
        self.calls: list[CallFact] = []

    @property
    def symbol(self) -> str:
        return ".".join(self.scope) if self.scope else "<module>"

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.imports.append(ImportFact(alias.name, self.symbol, node.lineno))
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module:
            self.imports.append(ImportFact(node.module, self.symbol, node.lineno))
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        name = dotted_call_name(node.func)
        if name:
            self.calls.append(CallFact(name, self.symbol, node.lineno, node))
        dynamic_module = literal_dynamic_import(node)
        if dynamic_module:
            self.imports.append(
                ImportFact(dynamic_module, self.symbol, getattr(node, "lineno", 0))
            )
        self.generic_visit(node)


def dotted_call_name(node: ast.AST) -> str | None:
    parts: list[str] = []
    current = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
        return ".".join(reversed(parts))
    return None


def literal_dynamic_import(node: ast.Call) -> str | None:
    name = dotted_call_name(node.func)
    if name not in {"__import__", "importlib.import_module"} or not node.args:
        return None
    value = node.args[0]
    if isinstance(value, ast.Constant) and isinstance(value.value, str):
        return value.value
    return None


def normalize_repo_path(repo_root: Path, path: Path) -> str:
    return path.resolve().relative_to(repo_root.resolve()).as_posix()


def load_toml(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as handle:
            value = tomllib.load(handle)
    except FileNotFoundError as exc:
        raise ArchitectureConfigError(f"missing configuration: {path}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ArchitectureConfigError(f"invalid TOML {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ArchitectureConfigError(f"configuration root must be a table: {path}")
    return value


def require_schema(config: Mapping[str, Any], path: Path) -> None:
    if config.get("schema_version") != SCHEMA_VERSION:
        raise ArchitectureConfigError(
            f"{path} schema_version must be {SCHEMA_VERSION}"
        )


def string_list(value: Any, *, field: str, rule_id: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ArchitectureConfigError(f"rule {rule_id}: {field} must be a string list")
    return tuple(value)


def iter_rule_files(repo_root: Path, rule: Mapping[str, Any]) -> tuple[Path, ...]:
    rule_id = str(rule.get("id") or "<unknown>")
    roots = string_list(rule.get("roots", []), field="roots", rule_id=rule_id)
    extensions = string_list(
        rule.get("extensions", []), field="extensions", rule_id=rule_id
    )
    excluded = tuple(
        item.replace("\\", "/").rstrip("/")
        for item in string_list(
            rule.get("exclude_path_prefixes", []),
            field="exclude_path_prefixes",
            rule_id=rule_id,
        )
    )
    found: list[Path] = []
    for root_value in roots:
        root = repo_root / root_value
        if not root.exists():
            raise ArchitectureConfigError(f"rule {rule_id}: root does not exist: {root_value}")
        candidates = (root,) if root.is_file() else root.rglob("*")
        for path in candidates:
            if not path.is_file() or (extensions and path.suffix not in extensions):
                continue
            relative = normalize_repo_path(repo_root, path)
            if any(relative == prefix or relative.startswith(prefix + "/") for prefix in excluded):
                continue
            found.append(path)
    return tuple(sorted(set(found), key=lambda item: normalize_repo_path(repo_root, item)))


def parse_python(path: Path) -> tuple[ast.Module, PythonFactCollector]:
    try:
        source = path.read_text(encoding="utf-8-sig")
        tree = ast.parse(source, filename=str(path))
    except (OSError, UnicodeError, SyntaxError) as exc:
        raise ArchitectureConfigError(f"cannot parse Python source {path}: {exc}") from exc
    facts = PythonFactCollector()
    facts.visit(tree)
    return tree, facts


def module_matches(module: str, prefixes: Sequence[str]) -> bool:
    return any(module == prefix or module.startswith(prefix + ".") for prefix in prefixes)


def stable_occurrences(
    facts: Iterable[tuple[str, str, int]],
) -> Iterable[tuple[str, str, int, int]]:
    values = sorted(facts, key=lambda item: (item[0], item[1], item[2]))
    totals = Counter((symbol, target) for symbol, target, _line in values)
    seen: Counter[tuple[str, str]] = Counter()
    for symbol, target, line in values:
        key = (symbol, target)
        seen[key] += 1
        ordinal = seen[key] if totals[key] > 1 else 0
        yield symbol, target, line, ordinal


def suffix_ordinal(value: str, ordinal: int) -> str:
    return f"{value}#{ordinal}" if ordinal else value


def check_forbidden_imports(
    repo_root: Path, rule: Mapping[str, Any]
) -> list[Violation]:
    rule_id = str(rule["id"])
    prefixes = string_list(
        rule.get("forbidden_prefixes"),
        field="forbidden_prefixes",
        rule_id=rule_id,
    )
    violations: list[Violation] = []
    for path in iter_rule_files(repo_root, rule):
        _tree, facts = parse_python(path)
        matches = (
            (fact.symbol, fact.module, fact.line)
            for fact in facts.imports
            if module_matches(fact.module, prefixes)
        )
        for symbol, module, line, ordinal in stable_occurrences(matches):
            occurrence = suffix_ordinal(f"{symbol}:import:{module}", ordinal)
            violations.append(
                Violation(
                    ViolationKey(rule_id, normalize_repo_path(repo_root, path), occurrence),
                    line,
                    f"forbidden import {module}",
                )
            )
    return violations


def check_forbidden_import_names(
    repo_root: Path, rule: Mapping[str, Any]
) -> list[Violation]:
    """Reject selected names imported from one or more exact modules.

    This is intentionally narrower than ``python_forbidden_import``: canonical
    repository and platform owners may import persistence models, while the
    listed consumer surfaces may not import those storage rows as evidence.
    """

    rule_id = str(rule["id"])
    modules = set(
        string_list(
            rule.get("modules"),
            field="modules",
            rule_id=rule_id,
        )
    )
    forbidden_names = set(
        string_list(
            rule.get("forbidden_names"),
            field="forbidden_names",
            rule_id=rule_id,
        )
    )
    violations: list[Violation] = []
    for path in iter_rule_files(repo_root, rule):
        tree, _facts = parse_python(path)
        matches: list[tuple[str, str, int]] = []

        class ImportNameCollector(ast.NodeVisitor):
            def __init__(self) -> None:
                self.scope: list[str] = []

            @property
            def symbol(self) -> str:
                return ".".join(self.scope) if self.scope else "<module>"

            def visit_ClassDef(self, node: ast.ClassDef) -> None:
                self.scope.append(node.name)
                self.generic_visit(node)
                self.scope.pop()

            def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
                self.scope.append(node.name)
                self.generic_visit(node)
                self.scope.pop()

            def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
                self.scope.append(node.name)
                self.generic_visit(node)
                self.scope.pop()

            def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
                if node.module in modules:
                    for alias in node.names:
                        if alias.name in forbidden_names:
                            matches.append(
                                (
                                    self.symbol,
                                    f"{node.module}:{alias.name}",
                                    node.lineno,
                                )
                            )
                self.generic_visit(node)

        ImportNameCollector().visit(tree)
        for symbol, target, line, ordinal in stable_occurrences(matches):
            occurrence = suffix_ordinal(
                f"{symbol}:import-name:{target}",
                ordinal,
            )
            violations.append(
                Violation(
                    ViolationKey(
                        rule_id,
                        normalize_repo_path(repo_root, path),
                        occurrence,
                    ),
                    line,
                    f"forbidden storage-model import {target}",
                )
            )
    return violations


def check_forbidden_calls(
    repo_root: Path, rule: Mapping[str, Any]
) -> list[Violation]:
    rule_id = str(rule["id"])
    names = set(
        string_list(
            rule.get("forbidden_call_names"),
            field="forbidden_call_names",
            rule_id=rule_id,
        )
    )
    violations: list[Violation] = []
    for path in iter_rule_files(repo_root, rule):
        _tree, facts = parse_python(path)
        matches = (
            (fact.symbol, fact.name, fact.line)
            for fact in facts.calls
            if fact.name.rsplit(".", 1)[-1] in names
        )
        for symbol, call_name, line, ordinal in stable_occurrences(matches):
            occurrence = suffix_ordinal(f"{symbol}:call:{call_name}", ordinal)
            violations.append(
                Violation(
                    ViolationKey(rule_id, normalize_repo_path(repo_root, path), occurrence),
                    line,
                    f"forbidden transaction call {call_name}",
                )
            )
    return violations


def is_router_get(function: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for decorator in function.decorator_list:
        if not isinstance(decorator, ast.Call):
            continue
        name = dotted_call_name(decorator.func)
        if name and name.rsplit(".", 1)[-1] == "get":
            return True
        if name and name.rsplit(".", 1)[-1] == "api_route":
            for keyword in decorator.keywords:
                if keyword.arg != "methods" or not isinstance(keyword.value, (ast.List, ast.Tuple)):
                    continue
                methods = {
                    str(item.value).upper()
                    for item in keyword.value.elts
                    if isinstance(item, ast.Constant) and isinstance(item.value, str)
                }
                if "GET" in methods:
                    return True
    return False


def false_like(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and node.value in {False, None, 0, ""}


def check_get_side_effects(
    repo_root: Path, rule: Mapping[str, Any]
) -> list[Violation]:
    rule_id = str(rule["id"])
    prefixes = string_list(
        rule.get("side_effect_call_prefixes"),
        field="side_effect_call_prefixes",
        rule_id=rule_id,
    )
    keywords = set(
        string_list(
            rule.get("side_effect_keywords"),
            field="side_effect_keywords",
            rule_id=rule_id,
        )
    )
    violations: list[Violation] = []
    for path in iter_rule_files(repo_root, rule):
        tree, _facts = parse_python(path)
        raw: list[tuple[str, str, int, str]] = []
        for function in ast.walk(tree):
            if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not is_router_get(function):
                continue
            for node in ast.walk(function):
                if not isinstance(node, ast.Call):
                    continue
                call_name = dotted_call_name(node.func)
                if not call_name:
                    continue
                leaf = call_name.rsplit(".", 1)[-1].lstrip("_")
                if any(leaf.startswith(prefix) for prefix in prefixes):
                    raw.append(
                        (
                            function.name,
                            f"call:{call_name}",
                            node.lineno,
                            f"GET handler calls side-effect candidate {call_name}",
                        )
                    )
                for keyword in node.keywords:
                    if keyword.arg in keywords and not false_like(keyword.value):
                        raw.append(
                            (
                                function.name,
                                f"keyword:{call_name}:{keyword.arg}",
                                node.lineno,
                                f"GET handler passes dynamic side-effect keyword {keyword.arg} to {call_name}",
                            )
                        )
        totals = Counter((symbol, target) for symbol, target, _line, _detail in raw)
        seen: Counter[tuple[str, str]] = Counter()
        for symbol, target, line, detail in sorted(raw, key=lambda item: (item[0], item[1], item[2])):
            key = (symbol, target)
            seen[key] += 1
            ordinal = seen[key] if totals[key] > 1 else 0
            occurrence = suffix_ordinal(f"{symbol}:{target}", ordinal)
            violations.append(
                Violation(
                    ViolationKey(rule_id, normalize_repo_path(repo_root, path), occurrence),
                    line,
                    detail,
                )
            )
    return violations


REQUEST_START_RE = re.compile(r"\b(request[A-Za-z0-9_]*|fetch)\s*(?:<[^;()]*>)?\s*\(")
ENDPOINT_RE = re.compile(r"[`\"'](/api/[^`\"']*)[`\"']")
PROVIDER_PROPERTY_RE = re.compile(r"\bprovider\s*:\s*([^,}\r\n]+)")


def balanced_call(text: str, open_paren: int) -> str | None:
    depth = 0
    quote: str | None = None
    escaped = False
    for index in range(open_paren, len(text)):
        char = text[index]
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue
        if char in {"'", '"', "`"}:
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return text[open_paren : index + 1]
    return None


def line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def compact_expression(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip())[:120]


def check_frontend_provider_selection(
    repo_root: Path, rule: Mapping[str, Any]
) -> list[Violation]:
    rule_id = str(rule["id"])
    production_prefixes = string_list(
        rule.get("production_path_prefixes"),
        field="production_path_prefixes",
        rule_id=rule_id,
    )
    diagnostics = string_list(
        rule.get("diagnostic_path_fragments"),
        field="diagnostic_path_fragments",
        rule_id=rule_id,
    )
    call_prefixes = string_list(
        rule.get("request_call_prefixes"),
        field="request_call_prefixes",
        rule_id=rule_id,
    )
    violations: list[Violation] = []
    for path in iter_rule_files(repo_root, rule):
        text = path.read_text(encoding="utf-8-sig")
        raw: list[tuple[str, int, str]] = []
        for match in REQUEST_START_RE.finditer(text):
            call_name = match.group(1)
            if not any(call_name.startswith(prefix) for prefix in call_prefixes):
                continue
            open_paren = text.find("(", match.start(), match.end())
            body = balanced_call(text, open_paren)
            if body is None:
                continue
            endpoint_match = ENDPOINT_RE.search(body)
            if endpoint_match is None:
                continue
            endpoint = endpoint_match.group(1)
            if not any(endpoint.startswith(prefix) for prefix in production_prefixes):
                continue
            if any(fragment in endpoint for fragment in diagnostics):
                continue
            provider_match = PROVIDER_PROPERTY_RE.search(body)
            provider_query = "provider=" in endpoint
            if provider_match is None and not provider_query:
                continue
            provider_value = (
                compact_expression(provider_match.group(1))
                if provider_match is not None
                else "<query>"
            )
            occurrence = f"{call_name}:request:{endpoint}:provider:{provider_value}"
            raw.append(
                (
                    occurrence,
                    line_number(text, match.start()),
                    f"production request selects provider {provider_value}",
                )
            )
        totals = Counter(item[0] for item in raw)
        seen: Counter[str] = Counter()
        for occurrence, line, detail in sorted(raw):
            seen[occurrence] += 1
            ordinal = seen[occurrence] if totals[occurrence] > 1 else 0
            violations.append(
                Violation(
                    ViolationKey(
                        rule_id,
                        normalize_repo_path(repo_root, path),
                        suffix_ordinal(occurrence, ordinal),
                    ),
                    line,
                    detail,
                )
            )
    return violations


def check_forbidden_paths(
    repo_root: Path, rule: Mapping[str, Any]
) -> list[Violation]:
    rule_id = str(rule["id"])
    paths = string_list(rule.get("paths"), field="paths", rule_id=rule_id)
    return [
        Violation(
            ViolationKey(rule_id, value.replace("\\", "/"), "path:exists"),
            1,
            "forbidden path exists",
        )
        for value in paths
        if (repo_root / value).exists()
    ]


CHECKERS = {
    "python_forbidden_import": check_forbidden_imports,
    "python_forbidden_import_names": check_forbidden_import_names,
    "python_forbidden_call": check_forbidden_calls,
    "fastapi_get_side_effect": check_get_side_effects,
    "frontend_provider_selection": check_frontend_provider_selection,
    "forbidden_path": check_forbidden_paths,
}


def load_rules(path: Path) -> tuple[dict[str, Any], ...]:
    config = load_toml(path)
    require_schema(config, path)
    raw_rules = config.get("rules")
    if not isinstance(raw_rules, list) or not raw_rules:
        raise ArchitectureConfigError(f"{path} must define at least one [[rules]] entry")
    rules: list[dict[str, Any]] = []
    ids: set[str] = set()
    for value in raw_rules:
        if not isinstance(value, dict):
            raise ArchitectureConfigError(f"{path}: each rule must be a table")
        rule_id = value.get("id")
        kind = value.get("kind")
        if not isinstance(rule_id, str) or not rule_id:
            raise ArchitectureConfigError(f"{path}: rule id is required")
        if rule_id in ids:
            raise ArchitectureConfigError(f"{path}: duplicate rule id {rule_id}")
        if kind not in CHECKERS:
            raise ArchitectureConfigError(f"{path}: unsupported kind {kind!r} for {rule_id}")
        ids.add(rule_id)
        rules.append(dict(value))
    return tuple(rules)


def load_debt(path: Path, *, rule_ids: set[str], repo_root: Path) -> tuple[DebtEntry, ...]:
    config = load_toml(path)
    require_schema(config, path)
    raw_debt = config.get("debt", [])
    if not isinstance(raw_debt, list):
        raise ArchitectureConfigError(f"{path}: debt must be an array of tables")
    required = {
        "id",
        "rule",
        "path",
        "occurrence",
        "reason",
        "owner",
        "closure_gate",
        "new_occurrences_allowed",
    }
    entries: list[DebtEntry] = []
    ids: set[str] = set()
    keys: set[ViolationKey] = set()
    for raw in raw_debt:
        if not isinstance(raw, dict):
            raise ArchitectureConfigError(f"{path}: each debt entry must be a table")
        missing = sorted(required - set(raw))
        if missing:
            raise ArchitectureConfigError(f"{path}: debt entry missing {', '.join(missing)}")
        if raw.get("new_occurrences_allowed") is not False:
            raise ArchitectureConfigError(
                f"{path}: debt {raw.get('id')} must set new_occurrences_allowed = false"
            )
        values = {name: raw.get(name) for name in required - {"new_occurrences_allowed"}}
        if not all(isinstance(value, str) and value for value in values.values()):
            raise ArchitectureConfigError(f"{path}: debt fields must be non-empty strings")
        debt_id = str(raw["id"])
        if debt_id in ids:
            raise ArchitectureConfigError(f"{path}: duplicate debt id {debt_id}")
        rule_id = str(raw["rule"])
        if rule_id not in rule_ids:
            raise ArchitectureConfigError(f"{path}: debt {debt_id} references unknown rule {rule_id}")
        relative = str(raw["path"]).replace("\\", "/")
        if not (repo_root / relative).exists():
            raise ArchitectureConfigError(f"{path}: debt {debt_id} references missing path {relative}")
        key = ViolationKey(rule_id, relative, str(raw["occurrence"]))
        if key in keys:
            raise ArchitectureConfigError(f"{path}: duplicate debt occurrence {key}")
        ids.add(debt_id)
        keys.add(key)
        entries.append(
            DebtEntry(
                debt_id,
                key,
                str(raw["reason"]),
                str(raw["owner"]),
                str(raw["closure_gate"]),
            )
        )
    return tuple(sorted(entries, key=lambda item: item.key))


def collect_violations(repo_root: Path, rules: Sequence[Mapping[str, Any]]) -> tuple[Violation, ...]:
    violations: list[Violation] = []
    for rule in rules:
        checker = CHECKERS[str(rule["kind"])]
        violations.extend(checker(repo_root, rule))
    keys = [item.key for item in violations]
    duplicates = [key for key, count in Counter(keys).items() if count > 1]
    if duplicates:
        raise ArchitectureConfigError(f"checker produced duplicate violation keys: {duplicates}")
    return tuple(sorted(violations, key=lambda item: item.key))


def evaluate(
    repo_root: Path,
    constraints_path: Path | None = None,
    debt_path: Path | None = None,
) -> Evaluation:
    repo_root = repo_root.resolve()
    constraints = constraints_path or repo_root / "architecture" / "constraints.toml"
    debt_manifest = debt_path or repo_root / "architecture" / "debt.toml"
    if not constraints.is_absolute():
        constraints = repo_root / constraints
    if not debt_manifest.is_absolute():
        debt_manifest = repo_root / debt_manifest
    rules = load_rules(constraints)
    violations = collect_violations(repo_root, rules)
    debt = load_debt(debt_manifest, rule_ids={str(rule["id"]) for rule in rules}, repo_root=repo_root)
    actual_by_key = {item.key: item for item in violations}
    debt_by_key = {item.key: item for item in debt}
    undeclared = tuple(actual_by_key[key] for key in sorted(actual_by_key.keys() - debt_by_key.keys()))
    stale = tuple(debt_by_key[key] for key in sorted(debt_by_key.keys() - actual_by_key.keys()))
    return Evaluation(violations, debt, undeclared, stale)


def evaluation_json(result: Evaluation) -> str:
    return json.dumps(
        {
            "passed": result.passed,
            "actual_count": len(result.violations),
            "declared_debt_count": len(result.debt),
            "violations": [item.to_dict() for item in result.violations],
            "undeclared": [item.to_dict() for item in result.undeclared],
            "stale": [
                {
                    "id": item.id,
                    "rule": item.key.rule,
                    "path": item.key.path,
                    "occurrence": item.key.occurrence,
                }
                for item in result.stale
            ],
        },
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )


def print_text(result: Evaluation, *, report_only: bool) -> None:
    status = "REPORT" if report_only else "PASS" if result.passed else "FAIL"
    print(f"Architecture guard: {status}")
    print(f"Actual violations: {len(result.violations)}")
    print(f"Declared debt: {len(result.debt)}")
    if report_only:
        for item in result.violations:
            print(
                f"ACTUAL {item.key.rule} {item.key.path}:{item.line} "
                f"{item.key.occurrence} -- {item.detail}"
            )
        return
    for item in result.undeclared:
        print(
            f"UNDECLARED {item.key.rule} {item.key.path}:{item.line} "
            f"{item.key.occurrence} -- {item.detail}"
        )
    for item in result.stale:
        print(
            f"STALE {item.id} {item.key.rule} {item.key.path} {item.key.occurrence}"
        )


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description="Check OMI architecture constraints against exact debt.")
    default_root = Path(__file__).resolve().parents[1]
    value.add_argument("--repo-root", type=Path, default=default_root)
    value.add_argument("--constraints", type=Path)
    value.add_argument("--debt", type=Path)
    value.add_argument("--format", choices=("text", "json"), default="text")
    value.add_argument(
        "--report-only",
        action="store_true",
        help="List actual violations without enforcing the debt manifest.",
    )
    return value


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        result = evaluate(args.repo_root, args.constraints, args.debt)
    except ArchitectureConfigError as exc:
        print(f"Architecture guard configuration error: {exc}", file=sys.stderr)
        return 2
    if args.format == "json":
        print(evaluation_json(result))
    else:
        print_text(result, report_only=args.report_only)
    return 0 if args.report_only or result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
