"""Non-normative local v2 adoption storage: bundles, receipts, and one pointer."""

from __future__ import annotations
del annotations
import copy as _copy
import datetime as _datetime
import hashlib as _hashlib
import json as _json
import os as _os
import re as _re
import shutil as _shutil
import stat as _stat
import uuid as _uuid
from collections.abc import Mapping as _Mapping
from pathlib import Path as _Path
from typing import Any as _Any

__all__ = ("AdoptionError", "build_adoption_record", "publish_adoption", "read_active_adoption")
_RECORD_KIND, _POINTER_KIND, _RECEIPT_KIND = "repository-adoption", "active-adoption-pointer", "adoption-activation-receipt"
_SCHEMA_VERSION, _PROTOCOL_MAJOR, _PROTOCOL_MINOR = 1, 2, 0
_DEFAULT_PROTOCOL = "v2"
_BUNDLE_DIRECTORY, _BUNDLE_FILENAME = "adoption-bundles", "adoption.json"
_RECEIPT_DIRECTORY, _POINTER_FILENAME = "activation-receipts", "active-adoption-pointer.json"
_LEGACY_HISTORY_FILENAME, _RECEIPT_WIDTH = "adoption-activation-history.json", 20
_DIGEST_RE = _re.compile(r"^sha256:[0-9a-f]{64}$")
_SHA_RE = _re.compile(r"^[0-9a-f]{40}$")
_IDENTIFIER_RE = _re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$", _re.ASCII)
_TOKEN_RE = _re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$", _re.ASCII)
_RECEIPT_NAME_RE = _re.compile(r"^(?P<sequence>[0-9]+)-(?P<adoption_id>[A-Za-z0-9][A-Za-z0-9._-]{0,127})\.json$", _re.ASCII)
_TIMESTAMP_RE = _re.compile(r"^[0-9]{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12][0-9]|3[01])T(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9](?:\.[0-9]{1,6})?(?:Z|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])$")
_ADOPTION_FIELDS = frozenset("record_kind repository_id adoption_id default_protocol protocol_major protocol_minor record_family_id schema_identity validator_commit_sha validator_source_digest adopted_at issuer_master_id predecessor_adoption_digest adoption_digest".split())
_RECEIPT_FIELDS = frozenset("record_kind schema_version sequence repository_id adoption_id locator adoption_digest predecessor_adoption_digest predecessor_receipt_digest receipt_digest".split())
_POINTER_FIELDS = frozenset("record_kind schema_version sequence repository_id adoption_id locator adoption_digest predecessor_adoption_digest receipt_locator receipt_digest predecessor_receipt_digest pointer_digest".split())

class AdoptionError(Exception):
    """The sole public error type; ``code`` is stable for machine callers."""

    def __init__(self, code: str, message: str | None = None) -> None:
        self.code, self.message = code, message or code
        super().__init__(self.message)

def _fail(code: str, message: str) -> None: raise AdoptionError(code, message)

def _canonical(value: _Any, code: str = "validation") -> None:
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

def _bytes(value: _Any, code: str = "validation") -> bytes:
    _canonical(value, code)
    return _json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")

def _digest(value: _Mapping[str, _Any], field: str) -> str:
    candidate = dict(value)
    candidate[field] = None
    return "sha256:" + _hashlib.sha256(_bytes(candidate)).hexdigest()

def _check(value: _Any, pattern: _Any, label: str, code: str) -> None:
    if type(value) is not str or pattern.fullmatch(value) is None:
        _fail(code, f"{label} has an invalid value")

def _timestamp(value: _Any, code: str) -> None:
    _check(value, _TIMESTAMP_RE, "adopted_at", code)
    try:
        _datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        _fail(code, "adopted_at is not calendar-valid")

def _keys(value: dict[str, _Any], expected: frozenset[str], label: str, code: str) -> None:
    if any(type(key) is not str for key in value):
        _fail(code, f"{label} keys must all be strings")
    missing, extra = sorted(expected - set(value)), sorted(set(value) - expected)
    if missing or extra:
        _fail(code, f"{label} field set invalid: missing={missing}, extra={extra}")

