"""Versioned JSON persistence of allowlisted immutable M1 values, never pickle."""

from dataclasses import fields, is_dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
import json
from types import UnionType
from typing import get_args, get_origin

from execution import contracts
from execution.contracts import ExecutionRejected
from . import settlement_contracts


TYPES = {name: value for name, value in vars(contracts).items()
         if isinstance(value, type) and value.__module__ == contracts.__name__
         and (is_dataclass(value) or issubclass(value, Enum))}
TYPES.update({name: value for name, value in vars(settlement_contracts).items()
              if isinstance(value, type) and value.__module__ == settlement_contracts.__name__
              and is_dataclass(value)})


def _matches(value, expected):
    origin, args = get_origin(expected), get_args(expected)
    if origin is UnionType:
        return any(_matches(value, option) for option in args)
    if origin is tuple:
        return type(value) is tuple and (all(_matches(v, args[0]) for v in value)
                                        if len(args) == 2 and args[1] is Ellipsis else
                                        len(value) == len(args) and all(_matches(v, t) for v, t in zip(value, args)))
    if origin is frozenset:
        return type(value) is frozenset and all(_matches(v, args[0]) for v in value)
    return type(value) is expected


def pack(value):
    if isinstance(value, Enum):
        return {"type": type(value).__name__, "value": value.value}
    if is_dataclass(value):
        return {"type": type(value).__name__, "fields": {
            f.name: pack(getattr(value, f.name)) for f in fields(value) if f.init
            and not (f.metadata.get('additive') and type(getattr(value, f.name)) is type(f.default)
                     and getattr(value, f.name) == f.default)}}
    if isinstance(value, (datetime, Decimal)):
        return {"type": type(value).__name__, "value": str(value)}
    if isinstance(value, (tuple, frozenset)):
        return {"type": type(value).__name__, "items": [pack(x) for x in sorted(value, key=str)]
                if isinstance(value, frozenset) else [pack(x) for x in value]}
    if isinstance(value, dict):
        return {k: pack(v) for k, v in value.items()}
    if isinstance(value, list):
        return [pack(v) for v in value]
    if value is None or type(value) in (str, int, bool):
        return value
    raise ValueError("UNSUPPORTED_PERSISTENCE_TYPE")


def unpack(value):
    if isinstance(value, list):
        return [unpack(v) for v in value]
    if not isinstance(value, dict):
        return value
    tag = value.get("type")
    if tag is None:
        return {k: unpack(v) for k, v in value.items()}
    if type(tag) is not str:
        raise ValueError("INVALID_TAG")
    if tag == "datetime":
        if set(value) != {"type", "value"} or type(value['value']) is not str:
            raise ValueError("INVALID_TIME_PAYLOAD")
        return datetime.fromisoformat(value["value"])
    if tag == "Decimal":
        if set(value) != {"type", "value"} or type(value['value']) is not str:
            raise ValueError("INVALID_DECIMAL_PAYLOAD")
        return Decimal(value["value"])
    if tag in ("tuple", "frozenset"):
        if set(value) != {"type", "items"} or type(value['items']) is not list:
            raise ValueError("INVALID_COLLECTION_PAYLOAD")
        return (tuple if tag == "tuple" else frozenset)(unpack(v) for v in value["items"])
    if tag not in TYPES:
        raise ValueError("UNKNOWN_TYPE")
    cls = TYPES[tag]
    if issubclass(cls, Enum):
        if set(value) != {"type", "value"}:
            raise ValueError("INVALID_ENUM_PAYLOAD")
        return cls(value["value"])
    expected = {f.name for f in fields(cls) if f.init}
    optional = {f.name for f in fields(cls) if f.init and f.metadata.get('additive')}
    if (set(value) != {"type", "fields"} or type(value['fields']) is not dict
            or not expected - optional <= set(value['fields']) <= expected):
        raise ValueError("INVALID_FIELDS")
    decoded = {k: unpack(v) for k, v in value["fields"].items()}
    decoded.update({f.name: f.default for f in fields(cls) if f.name in optional and f.name not in decoded})
    if any(not _matches(decoded[f.name], f.type) for f in fields(cls) if f.init):
        raise ValueError("INVALID_FIELD_TYPE")
    return cls(**decoded)


def dumps(value):
    return json.dumps({"schema": "omi.synthetic.persistence", "version": 1, "payload": pack(value)},
                      sort_keys=True, separators=(",", ":"), allow_nan=False)


def loads(value):
    def unique_pairs(pairs):
        result = {}
        for key, item in pairs:
            if key in result:
                raise ValueError("DUPLICATE_KEY")
            result[key] = item
        return result

    try:
        data = json.loads(value, object_pairs_hook=unique_pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(ValueError("INVALID_CONSTANT")))
        if (type(data) is not dict or set(data) != {"schema", "version", "payload"}
                or data['schema'] != "omi.synthetic.persistence"
                or type(data['version']) is not int or data['version'] != 1):
            raise ValueError("INVALID_SCHEMA")
        decoded = unpack(data['payload'])
        if pack(decoded) != data['payload']:
            raise ValueError("NON_CANONICAL_PAYLOAD")
        return decoded
    except (ValueError, TypeError, KeyError, ArithmeticError, RecursionError):
        raise ExecutionRejected("CORRUPT_LEDGER_PAYLOAD") from None
