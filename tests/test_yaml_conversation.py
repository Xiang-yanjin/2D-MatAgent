"""Plan selection and revision through the same production conversation entry point."""
from contextlib import redirect_stdout, redirect_stderr
import io
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest.mock import patch

from matsimpy.ai.provider import ChatMessage, ChatResponse, ToolCall
from matagent.assistant.agent import build_agent
from matagent.cli import main
from matagent.planning.single_task import PlanStore
from matagent.potentials.store import PotentialStore
from test_yaml_plans import model_fixture, structure_fixture


class YamlProvider:
    model = "yaml-test-model"

    def chat(self, messages, tools):
        if messages[-1].role != "user":
            return ChatResponse(ChatMessage.assistant(messages[-1].content))
        question = messages[-1].content
        state = json.loads(messages[0].content.split("当前会话引用（仅作定位，结果仍需调用工具重读）：\n")[1])
        if "建立" in question:
            name, args = "create_structure", {"prototype":"mos2"}
        elif "更严格" in question:
            return ChatResponse(ChatMessage.assistant("你希望把 fmax 设为多少 eV/Å？"))
        elif "执行" in question:
            name, args = "execute_plan", {"plan_id":state["resolved_for_this_turn"]["plan_id"]}
        elif "改成" in question:
            name, args = "update_optimization_plan", {"plan_id":state["resolved_for_this_turn"]["plan_id"],
                                                      "fmax":0.015, "steps":50}
        else:
            name, args = "preview_optimization", {"fmax":0.02, "steps":100, "potential_source":"project_default",
                                                   "device":"cpu"}
        call = ToolCall("yaml-" + str(len(messages)), name, args)
        return ChatResponse(ChatMessage.assistant("", [call]), [call], "tool_calls")


class YamlConversationTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.workspace = Path(tmp.name)
        self.selected = model_fixture(self.workspace)

    def cli(self, questions=None, arguments=()):
        out = io.StringIO()
        with patch.object(sys, "argv", ["matagent", "--workspace",str(self.workspace),*arguments]), \
             patch("matagent.cli.configured_provider", return_value=YamlProvider()), \
             patch("builtins.input", side_effect=questions), redirect_stdout(out), redirect_stderr(out):
            code = main()
        self.assertEqual(code,0,out.getvalue())
        path = Path(re.findall(r"\[会话\] (.+\.json)",out.getvalue())[-1])
        return json.loads(path.read_text()), out.getvalue()

    def test_cli_full_chain_and_resume_reuse_same_plan_without_calculation(self):
        session, _ = self.cli(["建立 MoS₂ 单层","用刚才建的结构和项目默认模型生成计划，CPU，fmax=0.02，steps=100",
                               "把力阈值改成 0.015，最多 50 步，其他不变","给我看最终 YAML","/exit"])
        results = [json.loads(m["content"]) for m in session["messages"] if m["role"]=="tool"]
        plans = [r for r in results if r.get("kind")=="single_optimization"]
        original, updated = plans[:2]
        self.assertEqual(updated["parameters"],{"fmax":0.015,"steps":50})
        self.assertEqual(updated["parent_id"],original["plan_id"])
        self.assertEqual(len(list((self.workspace/".matagent/plans").glob("plan-*"))),2)
        resumed, _ = self.cli(arguments=["--resume",session["id"],"这份计划用了哪个权重，结构文件在哪里？"])
        last = next(json.loads(m["content"]) for m in reversed(resumed["messages"]) if m["role"]=="tool")
        self.assertEqual(last["plan_id"],updated["plan_id"])
        self.assertEqual(last["potential"]["source_path"],self.selected["source_path"])
        self.cli(arguments=["--resume",session["id"],"执行刚才的计划"])
        self.assertFalse((self.workspace/"runs").exists())
        self.assertTrue(all(not (p/"execution").exists() for p in (self.workspace/".matagent/plans").glob("plan-*")))

    def test_missing_structure_preserves_parameters_and_multiple_objects_require_choice(self):
        with build_agent(YamlProvider(),self.workspace) as agent:
            result=agent.run("用项目默认模型生成计划，fmax=0.02，steps=100")
            self.assertEqual(result.tool_calls[0].result["status"],"needs_clarification")
            self.assertEqual(agent.conversation.references["pending_plan_inputs"]["steps"],100)
            agent.run("建立 MoS₂ 单层")
            result=agent.run("用刚才建的结构生成计划")
            self.assertEqual(result.tool_calls[0].result["parameters"]["steps"],100)
            self.assertEqual(agent.conversation.references["pending_plan_inputs"],{})
            before=list((self.workspace/".matagent/plans").glob("plan-*"))
            result=agent.run("把精度提高一点，更严格")
            self.assertFalse(result.tool_calls)
            self.assertIn("多少",result.response)
            self.assertEqual(before,list((self.workspace/".matagent/plans").glob("plan-*")))
            # Restore two candidate structures; the model is not allowed to choose one.
            first=structure_fixture(self.workspace)
            second=structure_fixture(self.workspace,"graphene")
            agent.conversation.references["structure_ids"]=[first,second]
            agent.conversation.references["active_object_kind"]="structure"
            result=agent.run("生成一个优化计划")
            self.assertEqual(result.tool_calls[0].result["status"],"needs_clarification")

    def test_project_default_is_distinct_from_session_and_invalid_defaults_are_not_replaced(self):
        other=model_fixture(self.workspace,seed=2)
        with build_agent(YamlProvider(),self.workspace) as agent:
            sid=structure_fixture(self.workspace)
            agent.conversation.references.update(structure_ids=[sid],potential_selection=self.selected)
            result=agent.run("用当前结构和项目默认模型生成计划")
            self.assertEqual(result.tool_calls[0].result["potential"]["potential_id"],other["potential_id"])
            self.assertEqual(agent.conversation.references["potential_selection"],self.selected)
            Path(other["source_path"]).unlink()
            result=agent.run("用当前结构和项目默认模型生成另一份计划")
            self.assertEqual(result.tool_calls[0].result["status"],"needs_validation")
            self.assertEqual(len(list((self.workspace/".matagent/plans").glob("plan-*"))),1)

    def test_query_refresh_reports_missing_yaml_and_cannot_recreate_or_load(self):
        with build_agent(YamlProvider(),self.workspace) as agent:
            agent.run("建立 MoS₂ 单层")
            result=agent.run("生成优化计划")
            pid=result.tool_calls[0].result["plan_id"]
            (PlanStore(self.workspace).directory(pid)/"workflow.yaml").unlink()
            session_id=agent.session.id
        with build_agent(YamlProvider(),self.workspace) as resumed:
            resumed.resume(session_id)
            result=resumed.run("这份计划的 YAML 在哪里？")
            self.assertEqual(result.tool_calls[0].name,"inspect_plan")
            self.assertFalse(result.tool_calls[0].result["validation"]["passed"])
            self.assertIsNone(result.tool_calls[0].result["yaml"])
            self.assertEqual(result.tool_calls[0].result["status"],"blocked")
            self.assertEqual(len(list((self.workspace/".matagent/plans").glob("plan-*"))),1)

    def test_explicit_references_and_planning_queries_cannot_be_overridden_by_model(self):
        class WrongProvider:
            def chat(self,messages,tools):
                if messages[-1].role!="user":
                    return ChatResponse(ChatMessage.assistant(messages[-1].content))
                call=ToolCall("wrong","validate_potential",{"potential_id":self.selected["potential_id"]})
                return ChatResponse(ChatMessage.assistant("",[call]),[call],"tool_calls")
        provider=WrongProvider()
        provider.selected=self.selected
        with build_agent(provider,self.workspace) as agent:
            with patch("matagent.potentials.validation.validate") as load:
                result=agent.run("生成 YAML，只给我看计划")
                self.assertIn("不自动加载",result.tool_calls[0].result["error"])
                load.assert_not_called()

    def test_model_cannot_guess_structure_or_ignore_explicit_gpu_and_cell_requests(self):
        first = structure_fixture(self.workspace)
        second = structure_fixture(self.workspace, "graphene")
        class GuessingProvider:
            def chat(self, messages, tools):
                if messages[-1].role != "user":
                    return ChatResponse(ChatMessage.assistant(messages[-1].content))
                call = ToolCall("guess", "preview_optimization",
                                {"structure_id": first, "device": "cpu", "potential_source": "project_default"})
                return ChatResponse(ChatMessage.assistant("", [call]), [call], "tool_calls")
        for question, field in (("从刚才的候选生成计划", "structure_id"),
                                ("在 GPU 上生成一个优化计划", "device"),
                                ("生成一个松弛晶胞的优化计划", "constraints")):
            with self.subTest(question=question), build_agent(GuessingProvider(), self.workspace) as agent:
                agent.conversation.references["structure_ids"] = [first, second]
                result = agent.run(question)
                self.assertEqual(result.tool_calls[0].result["issues"][0]["field"], field)
        self.assertFalse((self.workspace / ".matagent/plans").exists())
