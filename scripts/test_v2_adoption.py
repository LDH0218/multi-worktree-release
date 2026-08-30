"""Offline regression tests for the local v2 adoption prototype."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from v2_adoption import AdoptionError, build_adoption_record, publish_adoption, read_active_adoption

_COMMIT_SHA = "a" * 40
_VALIDATOR_DIGEST = "sha256:" + "b" * 64
_PUBLIC = {"AdoptionError", "build_adoption_record", "publish_adoption", "read_active_adoption"}


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(value: dict[str, object], field: str) -> str:
    candidate = dict(value)
    candidate[field] = None
    return "sha256:" + hashlib.sha256(canonical(candidate)).hexdigest()


def bundle(root: Path, adoption_id: str) -> Path:
    return root / "adoption-bundles" / adoption_id / "adoption.json"


def receipt(root: Path, sequence: int, adoption_id: str) -> Path:
    return root / "activation-receipts" / f"{sequence:020d}-{adoption_id}.json"


def pointer(root: Path) -> Path:
    return root / "active-adoption-pointer.json"


def make_record(adoption_id: str = "adoption-1", *, predecessor: str | None = None, issuer: str = "master-1", adopted_at: str = "2026-08-30T12:00:00Z", repository_id: str = "multi-worktree-release", validator_commit_sha: str = _COMMIT_SHA) -> dict[str, object]:
    return build_adoption_record(
        adoption_id=adoption_id,
        schema_identity="schema-v2",
        validator_commit_sha=validator_commit_sha,
        validator_source_digest=_VALIDATOR_DIGEST,
        issuer_master_id=issuer,
        adopted_at=adopted_at,
        repository_id=repository_id,
        predecessor_adoption_digest=predecessor,
    )


def expect_code(test: unittest.TestCase, code: str, call, *args, **kwargs) -> None:
    with test.assertRaises(AdoptionError) as caught:
        call(*args, **kwargs)
    test.assertEqual(caught.exception.code, code)


class AdoptionPrototypeTests(unittest.TestCase):
    def test_public_surface_and_stable_error_code(self) -> None:
        import v2_adoption as api

        self.assertEqual({name for name in vars(api) if not name.startswith("_")}, _PUBLIC)
        self.assertEqual(set(api.__all__), _PUBLIC)
        self.assertEqual(AdoptionError("example").code, "example")

    def test_successful_activation_has_only_immutable_chain_and_pointer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            record = make_record()
            result = publish_adoption(record, root)
            saved_receipt = json.loads(receipt(root, 1, "adoption-1").read_text())
            saved_pointer = json.loads(pointer(root).read_text())
            self.assertFalse(result["idempotent"])
            self.assertEqual(result["sequence"], 1)
            self.assertEqual(read_active_adoption(root), record)
            self.assertEqual(Path(result["bundle_path"]).read_bytes(), canonical(record))
            self.assertEqual(saved_receipt["receipt_digest"], digest(saved_receipt, "receipt_digest"))
            self.assertEqual(saved_pointer["pointer_digest"], digest(saved_pointer, "pointer_digest"))
            self.assertEqual(record["adoption_digest"], digest(record, "adoption_digest"))
            self.assertFalse((root / "adoption-activation-history.json").exists())

    def test_idempotence_predecessor_and_identity_binding(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            first = make_record()
            first_result = publish_adoption(first, root)
            repeated = publish_adoption(first, root)
            second = make_record("adoption-2", predecessor=first["adoption_digest"], adopted_at="2026-08-30T12:01:00Z")
            second_result = publish_adoption(second, root)
            stale = make_record("adoption-3", predecessor=first["adoption_digest"])
            conflict = make_record(predecessor=first["adoption_digest"], issuer="master-2")
            self.assertFalse(first_result["idempotent"])
            self.assertTrue(repeated["idempotent"])
            self.assertEqual(second_result["sequence"], 2)
            expect_code(self, "rollback", publish_adoption, stale, root)
            expect_code(self, "identity_conflict", publish_adoption, conflict, root)

    def test_identical_retry_recovers_all_interruption_stages(self) -> None:
        stages = ("before_bundle", "before_receipt", "after_receipt", "before_pointer", "after_pointer")
        for stage in stages:
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as directory:
                root = Path(directory).resolve()
                first = make_record()
                candidate = first
                if stage in {"before_pointer", "after_pointer"}:
                    publish_adoption(first, root)
                    candidate = make_record("adoption-2", predecessor=first["adoption_digest"], adopted_at="2026-08-30T12:01:00Z")
                expect_code(self, "interrupted", publish_adoption, candidate, root, interruption=stage)
                if stage == "after_pointer":
                    self.assertEqual(read_active_adoption(root), candidate)
                retry = publish_adoption(candidate, root)
                self.assertEqual(read_active_adoption(root), candidate)
                self.assertEqual(retry["idempotent"], stage == "after_pointer")

    def test_conflicting_retry_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            first = make_record()
            publish_adoption(first, root)
            second = make_record("adoption-2", predecessor=first["adoption_digest"])
            expect_code(self, "interrupted", publish_adoption, second, root, interruption="before_pointer")
            conflicting = make_record("adoption-2", predecessor=first["adoption_digest"], issuer="master-2")
            expect_code(self, "identity_conflict", publish_adoption, conflicting, root)
            publish_adoption(second, root)

    def test_missing_pointer_only_and_partial_states(self) -> None:
        with tempfile.TemporaryDirectory() as outer:
            base = Path(outer).resolve()
            missing = base / "missing"
            expect_code(self, "missing", read_active_adoption, missing)
            source, target = base / "source", base / "target"
            source.mkdir()
            publish_adoption(make_record(), source)
            target.mkdir()
            pointer(target).write_bytes(pointer(source).read_bytes())
            expect_code(self, "partial", read_active_adoption, target)
            partial = base / "partial"
            (partial / "adoption-bundles" / "adoption-1").mkdir(parents=True)
            expect_code(self, "partial", read_active_adoption, partial)
            receipt_only = base / "receipt-only"
            (receipt_only / "activation-receipts").mkdir(parents=True)
            receipt_only_path = receipt(source, 1, "adoption-1")
            receipt(receipt_only, 1, "adoption-1").write_bytes(receipt_only_path.read_bytes())
            expect_code(self, "partial", read_active_adoption, receipt_only)

    def test_pointer_rollback_gap_and_receipt_link_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as outer:
            base = Path(outer).resolve()
            for scenario in ("pointer_rollback", "receipt_gap", "receipt_link"):
                with self.subTest(scenario=scenario):
                    root = base / scenario
                    root.mkdir()
                    first = make_record()
                    first_result = publish_adoption(first, root)
                    second = make_record("adoption-2", predecessor=first["adoption_digest"])
                    publish_adoption(second, root)
                    if scenario == "pointer_rollback":
                        pointer(root).write_bytes(canonical(first_result["pointer"]))
                    elif scenario == "receipt_gap":
                        receipt(root, 1, "adoption-1").unlink()
                    else:
                        path = receipt(root, 2, "adoption-2")
                        value = json.loads(path.read_text())
                        value["predecessor_receipt_digest"] = "sha256:" + "c" * 64
                        value["receipt_digest"] = digest(value, "receipt_digest")
                        path.write_bytes(canonical(value))
                    expect_code(self, "rollback", read_active_adoption, root)

    def test_integrity_tampering_duplicate_and_noncanonical_json(self) -> None:
        scenarios = ("locator_escape", "pointer_digest", "bundle_digest", "duplicate_keys", "noncanonical")
        for scenario in scenarios:
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as directory:
                root = Path(directory).resolve()
                record = make_record()
                publish_adoption(record, root)
                if scenario == "locator_escape":
                    value = json.loads(pointer(root).read_text())
                    value["locator"] = "../outside/adoption.json"
                    value["pointer_digest"] = digest(value, "pointer_digest")
                    pointer(root).write_bytes(canonical(value))
                elif scenario == "pointer_digest":
                    value = json.loads(pointer(root).read_text())
                    value["adoption_digest"] = "sha256:" + "c" * 64
                    pointer(root).write_bytes(canonical(value))
                elif scenario == "bundle_digest":
                    value = json.loads(bundle(root, "adoption-1").read_text())
                    value["validator_commit_sha"] = "c" * 40
                    bundle(root, "adoption-1").write_bytes(canonical(value))
                elif scenario == "duplicate_keys":
                    pointer(root).write_bytes(b'{"x":1,"x":2}')
                else:
                    pointer(root).write_bytes(b" {} ")
                expect_code(self, "integrity", read_active_adoption, root)

    def test_symlink_rejection_for_root_components_and_managed_files(self) -> None:
        if not hasattr(os, "symlink"):
            self.skipTest("symlinks are unavailable")
        with tempfile.TemporaryDirectory() as outer:
            base = Path(outer).resolve()
            real = base / "real"
            real.mkdir()
            link = base / "link"
            link.symlink_to(real, target_is_directory=True)
            expect_code(self, "symlink", publish_adoption, make_record(), link / "new")
            root = base / "root"
            root.mkdir()
            record = make_record()
            publish_adoption(record, root)
            outside = base / "outside.json"
            outside.write_bytes(canonical(record))
            managed = bundle(root, "adoption-1")
            managed.unlink()
            managed.symlink_to(outside)
            expect_code(self, "symlink", read_active_adoption, root)

    def test_legacy_filename_invalid_inputs_and_repository_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            publish_adoption(make_record(), root)
            (root / "adoption-activation-history.json").write_bytes(b"{}")
            expect_code(self, "integrity", read_active_adoption, root)
            expect_code(self, "validation", build_adoption_record, adoption_id="../escape", schema_identity="schema-v2", validator_commit_sha=_COMMIT_SHA, validator_source_digest=_VALIDATOR_DIGEST, issuer_master_id="master-1", adopted_at="2026-08-30T12:00:00Z")
            expect_code(self, "validation", publish_adoption, {}, root)
            expect_code(self, "validation", publish_adoption, make_record(), root, interruption="unknown")
            first = make_record()
            publish_adoption(first, root / "identity")
            other = make_record("adoption-2", predecessor=first["adoption_digest"], repository_id="other-repository")
            expect_code(self, "identity_conflict", publish_adoption, other, root / "identity")

    def test_receipt_filename_cannot_rebind_an_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            publish_adoption(make_record(), root)
            bad_name = root / "activation-receipts" / "00000000000000000001-other.json"
            bad_name.write_bytes(receipt(root, 1, "adoption-1").read_bytes())
            expect_code(self, "identity_conflict", read_active_adoption, root)


if __name__ == "__main__":
    unittest.main()