def _validate_adoption(record: dict[str, _Any], code: str, digest_required: bool) -> None:
    if not isinstance(record, dict):
        _fail(code, "adoption record must be a JSON object")
    _keys(record, _ADOPTION_FIELDS, "adoption record", code)
    if (record["record_kind"], record["default_protocol"]) != (_RECORD_KIND, _DEFAULT_PROTOCOL):
        _fail(code, "unsupported adoption record kind or protocol")
    for key in ("repository_id", "adoption_id", "record_family_id", "issuer_master_id"):
        _check(record[key], _IDENTIFIER_RE, key, code)
    if type(record["protocol_major"]) is not int or record["protocol_major"] != _PROTOCOL_MAJOR or type(record["protocol_minor"]) is not int or record["protocol_minor"] != _PROTOCOL_MINOR:
        _fail(code, "unsupported protocol version")
    for key, pattern in (("schema_identity", _TOKEN_RE), ("validator_commit_sha", _SHA_RE), ("validator_source_digest", _DIGEST_RE)):
        _check(record[key], pattern, key, code)
    _timestamp(record["adopted_at"], code)
    for key in ("predecessor_adoption_digest", "adoption_digest"):
        if key == "adoption_digest" and not digest_required and record[key] is None:
            continue
        if record[key] is not None:
            _check(record[key], _DIGEST_RE, key, code)
    if digest_required and record["adoption_digest"] != _digest(record, "adoption_digest"):
        _fail(code, "adoption_digest does not match canonical record bytes")

