"""Offline regressions for the Chinese run-query agent."""

import json
from pathlib import Path
import shutil
import tempfile
import unittest

from matagent.assistant.agent import build_agent
from matagent.assistant.demo_provider import DemoProvider
from matagent.structures.tools import TOOL_NAMES
from matagent.potentials.tools import TOOL_NAMES as POTENTIAL_TOOLS
from matagent.planning.plan_tools import PLAN_TOOLS
from matagent.planning.workflow_tools import WORKFLOW_TOOLS
from matsimpy.ai.provider import ChatMessage, ChatResponse, ToolCall


PROJECT = Path(__file__).resolve().parents[1]
SAMPLE = PROJECT / "examples" / "mos2" / "runs" / "20261120T143706Z-09f1c9a4"


class RepeatingProvider:
    """Keep calling a read tool so the loop must enforce its limit."""

    model = "test-repeating"

    def __init__(self):
        self.advertised = []

    def chat(self, messages, tools):
        self.advertised.append({item["function"]["name"] for item in tools})
        call = ToolCall(f"repeat-{len(self.advertised)}", "list_runs", {"limit": 1})
        return ChatResponse(ChatMessage.assistant("", [call]), [call], "tool_calls")


class RunAgentTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.workspace = Path(directory.name)
        self.run = self.workspace / "runs" / SAMPLE.name
        shutil.copytree(SAMPLE, self.run)
        self.manifest = self.run / "run.json"

    def test_queries_read_the_real_record_and_report_unknown_id(self):
        expected = json.loads(self.manifest.read_text(encoding="utf-8"))
        runs = self.workspace / "runs"

        def files():
            return {p.relative_to(runs): p.read_bytes() for p in runs.rglob("*") if p.is_file()}

        # A newer record for another composition must not hide the MoS₂ sample.
        other = runs / "other-material"
        other.mkdir()
        other_record = {"started_utc": "2099-01-01T00:00:00Z",
                        "io_checks": {"workflow_input": {"species": ["W", "S", "S"]}}}
        (other / "run.json").write_text(json.dumps(other_record), encoding="utf-8")
        before = files()
        with build_agent(DemoProvider(), workspace=self.workspace) as agent:
            latest = agent.run("上次 MoS₂ 优化收敛了吗？最终最大原子力是多少，证据在哪？")
            self.assertEqual(latest.status, "success", latest.response)
            self.assertEqual(latest.tools, ("list_runs", "read_run"))
            listing, detail = latest.tool_calls
            self.assertEqual(listing.arguments, {"limit": 1, "formula": "MoS2"})
            self.assertEqual(detail.arguments, {"run_id": SAMPLE.name})
            for field in ("converged", "energy_eV", "atomic_fmax_eV_per_A"):
                self.assertEqual(detail.result[field], expected[field])
            self.assertEqual(detail.result["model"], expected["actual_backend"]["model"])
            self.assertEqual(detail.result["units"]["atomic_fmax_eV_per_A"], "eV/Å")
            self.assertEqual(self.workspace / detail.result["evidence"]["raw_result"],
                             self.run / expected["raw_result"])
            self.assertIn(detail.result["evidence"]["record"], latest.response)
            self.assertIn(str(expected["atomic_fmax_eV_per_A"]), latest.response)

            unknown = "20990101T000000Z-deadbeef"
            absent = agent.run(f"查看运行编号 {unknown}")
            self.assertEqual(absent.status, "success", absent.response)
            self.assertEqual(absent.tools, ("read_run",))
            self.assertEqual(absent.tool_calls[0].arguments, {"run_id": unknown})
            self.assertIn(f"runs/{unknown}", absent.tool_calls[0].result["missing"])
            self.assertIn(unknown, absent.response)
            self.assertNotIn(str(expected["atomic_fmax_eV_per_A"]), absent.response)
        self.assertEqual(files(), before)

    def test_missing_data_does_not_inherit_other_force_or_requested_model(self):
        data = json.loads(self.manifest.read_text(encoding="utf-8"))
        data["atomic_fmax_eV_per_A"] = None
        data["actual_backend"]["model"] = None
        data["raw_result"] = "backend/absent.json"
        self.manifest.write_text(json.dumps(data), encoding="utf-8")
        with build_agent(DemoProvider(), workspace=self.workspace) as agent:
            result = agent.call_tool("read_run", {"run_id": SAMPLE.name}).content()
        self.assertIsNone(result["atomic_fmax_eV_per_A"])
        self.assertIsNone(result["model"])
        self.assertIsNone(result["evidence"]["raw_result"])
        self.assertIn("atomic_fmax_eV_per_A", result["missing"])
        self.assertIn("actual_backend.model", result["missing"])
        self.assertTrue(any("raw_result" in item for item in result["missing"]))

    def test_only_project_tools_are_available_and_loop_stops(self):
        provider = RepeatingProvider()
        with build_agent(provider, workspace=self.workspace) as agent:
            result = agent.run("列出运行记录")
            self.assertFalse(agent.call_tool("search_tools", {"query": "structure"}).ok)
            self.assertFalse(agent.call_tool("read_structure", {"path": "initial.vasp"}).ok)
        self.assertEqual(provider.advertised, [{"list_runs", "read_run", "preview_optimization", "execute_plan", "physics_guard", *TOOL_NAMES, *POTENTIAL_TOOLS, *PLAN_TOOLS, *WORKFLOW_TOOLS}] * 10)
        self.assertEqual(result.status, "max_steps")
        self.assertEqual(result.tools, ("list_runs",) * 10)


if __name__ == "__main__":
    unittest.main()
