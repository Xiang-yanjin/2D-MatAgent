"""Deterministic protocol regression through the production Agent session."""
import json
import tempfile
from pathlib import Path
import unittest
from matsimpy.ai.provider import ChatMessage,ChatResponse,ToolCall
from matagent.assistant.agent import build_agent
from test_yaml_plans import structure_fixture,model_fixture

class Provider:
    model="dag-protocol-fixture"
    def chat(self,messages,tools):
        if messages[-1].role!="user":return ChatResponse(ChatMessage.assistant(messages[-1].content))
        q=messages[-1].content
        state=json.loads(messages[0].content.split("当前会话引用（仅作定位，结果仍需调用工具重读）：\n")[1])
        if "更精确" in q:return ChatResponse(ChatMessage.assistant("请给出新的 fmax（eV/Å）。"))
        if "删除" in q:
            name,args="update_workflow",{"plan_id":state["resolved_for_this_turn"]["plan_id"],"remove_nodes":["ph"]}
        elif "执行" in q:
            name,args="execute_plan",{"plan_id":state["resolved_for_this_turn"]["plan_id"]}
        else:
            name,args="preview_workflow",{"nodes":[
                {"id":"opt","capability":"optimization","parameters":{"relax_cell":False,"steps":50}},
                {"id":"ph","capability":"phonon","inputs":{"structure":{"node":"opt","output":"optimized_structure","type":"structure"}}}],
                "potential_source":"project_default"}
        call=ToolCall("dag-"+str(len(messages)),name,args)
        return ChatResponse(ChatMessage.assistant("",[call]),[call],"tool_calls")

class ConversationTests(unittest.TestCase):
    def test_resume_preserves_plan_and_never_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);model_fixture(root);sid=structure_fixture(root)
            with build_agent(Provider(),root) as agent:
                agent.conversation.references.update(structure_ids=[sid],active_object_kind="structure")
                a=agent.run("创建工作流：先优化再声子，只看计划").tool_calls[-1].result
                self.assertEqual(a["kind"],"workflow_dag")
                b=agent.run("删除刚才工作流的声子分支").tool_calls[-1].result
                self.assertEqual(b["parent_id"],a["plan_id"])
                self.assertEqual([n["id"] for n in b["nodes"]],["opt"])
                session=agent.session.id
                response=agent.run("这份计划更精确一点")
                self.assertFalse(response.tool_calls)
                self.assertIn("fmax",response.response)
            with build_agent(Provider(),root) as agent:
                agent.resume(session)
                inspected=agent.run("给我看这份计划的 YAML").tool_calls[-1].result
                self.assertEqual(inspected["plan_id"],b["plan_id"])
                self.assertEqual(inspected["nodes"],b["nodes"])
                blocked=agent.run("执行刚才的计划").tool_calls[-1].result
                self.assertEqual(blocked["status"],"execution_not_supported")
            self.assertFalse((root/"runs").exists())
