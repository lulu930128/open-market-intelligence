"""Read installed source as data. Never import SDK, site hooks, DLLs or config."""

import ast
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


def inspect_sdk(root: Path):
    site = root / '.venv-kgi/Lib/site-packages'
    metadata = list(site.glob('kgisuperpy-*.dist-info/METADATA'))
    if len(metadata) != 1:
        return {'status': 'BLOCKED', 'reasonCodes': ['SDK_METADATA_AMBIGUOUS_OR_MISSING']}
    package = site / 'kgisuperpy'
    # Fixed allowlist: never enumerate/read broker logs, CA files or encrypted config.
    msg = Parser().parsestr(metadata[0].read_text(encoding='utf-8'))
    version = msg.get('Version')
    signatures, enums, hashes = {}, {}, {}
    for relative in FILES:
        data = (package / relative).read_bytes()
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
    return {'status': 'PASS' if version == EXPECTED_VERSION else 'BLOCKED',
            'reasonCodes': [] if version == EXPECTED_VERSION else ['SDK_VERSION_MISMATCH'],
            'distribution': msg.get('Name'), 'installed_version': version,
            'expected_version': EXPECTED_VERSION, 'inspection': 'STATIC_AST_NO_IMPORT',
            'sdk_imported': False, 'abi_verified': False, 'signatures': signatures,
            'enums': enums, 'source_sha256': hashes,
            'limitations': ['QTY_UNIT_UNPROVEN', 'NATIVE_ENVIRONMENT_UNVERIFIED',
                'LOGIN_INITIALIZES_DATA_AND_QUOTE', 'GET_TRADES_IS_PROCESS_CACHE',
                'PYI_IS_NOT_RUNTIME_IMPLEMENTATION']}
