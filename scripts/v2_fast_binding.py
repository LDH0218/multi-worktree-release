"""Non-normative local binding of FAST requests and operation receipts to v2 adoption."""

from __future__ import annotations

del annotations

import copy as _copy
import hashlib as _hashlib
import json as _json
import os as _os
import re as _re
from collections.abc import Mapping as _Mapping
from typing import Any as _Any

from v2_adoption import AdoptionError as _AdoptionError
from v2_adoption import read_active_adoption as _read_active_adoption

__all__ = ("FastBindingError", "bind_fast_request", "build_operation_receipt", "validate_fast_record")

_REQUEST_KIND = "fast-request"
_RECEIPT_KIND = "fast-operation-receipt"
_SCHEMA_VERSION = 1
_BUNDLE_LOCATOR = "adoption-bundles/{adoption_id}/adoption.json"
_DIGEST_RE = _re.compile(r"^sha256:[0-9a-f]{64}$")
_IDENTIFIER_RE = _re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$", _re.ASCII)
_TOKEN_RE = _re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$", _re.ASCII)
_IDENTITY_FIELDS = (
    "repository_id", "adoption_id", "adoption_locator", "adoption_digest", "default_protocol",
    "protocol_major", "protocol_minor", "record_family_id", "schema_identity", "validator_commit_sha",
    "validator_source_digest",
)
_BASE_REQUEST_FIELDS = frozenset(("request_id", "operation", "payload"))
_REQUEST_FIELDS = frozenset(
    ("record_kind", "schema_version", "request_id", "operation", "payload", *_IDENTITY_FIELDS, "request_digest")
)
_RECEIPT_FIELDS = frozenset(
    ("record_kind", "schema_version", "request_id", "request_digest", *_IDENTITY_FIELDS,
     "outcome", "result_digest", "receipt_digest")
)
_OUTCOMES = frozenset(("SUCCEEDED", "FAILED", "CANCELLED"))


class FastBindingError(Exception):
    """The sole public error boundary; ``code`` is stable for machine callers."""

    def __init__(self, code: str, message: str | None = None) -> None:
        self.code = code
        self.message = message or code
        super().__init__(self.message)


def _fail(code: str, message: str) -> None:
    raise FastBindingError(code, message)


def _canonical(value: _Any, code: str) -> None:
    if value is None or type(value) in (bool, int, str):
        return
    if type(value) is float or not isinstance(value, (list, dict)):
        _fail(code, "value is not a canonical JSON value")
    if isinstance(value, list):
        for item in value:
            _canonical(item, code)
        return
    if any(type(key) is not str for key in value):
        _fail(code, "object keys must be strings")
    for item in value.values():
        _canonical(item, code)


def _canonical_bytes(value: _Any, code: str) -> bytes:
    _canonical(value, code)
    try:
        return _json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        _fail(code, f"value cannot be encoded as canonical JSON: {exc}")


def _digest(value: dict[str, _Any], field: str) -> str:
    candidate = dict(value)
    candidate[field] = None
    return "sha256:" + _hashlib.sha256(_canonical_bytes(candidate, "integrity")).hexdigest()


def _check(value: _Any, pattern: _Any, label: str, code: str) -> None:
    if type(value) is not str or pattern.fullmatch(value) is None:
        _fail(code, f"{label} has an invalid value")


def _keys(value: dict[str, _Any], expected: frozenset[str], label: str, code: str) -> None:
    if any(type(key) is not str for key in value):
        _fail(code, f"{label} keys must all be strings")
    missing = sorted(expected - set(value))
    extra = sorted(set(value) - expected)
    if missing or extra:
        _fail(code, f"{label} field set invalid: missing={missing}, extra={extra}")


