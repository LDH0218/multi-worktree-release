"""Offline regression tests for the local FAST adoption binding prototype."""

from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from v2_adoption import build_adoption_record, publish_adoption
from v2_fast_binding import (
    FastBindingError,
    bind_fast_request,
    build_operation_receipt,
    validate_fast_record,
)

_COMMIT_SHA = "a" * 40
_VALIDATOR_DIGEST = "sha256:" + "b" * 64
_PUBLIC = {"FastBindingError", "bind_fast_request", "build_operation_receipt", "validate_fast_record"}
_IDENTITY = (
    "repository_id", "adoption_id", "adoption_locator", "adoption_digest", "default_protocol",
    "protocol_major", "protocol_minor", "record_family_id", "schema_identity", "validator_commit_sha",
    "validator_source_digest",
)


def canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def digest(value: dict[str, object], field: str) -> str:
    candidate = dict(value)
    candidate[field] = None
    return "sha256:" + hashlib.sha256(canonical(candidate)).hexdigest()


def make_adoption(
    adoption_id: str = "adoption-1", *, predecessor: str | None = None,
    adopted_at: str = "2026-08-30T14:00:00Z",
) -> dict[str, object]:
    return build_adoption_record(
        adoption_id=adoption_id,
        schema_identity="schema-v2",
        validator_commit_sha=_COMMIT_SHA,
        validator_source_digest=_VALIDATOR_DIGEST,
        issuer_master_id="master-1",
        adopted_at=adopted_at,
        predecessor_adoption_digest=predecessor,
    )


def make_request(request_id: str = "request-1") -> dict[str, object]:
    return {"request_id": request_id, "operation": "local-probe", "payload": {"value": 1, "tags": ["fast"]}}


def expect_code(test: unittest.TestCase, code: str, call, *args, **kwargs) -> None:
    with test.assertRaises(FastBindingError) as caught:
        call(*args, **kwargs)
    test.assertEqual(caught.exception.code, code)


