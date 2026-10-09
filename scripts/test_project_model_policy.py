"""Project-selected profiles remain exact assignment fences without a model whitelist."""

import copy
import tempfile
import unittest
from pathlib import Path

import validate_contracts as contracts


class ProjectModelPolicyTests(unittest.TestCase):
    def test_public_cli_accepts_project_selected_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan, specs = contracts.make_graph_bundle(root, {"work": {}})
            profile = {
                "model": "project-model",
                "reasoning_effort": "medium",
                "service_tier": "auto",
                "selection_reason": "owner-default:ordinary-worker",
            }
            plan["model_policy"]["owner_defaults"]["ordinary_worker"] = copy.deepcopy(profile)
            plan["tasks"][0]["model_profile"] = copy.deepcopy(profile)
            specs["work"]["model_profile"] = copy.deepcopy(profile)
            path = contracts.write_graph_bundle(root, plan, specs)
            result = contracts.run_public_cli("--plan", str(path))
            self.assertEqual(result.returncode, 0, result.stderr)

            # A different non-empty choice is well formed but not authorized by this policy.
            specs["work"]["model_profile"]["model"] = "different-model"
            plan["tasks"][0]["model_profile"]["model"] = "different-model"
            path = contracts.write_graph_bundle(root, plan, specs)
            result = contracts.run_public_cli("--plan", str(path))
            self.assertEqual(result.returncode, 1)
            self.assertIn("owner-policy default", result.stderr)

    def test_owner_policy_cannot_claim_another_role(self):
        schema = contracts.load_json(Path(__file__).resolve().parents[1] / "references/contracts.schema.json")
        policy = contracts.make_model_policy()
        policy["owner_defaults"]["master"]["selection_reason"] = "owner-default:ordinary-worker"
        with self.assertRaisesRegex(contracts.ContractError, "mismatched owner"):
            contracts.validate_model_policy(policy, schema, 1)

    def test_schema_and_runtime_reject_empty_profile_values(self):
        schema = contracts.load_json(Path(__file__).resolve().parents[1] / "references/contracts.schema.json")
        for field in ("model", "reasoning_effort", "service_tier"):
            with self.subTest(field=field):
                profile = contracts.make_model_profile("master")
                profile[field] = ""
                with self.assertRaises(contracts.ContractError):
                    contracts.validate_model_profile(profile, schema)
                with self.assertRaises(contracts.ContractError):
                    contracts.validate_schema_definition(profile, schema, "model_profile", "profile")


if __name__ == "__main__":
    unittest.main()