def _duplicate_keys(pairs: list[tuple[str, _Any]]) -> dict[str, _Any]:
    result: dict[str, _Any] = {}
    for key, value in pairs:
        if key in result:
            _fail("duplicate_keys", f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    _fail("noncanonical_value", f"non-finite JSON number: {value}")


def _read_value(value: _Any, label: str) -> dict[str, _Any]:
    prefix = "request" if label == "request" else "record"
    if isinstance(value, _Mapping):
        try:
            result = _copy.deepcopy(dict(value))
        except (TypeError, ValueError) as exc:
            _fail(f"{prefix}_shape", f"{label} is not a mapping: {exc}")
        _canonical_bytes(result, f"{prefix}_shape")
        return result
    if isinstance(value, str):
        raw = value.encode("utf-8")
    elif isinstance(value, (bytes, bytearray, memoryview)):
        raw = bytes(value)
    else:
        _fail(f"{prefix}_shape", f"{label} must be a mapping or canonical JSON bytes")
    try:
        result = _json.loads(
            raw.decode("utf-8"), object_pairs_hook=_duplicate_keys, parse_constant=_reject_constant
        )
    except FastBindingError:
        raise
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        _fail(f"{prefix}_integrity", f"{label} is not valid JSON: {exc}")
    if not isinstance(result, dict):
        _fail(f"{prefix}_shape", f"{label} must contain one JSON object")
    if _canonical_bytes(result, f"{prefix}_integrity") != raw:
        _fail("noncanonical_json", f"{label} is not canonical JSON")
    return result


def _context(record: _Any) -> dict[str, _Any]:
    try:
        context = {key: record[key] for key in _IDENTITY_FIELDS if key != "adoption_locator"}
        context["adoption_locator"] = _BUNDLE_LOCATOR.format(adoption_id=record["adoption_id"])
    except (KeyError, TypeError) as exc:
        _fail("adoption_shape", f"verified adoption identity is incomplete: {exc}")
    return context


def _active_context(state_root: str | _os.PathLike[str]) -> dict[str, _Any]:
    try:
        adoption = _read_active_adoption(state_root)
    except _AdoptionError as exc:
        _fail("adoption_" + exc.code, "active adoption could not be verified")
    return _context(adoption)


def _compare_context(record: dict[str, _Any], context: dict[str, _Any]) -> None:
    for key in _IDENTITY_FIELDS:
        if record[key] != context[key]:
            _fail("adoption_mismatch", f"bound record does not match active adoption: {key}")


def _validate_bound_request(record: dict[str, _Any], context: dict[str, _Any]) -> dict[str, _Any]:
    _keys(record, _REQUEST_FIELDS, "bound FAST request", "request_shape")
    if record["record_kind"] != _REQUEST_KIND or record["schema_version"] != _SCHEMA_VERSION:
        _fail("request_shape", "bound FAST request kind or version is unsupported")
    _check(record["request_id"], _IDENTIFIER_RE, "request_id", "request_shape")
    _check(record["operation"], _TOKEN_RE, "operation", "request_shape")
    _canonical(record["payload"], "request_shape")
    _compare_context(record, context)
    if record["request_digest"] != _digest(record, "request_digest"):
        _fail("request_integrity", "request digest does not match canonical bytes")
    return _copy.deepcopy(record)


def _validate_receipt(
    record: dict[str, _Any], context: dict[str, _Any], request: dict[str, _Any] | None
) -> dict[str, _Any]:
    _keys(record, _RECEIPT_FIELDS, "operation receipt", "receipt_shape")
    if record["record_kind"] != _RECEIPT_KIND or record["schema_version"] != _SCHEMA_VERSION:
        _fail("receipt_shape", "operation receipt kind or version is unsupported")
    if request is None:
        _fail("request_required", "receipt validation requires the bound request")
    validated_request = _validate_bound_request(request, context)
    _check(record["request_id"], _IDENTIFIER_RE, "request_id", "receipt_shape")
    _check(record["request_digest"], _DIGEST_RE, "request_digest", "receipt_shape")
    _check(record["result_digest"], _DIGEST_RE, "result_digest", "receipt_shape")
    if record["outcome"] not in _OUTCOMES:
        _fail("receipt_outcome", "operation receipt outcome is not bounded")
    _compare_context(record, context)
    _check(record["receipt_digest"], _DIGEST_RE, "receipt_digest", "receipt_integrity")
    if record["receipt_digest"] != _digest(record, "receipt_digest"):
        _fail("receipt_integrity", "receipt digest does not match canonical bytes")
    if (
        record["request_id"] != validated_request["request_id"]
        or record["request_digest"] != validated_request["request_digest"]
    ):
        _fail("receipt_linkage", "operation receipt is not linked to the supplied request")
    return _copy.deepcopy(record)


def bind_fast_request(
    request: _Mapping[str, _Any] | bytes | str, state_root: str | _os.PathLike[str]
) -> dict[str, _Any]:
    """Bind an unbound local FAST request to the currently verified adoption identity."""
    base = _read_value(request, "request")
    _keys(base, _BASE_REQUEST_FIELDS, "FAST request", "request_shape")
    _check(base["request_id"], _IDENTIFIER_RE, "request_id", "request_shape")
    _check(base["operation"], _TOKEN_RE, "operation", "request_shape")
    _canonical(base["payload"], "request_shape")
    context = _active_context(state_root)
    bound = {
        "record_kind": _REQUEST_KIND,
        "schema_version": _SCHEMA_VERSION,
        "request_id": base["request_id"],
        "operation": base["operation"],
        "payload": _copy.deepcopy(base["payload"]),
    }
    bound.update(context)
    bound["request_digest"] = _digest(bound, "request_digest")
    return _validate_bound_request(bound, context)


def build_operation_receipt(
    request: _Mapping[str, _Any] | bytes | str,
    state_root: str | _os.PathLike[str],
    *,
    outcome: str,
    result_digest: str,
) -> dict[str, _Any]:
    """Build a receipt only from a currently valid request and active adoption."""
    context = _active_context(state_root)
    validated_request = _validate_bound_request(_read_value(request, "request"), context)
    if outcome not in _OUTCOMES:
        _fail("receipt_outcome", "operation receipt outcome is not bounded")
    _check(result_digest, _DIGEST_RE, "result_digest", "receipt_shape")
    receipt = {
        "record_kind": _RECEIPT_KIND,
        "schema_version": _SCHEMA_VERSION,
        "request_id": validated_request["request_id"],
        "request_digest": validated_request["request_digest"],
        "outcome": outcome,
        "result_digest": result_digest,
    }
    receipt.update({key: context[key] for key in _IDENTITY_FIELDS})
    receipt["receipt_digest"] = _digest(receipt, "receipt_digest")
    return _validate_receipt(receipt, context, validated_request)


def validate_fast_record(
    record: _Mapping[str, _Any] | bytes | str,
    state_root: str | _os.PathLike[str],
    request: _Mapping[str, _Any] | bytes | str | None = None,
) -> dict[str, _Any]:
    """Validate a bound request or receipt against the current adoption identity."""
    context = _active_context(state_root)
    value = _read_value(record, "FAST record")
    if value.get("record_kind") == _REQUEST_KIND:
        if request is not None:
            _fail("request_shape", "a bound request cannot carry a separate receipt request")
        return _validate_bound_request(value, context)
    if value.get("record_kind") == _RECEIPT_KIND:
        supplied = None if request is None else _read_value(request, "request")
        return _validate_receipt(value, context, supplied)
    _fail("record_kind", "unknown FAST binding record kind")