class FastBindingPrototypeTests(unittest.TestCase):
    def active_root(self, directory: str) -> tuple[Path, dict[str, object]]:
        root = Path(directory).resolve()
        record = make_adoption()
        publish_adoption(record, root)
        return root, record

    def test_public_surface_is_exact_and_machine_error_is_stable(self) -> None:
        import v2_fast_binding as api

        self.assertEqual({name for name in vars(api) if not name.startswith("_")}, _PUBLIC)
        self.assertEqual(set(api.__all__), _PUBLIC)
        self.assertEqual(FastBindingError("example").code, "example")

    def test_bound_request_carries_complete_adoption_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, adoption = self.active_root(directory)
            bound = bind_fast_request(make_request(), root)
            self.assertEqual(bound["record_kind"], "fast-request")
            self.assertEqual(bound["schema_version"], 1)
            for field in _IDENTITY:
                expected = (
                    adoption[field]
                    if field != "adoption_locator"
                    else "adoption-bundles/adoption-1/adoption.json"
                )
                self.assertEqual(bound[field], expected, field)
            self.assertEqual(bound["request_digest"], digest(bound, "request_digest"))
            self.assertEqual(validate_fast_record(bound, root), bound)

    def test_binding_and_receipt_are_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, _ = self.active_root(directory)
            before = {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}
            bound = bind_fast_request(make_request(), root)
            receipt = build_operation_receipt(bound, root, outcome="SUCCEEDED", result_digest="sha256:" + "c" * 64)
            validate_fast_record(receipt, root, bound)
            after = {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}
            self.assertEqual(before, after)

    def test_missing_and_partial_adoption_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            scenarios = {"missing": base / "missing", "empty": base / "empty"}
            scenarios["empty"].mkdir()
            source, target = base / "source", base / "target"
            publish_adoption(make_adoption(), source)
            target.mkdir()
            (target / "active-adoption-pointer.json").write_bytes(
                (source / "active-adoption-pointer.json").read_bytes()
            )
            scenarios["pointer_only"] = target
            for name, root in scenarios.items():
                with self.subTest(scenario=name):
                    code = "adoption_missing" if name != "pointer_only" else "adoption_partial"
                    expect_code(self, code, bind_fast_request, make_request(), root)

    def test_adoption_integrity_is_rejected_by_the_reader_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, _ = self.active_root(directory)
            path = root / "adoption-bundles" / "adoption-1" / "adoption.json"
            value = json.loads(path.read_text())
            value["validator_commit_sha"] = "c" * 40
            path.write_bytes(canonical(value))
            expect_code(self, "adoption_integrity", bind_fast_request, make_request(), root)

    def test_unbound_request_shape_rejects_missing_unknown_and_float_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, _ = self.active_root(directory)
            cases = {}
            missing = make_request()
            missing.pop("operation")
            cases["missing"] = missing
            cases["unknown"] = {**make_request(), "extra": True}
            cases["float"] = {**make_request(), "payload": {"value": 1.0}}
            for name, request in cases.items():
                with self.subTest(scenario=name):
                    expect_code(self, "request_shape", bind_fast_request, request, root)

    def test_request_raw_json_rejects_duplicate_noncanonical_and_float_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, _ = self.active_root(directory)
            bound = bind_fast_request(make_request(), root)
            duplicate = canonical(bound).replace(
                b'"request_id":"request-1"',
                b'"request_id":"request-1","request_id":"request-1"',
                1,
            )
            noncanonical = b" " + canonical(bound)
            floating = dict(bound)
            floating["payload"] = 1.0
            raw_float = json.dumps(floating, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
            expect_code(self, "duplicate_keys", validate_fast_record, duplicate, root)
            expect_code(self, "noncanonical_json", validate_fast_record, noncanonical, root)
            expect_code(self, "record_integrity", validate_fast_record, raw_float, root)

    def test_request_digest_and_adoption_identity_tampering_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, _ = self.active_root(directory)
            bound = bind_fast_request(make_request(), root)
            tampered = copy.deepcopy(bound)
            tampered["request_digest"] = "sha256:" + "d" * 64
            expect_code(self, "request_integrity", validate_fast_record, tampered, root)
            replacements = {
                "repository_id": "other-repository",
                "adoption_id": "adoption-other",
                "adoption_locator": "adoption-bundles/other/adoption.json",
                "adoption_digest": "sha256:" + "e" * 64,
                "record_family_id": "other-family",
                "schema_identity": "schema-other",
                "validator_commit_sha": "c" * 40,
                "validator_source_digest": "sha256:" + "f" * 64,
            }
            for field, replacement in replacements.items():
                with self.subTest(field=field):
                    candidate = copy.deepcopy(bound)
                    candidate[field] = replacement
                    candidate["request_digest"] = digest(candidate, "request_digest")
                    expect_code(self, "adoption_mismatch", validate_fast_record, candidate, root)

    def test_protocol_identity_tampering_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, _ = self.active_root(directory)
            bound = bind_fast_request(make_request(), root)
            for field, replacement in (("default_protocol", "v1"), ("protocol_major", 3), ("protocol_minor", 1)):
                with self.subTest(field=field):
                    candidate = copy.deepcopy(bound)
                    candidate[field] = replacement
                    candidate["request_digest"] = digest(candidate, "request_digest")
                    expect_code(self, "adoption_mismatch", validate_fast_record, candidate, root)

    def test_changed_active_adoption_rejects_old_request_and_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, first = self.active_root(directory)
            bound = bind_fast_request(make_request(), root)
            receipt = build_operation_receipt(bound, root, outcome="SUCCEEDED", result_digest="sha256:" + "c" * 64)
            second = make_adoption(
                "adoption-2", predecessor=first["adoption_digest"], adopted_at="2026-08-30T14:01:00Z"
            )
            publish_adoption(second, root)
            expect_code(self, "adoption_mismatch", validate_fast_record, bound, root)
            expect_code(
                self, "adoption_mismatch", build_operation_receipt, bound, root,
                outcome="SUCCEEDED", result_digest="sha256:" + "c" * 64,
            )
            expect_code(self, "adoption_mismatch", validate_fast_record, receipt, root, bound)

    def test_receipt_binds_exact_validated_request_and_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, adoption = self.active_root(directory)
            bound = bind_fast_request(make_request(), root)
            receipt = build_operation_receipt(bound, root, outcome="FAILED", result_digest="sha256:" + "d" * 64)
            self.assertEqual(receipt["request_digest"], bound["request_digest"])
            self.assertEqual(receipt["request_id"], bound["request_id"])
            self.assertEqual(receipt["adoption_id"], adoption["adoption_id"])
            self.assertEqual(receipt["receipt_digest"], digest(receipt, "receipt_digest"))
            self.assertEqual(validate_fast_record(receipt, root, bound), receipt)

    def test_receipt_requires_bound_current_request(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, _ = self.active_root(directory)
            expect_code(
                self, "request_shape", build_operation_receipt, make_request(), root,
                outcome="SUCCEEDED", result_digest="sha256:" + "c" * 64,
            )
            bound = bind_fast_request(make_request(), root)
            receipt = build_operation_receipt(bound, root, outcome="SUCCEEDED", result_digest="sha256:" + "c" * 64)
            expect_code(self, "request_required", validate_fast_record, receipt, root)
            unvalidated = make_request()
            expect_code(self, "request_shape", validate_fast_record, receipt, root, unvalidated)

    def test_receipt_outcome_and_result_digest_are_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, _ = self.active_root(directory)
            bound = bind_fast_request(make_request(), root)
            for name, outcome, result in (
                ("unknown_outcome", "UNKNOWN", "sha256:" + "c" * 64),
                ("missing_result", "SUCCEEDED", None),
                ("bad_result", "SUCCEEDED", "not-a-digest"),
            ):
                with self.subTest(scenario=name):
                    kwargs = {"outcome": outcome, "result_digest": result}
                    code = "receipt_outcome" if name == "unknown_outcome" else "receipt_shape"
                    expect_code(self, code, build_operation_receipt, bound, root, **kwargs)

    def test_receipt_integrity_and_linkage_tampering_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, _ = self.active_root(directory)
            bound = bind_fast_request(make_request(), root)
            receipt = build_operation_receipt(bound, root, outcome="CANCELLED", result_digest="sha256:" + "c" * 64)
            bad_digest = copy.deepcopy(receipt)
            bad_digest["receipt_digest"] = "sha256:" + "e" * 64
            expect_code(self, "receipt_integrity", validate_fast_record, bad_digest, root, bound)
            bad_link = copy.deepcopy(receipt)
            bad_link["request_digest"] = "sha256:" + "f" * 64
            bad_link["receipt_digest"] = digest(bad_link, "receipt_digest")
            expect_code(self, "receipt_linkage", validate_fast_record, bad_link, root, bound)
            wrong_request = bind_fast_request(make_request("request-2"), root)
            expect_code(self, "receipt_linkage", validate_fast_record, receipt, root, wrong_request)

    def test_receipt_raw_json_rejects_duplicate_and_noncanonical_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, _ = self.active_root(directory)
            bound = bind_fast_request(make_request(), root)
            receipt = build_operation_receipt(bound, root, outcome="SUCCEEDED", result_digest="sha256:" + "c" * 64)
            duplicate = canonical(receipt).replace(
                b'"request_id":"request-1"',
                b'"request_id":"request-1","request_id":"request-1"',
                1,
            )
            noncanonical = b"\n" + canonical(receipt)
            expect_code(self, "duplicate_keys", validate_fast_record, duplicate, root, bound)
            expect_code(self, "noncanonical_json", validate_fast_record, noncanonical, root, bound)


if __name__ == "__main__":
    unittest.main()
