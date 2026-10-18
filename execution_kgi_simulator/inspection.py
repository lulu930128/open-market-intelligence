"""Read installed source as data. Never import SDK, site hooks, DLLs or config."""

import ast
import stat
from email.parser import Parser
from hashlib import sha256
from pathlib import Path


EXPECTED_VERSION = '2.1.0'
FILES = ('__init__.py', 'main.py', 'trading/Order.py', 'trading/pyi.py',
         'trading/_trade_base.py', 'CA.py', 'pushClient/pyTradeCom.py')
METHODS = {
    'main.py': {'login': ('__init__', 'login', '_set_Account', '_logout', '_login_info')},
    'trading/Order.py': {'OrderAPI': ('create_order', 'cancel_order', 'get_trades', 'set_event')},
    'trading/pyi.py': {'_Order': ('create_order', 'cancel_order', 'set_event')},
}
ENUMS = ('Action', 'TimeInForce', 'PriceType', 'OddLot', 'OrderCond', 'Task', 'Status')


def _source_path(root: Path, relative: str) -> Path:
    """Fixed installed-source paths only; refuse junction/symlink traversal."""
    base = root.absolute()
    path = base / relative
    if '..' in path.parts or not path.is_relative_to(base):
        raise ValueError('SDK_SOURCE_PATH_REJECTED')
    for candidate in (path, *path.parents):
        info = candidate.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError('SDK_SOURCE_REPARSE_REJECTED')
    return path


def inspect_connection_surface(root: Path):
    """Report AST locations, never SDK literal values, logs or encrypted config.

    Matches identify review targets, not safe/unsafe execution certification.
    Missing matches do not clear any qualification gate.
    """
    package = root / '.venv-kgi/Lib/site-packages/kgisuperpy'
    selectors = {
        'CA.py': {'Connect': 'NATIVE_CONNECT_FROM_RUNTIME_HOST',
                  'AutoRefresh': 'DYNAMIC_ENDPOINT_RESOLVER',
                  'Login': 'NATIVE_LOGIN', 'print': 'SDK_STDOUT',
                  'set_Account': 'ACCOUNT_BINDING'},
        'pushClient/pyTradeCom.py': {'LoadLibrary': 'NATIVE_LIBRARY_LOAD',
                                   'pyTradeCom_Connect': 'NATIVE_CONNECT',
                                   'pyTradeCom_Init': 'NATIVE_INITIALIZATION',
                                   'pyTradeCom_New': 'NATIVE_IDENTITY_INITIALIZATION',
                                   'chdir': 'SDK_CHANGES_WORKING_DIRECTORY',
                                   'pyTradeCom_SetCA_PFX': 'NATIVE_CA_PATH_SURFACE',
                                   'pyTradeCom_SetCA_PW': 'NATIVE_CA_PASSWORD_SURFACE',
                                   'pyTradeCom_Logout': 'VOID_NATIVE_LOGOUT',
                                   'pyTradeCom_GetAccounts': 'NATIVE_ACCOUNT_READBACK'},
        'main.py': {'TradeCom': 'LOGIN_INITIALIZES_NATIVE',
                    'tw_data': 'LOGIN_INITIALIZES_DATA',
                    '_STKQuoteManager': 'LOGIN_INITIALIZES_QUOTES'},
    }
    matches, hashes = {}, {}
    for relative, names in selectors.items():
        data = _source_path(root, '.venv-kgi/Lib/site-packages/kgisuperpy/' + relative).read_bytes()
        hashes[relative] = sha256(data).hexdigest()
        tree = ast.parse(data.decode('utf-8-sig'))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = (node.func.attr if isinstance(node.func, ast.Attribute)
                    else node.func.id if isinstance(node.func, ast.Name) else '')
            if name in names:
                matches.setdefault(names[name], []).append(f'{relative}:{node.lineno}')
        if relative == 'CA.py':
            # Identity-derived log names are a confinement concern even before
            # login. Emit location only; never render the expression or value.
            for node in ast.walk(tree):
                if isinstance(node, ast.JoinedStr) and any(
                    isinstance(part, ast.Constant) and isinstance(part.value, str)
                    and 'TradeCom.' in part.value for part in node.values
                ):
                    matches.setdefault('IDENTITY_DERIVED_LOG_NAME', []).append(
                        f'{relative}:{node.lineno}')
    return {'inspection': 'STATIC_AST_NO_IMPORT', 'review_locations': matches,
            'source_sha256': hashes, 'endpoint_attested': False,
            'native_output_confined': False, 'native_filesystem_confined': False}


def inspect_sdk(root: Path):
    site = root / '.venv-kgi/Lib/site-packages'
    _source_path(root, '.venv-kgi/Lib/site-packages')
    metadata = list(site.glob('kgisuperpy-*.dist-info/METADATA'))
    if len(metadata) != 1:
        return {'status': 'BLOCKED', 'reasonCodes': ['SDK_METADATA_AMBIGUOUS_OR_MISSING']}
    package = site / 'kgisuperpy'
    # Fixed allowlist: never enumerate/read broker logs, CA files or encrypted config.
    msg = Parser().parsestr(_source_path(root, metadata[0].relative_to(root).as_posix()).read_text(encoding='utf-8'))
    version = msg.get('Version')
    signatures, enums, hashes = {}, {}, {}
    for relative in FILES:
        data = _source_path(root, '.venv-kgi/Lib/site-packages/kgisuperpy/' + relative).read_bytes()
        hashes[relative] = sha256(data).hexdigest()
        tree = ast.parse(data.decode('utf-8-sig'))
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            for method in node.body:
                if (isinstance(method, ast.FunctionDef)
                        and method.name in METHODS.get(relative, {}).get(node.name, ())):
                    signatures[f'{relative}:{node.name}.{method.name}'] = ast.unparse(method.args)
            if relative == 'trading/_trade_base.py' and node.name in ENUMS:
                enums[node.name] = {item.targets[0].id: ast.literal_eval(item.value)
                    for item in node.body if isinstance(item, ast.Assign)
                    and len(item.targets) == 1 and isinstance(item.targets[0], ast.Name)}
    return {'status': 'INSPECTED' if version == EXPECTED_VERSION else 'BLOCKED',
            'reasonCodes': [] if version == EXPECTED_VERSION else ['SDK_VERSION_MISMATCH'],
            'distribution': msg.get('Name'), 'installed_version': version,
            'expected_version': EXPECTED_VERSION, 'inspection': 'STATIC_AST_NO_IMPORT',
            'sdk_imported': False, 'abi_verified': False, 'signatures': signatures,
            'enums': enums, 'source_sha256': hashes,
            'limitations': ['QTY_UNIT_UNPROVEN', 'NATIVE_ENVIRONMENT_UNVERIFIED',
                'LOGIN_INITIALIZES_DATA_AND_QUOTE', 'GET_TRADES_IS_PROCESS_CACHE',
                'PYI_IS_NOT_RUNTIME_IMPLEMENTATION']}
