"""Entrypoint routing must preserve reachable normative contract checks."""

import re
import shutil
import tempfile
import unittest
from pathlib import Path

import validate_contracts as contracts


ROOT = Path(__file__).resolve().parents[1]


class DocumentRoutingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        for name in ("SKILL.md", "README.md"):
            shutil.copyfile(ROOT / name, self.root / name)
        for name in ("references", "design"):
            shutil.copytree(ROOT / name, self.root / name)
        self.schema = contracts.load_json(self.root / "references/contracts.schema.json")

    def validate(self) -> None:
        contracts.validate_documented_contracts(self.root, self.schema)

    def test_router_without_repeated_contract_details_passes(self) -> None:
        # Only the links are relevant to this check; behavior is reviewed separately.
        links = re.findall(r"\]\((references/[^\s)]+)\)",
                           (self.root / "SKILL.md").read_text())
        (self.root / "SKILL.md").write_text(
            "# Routing fixture\n" + "\n".join(f"[Reference]({link})" for link in links),
        )
        self.validate()

    def test_required_link_and_target_must_both_exist(self) -> None:
        path = self.root / "SKILL.md"
        original = path.read_text()
        for scenario in ("missing-link", "wrong-target", "missing-file"):
            with self.subTest(scenario=scenario):
                if scenario == "missing-file":
                    path.write_text(original)
                    (self.root / "references/release-sop.md").unlink()
                else:
                    replacement = "not-a-reference" if scenario == "missing-link" else "references/missing.md"
                    path.write_text(original.replace("references/release-sop.md", replacement))
                with self.assertRaisesRegex(contracts.ContractError, "required reference"):
                    self.validate()

    def test_normative_source_cannot_be_missing_or_lose_constraints(self) -> None:
        path = self.root / "references/methodology.md"
        original = path.read_text()
        path.unlink()
        with self.assertRaisesRegex(contracts.ContractError, "required reference"):
            self.validate()
        path.write_text(original.replace("zero opaque digest reuse", "removed safety requirement"))
        with self.assertRaisesRegex(contracts.ContractError, "candidate-head rerun"):
            self.validate()

    def test_template_schema_field_drift_still_fails(self) -> None:
        path = self.root / "references/templates.md"
        path.write_text(path.read_text().replace("record_revision: <positive-integer>\n", "", 1))
        with self.assertRaisesRegex(contracts.ContractError, "top-level fields drifted"):
            self.validate()


if __name__ == "__main__":
    unittest.main()