def build_adoption_record(
    *, adoption_id: str, schema_identity: str, validator_commit_sha: str,
    validator_source_digest: str, issuer_master_id: str, adopted_at: str | None = None,
    repository_id: str = "multi-worktree-release", record_family_id: str = "mwr-v2",
    predecessor_adoption_digest: str | None = None,
) -> dict[str, _Any]:
    if adopted_at is None:
        adopted_at = _datetime.datetime.now(_datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    record: dict[str, _Any] = dict(
        record_kind=_RECORD_KIND, repository_id=repository_id, adoption_id=adoption_id,
        default_protocol=_DEFAULT_PROTOCOL, protocol_major=_PROTOCOL_MAJOR, protocol_minor=_PROTOCOL_MINOR,
        record_family_id=record_family_id, schema_identity=schema_identity,
        validator_commit_sha=validator_commit_sha, validator_source_digest=validator_source_digest,
        adopted_at=adopted_at, issuer_master_id=issuer_master_id,
        predecessor_adoption_digest=predecessor_adoption_digest, adoption_digest=None,
    )
    _validate_adoption(record, "validation", False)
    record["adoption_digest"] = _digest(record, "adoption_digest")
    _validate_adoption(record, "validation", True)
    return record

def _reject_symlinks(path: _Path, label: str) -> None:
    current = _Path(path.anchor)
    for component in path.parts[1:]:
        current /= component
        try:
            linked = _os.path.lexists(current) and _stat.S_ISLNK(_os.lstat(current).st_mode)
        except OSError as exc:
            _fail("partial", f"cannot inspect {label}: {exc}")
        if linked:
            _fail("symlink", f"{label} contains a symlink: {current}")

def _root(state_root: str | _os.PathLike[str], create: bool) -> _Path:
    if not isinstance(state_root, (str, _os.PathLike)):
        _fail("validation", "state_root must be a filesystem path")
    raw = _os.fspath(state_root)
    if not isinstance(raw, str) or not raw:
        _fail("validation", "state_root must be a non-empty text path")
    root = _Path(_os.path.abspath(_os.path.expanduser(raw)))
    _reject_symlinks(root, "state_root")
    if not _os.path.lexists(root) and not create:
        _fail("missing", "state_root does not exist")
    if not _os.path.lexists(root):
        root.mkdir(parents=True, exist_ok=True)
        _reject_symlinks(root, "state_root")
    if not root.is_dir():
        _fail("partial", "state_root is not a directory")
    return root

def _mkdir(path: _Path, label: str) -> None:
    _reject_symlinks(path, label)
    if not _os.path.lexists(path):
        path.mkdir(exist_ok=True)
    _reject_symlinks(path, label)
    if not path.is_dir():
        _fail("partial", f"{label} is not a directory")

def _fsync(path: _Path) -> None:
    try:
        fd = _os.open(_os.fspath(path), _os.O_RDONLY | getattr(_os, "O_DIRECTORY", 0))
        _os.fsync(fd)
        _os.close(fd)
    except (AttributeError, OSError):
        pass

def _cleanup(path: _Path) -> None:
    if not _os.path.lexists(path):
        return
    try:
        if path.is_dir() and not path.is_symlink():
            _shutil.rmtree(path)
        else:
            path.unlink()
    except OSError:
        pass

def _write_new(path: _Path, data: bytes) -> None:
    path.write_bytes(data)

def _stage_file(parent: _Path, name: str, data: bytes) -> _Path:
    _mkdir(parent, f"parent of {name}")
    temporary = parent / f".{name}.tmp-{_uuid.uuid4().hex}"
    try:
        _write_new(temporary, data)
        _reject_symlinks(temporary, "temporary managed file")
        _fsync(parent)
        return temporary
    except AdoptionError:
        _cleanup(temporary)
        raise

def _publish_immutable(path: _Path, data: bytes, label: str) -> None:
    temporary = _stage_file(path.parent, path.name, data)
    try:
        _reject_symlinks(path, label)
        if not _os.path.lexists(path):
            try:
                _os.rename(temporary, path)
            except FileExistsError:
                pass
        _reject_symlinks(path, label)
        if not _os.path.lexists(path) or not path.is_file():
            _fail("partial", f"{label} is not a regular file")
        if path.read_bytes() != data:
            _fail("identity_conflict", f"{label} is already bound to different bytes")
        _fsync(path.parent)
    finally:
        _cleanup(temporary)

def _duplicate_keys(pairs: list[tuple[str, _Any]]) -> dict[str, _Any]:
    result: dict[str, _Any] = {}
    for key, value in pairs:
        if key in result:
            _fail("integrity", f"duplicate JSON object key: {key}")
        result[key] = value
    return result

def _read_json(path: _Path, label: str) -> dict[str, _Any]:
    _reject_symlinks(path, label)
    if not _os.path.lexists(path):
        _fail("partial", f"missing {label}")
    if not path.is_file():
        _fail("partial", f"{label} is not a regular file")
    try:
        raw = path.read_bytes()
        parsed = _json.loads(raw.decode("utf-8"), object_pairs_hook=_duplicate_keys, parse_constant=lambda value: _fail("integrity", f"non-finite JSON number: {value}"))
    except (OSError, UnicodeDecodeError, ValueError, RecursionError) as exc:
        _fail("integrity", f"{label} is not valid canonical JSON: {exc}")
    if not isinstance(parsed, dict):
        _fail("integrity", f"{label} must contain one JSON object")
    canonical = _bytes(parsed, "integrity")
    if raw != canonical:
        _fail("integrity", f"{label} is not canonical JSON")
    return parsed

def _bundle_locator(adoption_id: str) -> str:
    _check(adoption_id, _IDENTIFIER_RE, "adoption_id", "validation")
    return f"{_BUNDLE_DIRECTORY}/{adoption_id}/{_BUNDLE_FILENAME}"

def _receipt_filename(sequence: int, adoption_id: str) -> str:
    if type(sequence) is not int or sequence < 1:
        _fail("validation", "receipt sequence must be positive")
    _check(adoption_id, _IDENTIFIER_RE, "adoption_id", "validation")
    return f"{sequence:0{_RECEIPT_WIDTH}d}-{adoption_id}.json"

def _bundle_file(directory: _Path, label: str) -> _Path:
    _reject_symlinks(directory, f"{label} directory")
    if not _os.path.lexists(directory) or not directory.is_dir():
        _fail("partial", f"{label} directory is missing or invalid")
    entries = list(directory.iterdir())
    for entry in entries:
        _reject_symlinks(entry, f"{label} entry")
    visible = [entry for entry in entries if not entry.name.startswith(".")]
    if len(visible) != 1 or visible[0].name != _BUNDLE_FILENAME:
        _fail("partial", f"{label} is incomplete or contains unknown files")
    return visible[0]

def _read_record(path: _Path, label: str) -> dict[str, _Any]:
    record = _read_json(path, label)
    _validate_adoption(record, "integrity", True)
    return record

def _scan_bundles(root: _Path) -> dict[str, dict[str, _Any]]:
    directory = root / _BUNDLE_DIRECTORY
    _reject_symlinks(directory, "adoption bundle directory")
    if not _os.path.lexists(directory):
        return {}
    if not directory.is_dir():
        _fail("partial", "adoption bundle directory is not a directory")
    entries = list(directory.iterdir())
    result: dict[str, dict[str, _Any]] = {}
    for child in entries:
        _reject_symlinks(child, "adoption bundle entry")
        if child.name.startswith("."):
            continue
        _check(child.name, _IDENTIFIER_RE, "adoption_id", "partial")
        record = _read_record(_bundle_file(child, "immutable adoption bundle"), "immutable adoption record")
        if record["adoption_id"] != child.name:
            _fail("identity_conflict", "bundle path and adoption identity differ")
        result[child.name] = record
    return result

def _receipt_for(record: _Mapping[str, _Any], sequence: int, predecessor: str | None) -> dict[str, _Any]:
    receipt: dict[str, _Any] = {
        "record_kind": _RECEIPT_KIND, "schema_version": _SCHEMA_VERSION, "sequence": sequence,
        "repository_id": record["repository_id"], "adoption_id": record["adoption_id"], "locator": _bundle_locator(record["adoption_id"]),
        "adoption_digest": record["adoption_digest"], "predecessor_adoption_digest": record["predecessor_adoption_digest"],
        "predecessor_receipt_digest": predecessor, "receipt_digest": None,
    }
    receipt["receipt_digest"] = _digest(receipt, "receipt_digest")
    return receipt

def _versioned(value: dict[str, _Any], fields: frozenset[str], kind: str, label: str) -> None:
    if not isinstance(value, dict):
        _fail("integrity", f"{label} must be a JSON object")
    _keys(value, fields, label, "integrity")
    if type(value["schema_version"]) is not int or value["schema_version"] != _SCHEMA_VERSION or value["record_kind"] != kind:
        _fail("integrity", f"unsupported {label} version or kind")

def _validate_link(value: dict[str, _Any], pointer: bool) -> dict[str, _Any]:
    kind, fields, label = (_POINTER_KIND, _POINTER_FIELDS, "active pointer") if pointer else (_RECEIPT_KIND, _RECEIPT_FIELDS, "activation receipt")
    _versioned(value, fields, kind, label)
    if type(value["sequence"]) is not int or value["sequence"] < 1:
        _fail("integrity", f"{label} sequence is invalid")
    for key in ("repository_id", "adoption_id"):
        _check(value[key], _IDENTIFIER_RE, f"{label}.{key}", "integrity")
    if value["locator"] != _bundle_locator(value["adoption_id"]):
        _fail("integrity", f"{label} locator is not canonical")
    if pointer:
        expected = f"{_RECEIPT_DIRECTORY}/{_receipt_filename(value['sequence'], value['adoption_id'])}"
        if value["receipt_locator"] != expected:
            _fail("integrity", "active pointer receipt locator is not canonical")
    required = ("adoption_digest", "receipt_digest", "pointer_digest") if pointer else ("adoption_digest", "receipt_digest")
    for key in required:
        _check(value[key], _DIGEST_RE, f"{label}.{key}", "integrity")
    for key in ("predecessor_adoption_digest", "predecessor_receipt_digest"):
        if value[key] is not None:
            _check(value[key], _DIGEST_RE, f"{label}.{key}", "integrity")
    digest_field = "pointer_digest" if pointer else "receipt_digest"
    if value[digest_field] != _digest(value, digest_field):
        _fail("integrity", f"{label} digest mismatch")
    return value

def _pointer_for(receipt: _Mapping[str, _Any]) -> dict[str, _Any]:
    pointer: dict[str, _Any] = {
        "record_kind": _POINTER_KIND, "schema_version": _SCHEMA_VERSION, "sequence": receipt["sequence"], "repository_id": receipt["repository_id"],
        "adoption_id": receipt["adoption_id"], "locator": receipt["locator"], "adoption_digest": receipt["adoption_digest"],
        "predecessor_adoption_digest": receipt["predecessor_adoption_digest"],
        "receipt_locator": f"{_RECEIPT_DIRECTORY}/{_receipt_filename(receipt['sequence'], receipt['adoption_id'])}",
        "receipt_digest": receipt["receipt_digest"], "predecessor_receipt_digest": receipt["predecessor_receipt_digest"], "pointer_digest": None,
    }
    pointer["pointer_digest"] = _digest(pointer, "pointer_digest")
    return pointer

def _scan_receipts(root: _Path, bundles: _Mapping[str, dict[str, _Any]]) -> dict[str, dict[int, dict[str, _Any]]]:
    directory = root / _RECEIPT_DIRECTORY
    _reject_symlinks(directory, "activation receipt directory")
    if not _os.path.lexists(directory):
        return {"receipts": {}, "records": {}}
    if not directory.is_dir():
        _fail("partial", "activation receipt directory is not a directory")
    entries = list(directory.iterdir())
    receipts: dict[int, dict[str, _Any]] = {}
    records: dict[int, dict[str, _Any]] = {}
    for path in entries:
        _reject_symlinks(path, "activation receipt entry")
        if path.name.startswith("."):
            continue
        match = _RECEIPT_NAME_RE.fullmatch(path.name)
        if match is None:
            _fail("partial", f"activation receipt has an invalid filename: {path.name}")
        try:
            sequence = int(match["sequence"])
        except ValueError:
            _fail("partial", "activation receipt sequence is not numeric")
        adoption_id = match["adoption_id"]
        if _receipt_filename(sequence, adoption_id) != path.name:
            _fail("partial", f"activation receipt filename is not canonical: {path.name}")
        receipt = _validate_link(_read_json(path, "immutable activation receipt"), False)
        if (receipt["sequence"], receipt["adoption_id"]) != (sequence, adoption_id):
            _fail("identity_conflict", "activation receipt filename and content differ")
        if sequence in receipts:
            _fail("identity_conflict", "duplicate activation receipt sequence")
        record = bundles.get(adoption_id)
        if record is None:
            _fail("partial", "activation receipt references a missing adoption bundle")
        if receipt["repository_id"] != record["repository_id"]:
            _fail("identity_conflict", "receipt and bundle repository identities differ")
        if receipt["adoption_digest"] != record["adoption_digest"]:
            _fail("integrity", "receipt and bundle adoption digests differ")
        if receipt["predecessor_adoption_digest"] != record["predecessor_adoption_digest"]:
            _fail("rollback", "receipt and bundle predecessor links differ")
        receipts[sequence], records[sequence] = receipt, record
    previous: tuple[dict[str, _Any], dict[str, _Any]] | None = None
    seen: set[tuple[str, str]] = set()
    for expected, sequence in enumerate(sorted(receipts), 1):
        if sequence != expected:
            _fail("rollback", "activation receipt chain has a gap")
        receipt, record = receipts[sequence], records[sequence]
        identity = (receipt["adoption_id"], receipt["adoption_digest"])
        if identity in seen:
            _fail("identity_conflict", "an adoption identity appears more than once")
        if previous is None:
            if receipt["predecessor_receipt_digest"] is not None or receipt["predecessor_adoption_digest"] is not None:
                _fail("rollback", "first activation receipt has a predecessor")
        elif (receipt["repository_id"], receipt["predecessor_receipt_digest"], receipt["predecessor_adoption_digest"]) != (previous[0]["repository_id"], previous[0]["receipt_digest"], previous[1]["adoption_digest"]):
            _fail("rollback", "activation receipt predecessor chain is not monotonic")
        seen.add(identity)
        previous = (receipt, record)
    return {"receipts": receipts, "records": records}

def _latest(chain: _Mapping[str, _Any]) -> tuple[int | None, _Any, _Any]:
    if not chain["receipts"]:
        return None, None, None
    sequence = max(chain["receipts"])
    return sequence, chain["receipts"][sequence], chain["records"][sequence]

def _load(root: _Path, strict: bool) -> dict[str, _Any]:
    legacy = root / _LEGACY_HISTORY_FILENAME
    _reject_symlinks(legacy, "legacy mutable activation history")
    if _os.path.lexists(legacy):
        _fail("integrity", "mutable activation history is not a v2 authority")
    chain = _scan_receipts(root, _scan_bundles(root))
    pointer_path = root / _POINTER_FILENAME
    pointer = None if not _os.path.lexists(pointer_path) else _validate_link(_read_json(pointer_path, "active adoption pointer"), True)
    latest, latest_receipt, _ = _latest(chain)
    if pointer is not None:
        if latest is None:
            _fail("partial", "active pointer exists without an activation receipt chain")
        if pointer["sequence"] not in chain["receipts"]:
            _fail("rollback" if pointer["sequence"] < latest else "partial", "active pointer references an unavailable activation receipt")
        if pointer != _pointer_for(chain["receipts"][pointer["sequence"]]):
            _fail("integrity", "active pointer does not match its immutable receipt")
        if strict and pointer["sequence"] < latest:
            _fail("rollback", "active pointer has rolled back to an older activation")
        if strict and pointer != _pointer_for(latest_receipt):
            _fail("integrity", "active pointer does not match the highest activation receipt")
    return {"pointer": pointer, "chain": chain}

def read_active_adoption(state_root: str | _os.PathLike[str]) -> dict[str, _Any]:
    state = _load(_root(state_root, False), True)
    if state["pointer"] is None:
        _fail("missing", "no verified active adoption exists")
    pointer = state["pointer"]
    return _copy.deepcopy(state["chain"]["records"][pointer["sequence"]])

def _stage_bundle(root: _Path, record: _Mapping[str, _Any]) -> _Path:
    parent = root / _BUNDLE_DIRECTORY
    _mkdir(parent, "adoption bundle directory")
    temporary = parent / f".{record['adoption_id']}.tmp-{_uuid.uuid4().hex}"
    try:
        temporary.mkdir()
        _write_new(temporary / _BUNDLE_FILENAME, _bytes(record))
        _fsync(temporary)
        return temporary
    except Exception:
        _cleanup(temporary)
        raise

def _ensure_bundle(root: _Path, record: _Mapping[str, _Any], interruption: str | None) -> None:
    final = root / _BUNDLE_DIRECTORY / record["adoption_id"]
    _reject_symlinks(final, "immutable adoption bundle directory")
    if _os.path.lexists(final):
        if _read_record(_bundle_file(final, "existing immutable adoption bundle"), "existing immutable adoption record") != record:
            _fail("identity_conflict", "adoption_id is already bound to different bytes")
        return
    if interruption == "before_bundle":
        _fail("interrupted", "interrupted before immutable bundle publication")
    temporary = _stage_bundle(root, record)
    try:
        _reject_symlinks(final, "immutable adoption bundle directory")
        try:
            _os.rename(temporary, final)
        except FileExistsError:
            if _read_record(_bundle_file(final, "existing immutable adoption bundle"), "existing immutable adoption record") != record:
                _fail("identity_conflict", "adoption_id is already bound to different bytes")
        else:
            _fsync(final.parent)
    finally:
        _cleanup(temporary)

def _matching(chain: _Mapping[str, _Any], record: _Mapping[str, _Any]) -> tuple[int, dict[str, _Any]] | None:
    match = None
    for sequence, receipt in chain["receipts"].items():
        if receipt["adoption_id"] == record["adoption_id"] or receipt["adoption_digest"] == record["adoption_digest"]:
            if match is not None or chain["records"][sequence] != record:
                _fail("identity_conflict", "adoption identity or digest is bound to different bytes")
            match = (sequence, receipt)
    return match

def _ensure_receipt(root: _Path, receipt: _Mapping[str, _Any], interruption: str | None) -> None:
    path = root / _RECEIPT_DIRECTORY / _receipt_filename(receipt["sequence"], receipt["adoption_id"])
    if _os.path.lexists(path):
        if _validate_link(_read_json(path, "existing immutable activation receipt"), False) != receipt:
            _fail("identity_conflict", "activation receipt is bound to different bytes")
        return
    if interruption == "before_receipt":
        _fail("interrupted", "interrupted before immutable activation receipt publication")
    _publish_immutable(path, _bytes(receipt), "immutable activation receipt")

def _publish_pointer(root: _Path, pointer: _Mapping[str, _Any]) -> None:
    path = root / _POINTER_FILENAME
    _reject_symlinks(path, "active adoption pointer")
    if _os.path.lexists(path) and not path.is_file():
        _fail("partial", "active adoption pointer is not a regular file")
    temporary = _stage_file(root, _POINTER_FILENAME, _bytes(pointer))
    try:
        _reject_symlinks(path, "active adoption pointer")
        _os.replace(temporary, path)
        _fsync(root)
    except OSError as exc:
        _fail("partial", f"cannot publish active adoption pointer: {exc}")
    finally:
        _cleanup(temporary)

def _result(root: _Path, record: _Mapping[str, _Any], pointer: _Mapping[str, _Any], sequence: int, idempotent: bool) -> dict[str, _Any]:
    return {"record": _copy.deepcopy(dict(record)), "pointer": _copy.deepcopy(dict(pointer)), "locator": pointer["locator"], "bundle_path": str(root / pointer["locator"]), "sequence": sequence, "idempotent": idempotent}

def publish_adoption(
    record: _Mapping[str, _Any], state_root: str | _os.PathLike[str], *, interruption: str | None = None
) -> dict[str, _Any]:
    """Atomically publish an immutable bundle, receipt, and active pointer."""
    stages = {None, "before_bundle", "before_receipt", "after_receipt", "before_pointer", "after_pointer"}
    if interruption not in stages:
        _fail("validation", f"unsupported interruption stage: {interruption!r}")
    if not isinstance(record, _Mapping):
        _fail("validation", "adoption record must be a mapping")
    candidate = _copy.deepcopy(dict(record))
    _validate_adoption(candidate, "validation", True)
    root = _root(state_root, True)
    state = _load(root, False)
    chain, pointer = state["chain"], state["pointer"]
    latest_sequence, latest_receipt, latest_record = _latest(chain)
    matching = _matching(chain, candidate)
    if pointer is not None and latest_receipt is not None:
        if pointer["sequence"] == latest_sequence and candidate == latest_record:
            return _result(root, candidate, pointer, latest_sequence, True)
        if pointer["sequence"] < latest_sequence and candidate != latest_record:
            _fail("rollback", "active pointer is behind a different highest receipt")
    elif pointer is None and latest_receipt is not None and candidate != latest_record:
        _fail("partial", "orphan receipt chain has no active pointer")
    if matching is not None:
        sequence, receipt = matching
        if sequence != latest_sequence or candidate != latest_record:
            _fail("rollback", "an older adoption cannot be activated again")
        _ensure_bundle(root, candidate, None)
    else:
        expected = None if latest_record is None else latest_record["adoption_digest"]
        if candidate["predecessor_adoption_digest"] != expected:
            _fail("rollback", "new adoption predecessor does not match the highest activation")
        if latest_record is not None and candidate["repository_id"] != latest_record["repository_id"]:
            _fail("identity_conflict", "new adoption changes repository identity")
        sequence = 1 if latest_sequence is None else latest_sequence + 1
        receipt = _receipt_for(candidate, sequence, None if latest_receipt is None else latest_receipt["receipt_digest"])
        _ensure_bundle(root, candidate, interruption)
    _ensure_receipt(root, receipt, interruption)
    if interruption == "after_receipt":
        _fail("interrupted", "interrupted after immutable activation receipt publication")
    if interruption == "before_pointer":
        _fail("interrupted", "interrupted before active pointer publication")
    pointer = _pointer_for(receipt)
    _publish_pointer(root, pointer)
    if interruption == "after_pointer":
        _fail("interrupted", "interrupted after active pointer publication")
    return _result(root, candidate, pointer, sequence, False)
