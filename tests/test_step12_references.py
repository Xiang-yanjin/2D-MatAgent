import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from matagent.assistant.conversation import Conversation
from matagent.optimization_tools import OptimizationTools


class Step12References(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.workspace = Path(directory.name)
        self.session = SimpleNamespace(id="session", messages=[])
        self.chat = Conversation(self.workspace, self.session)
        self.plan = "plan-20261124T000001Z-00000001"
        self.chat.observe("update_workflow", {}, {"plan_id": self.plan})

    def test_restored_revision_authorization(self):
        chat = Conversation(self.workspace, self.session)
        tools = OptimizationTools()
        for text, allowed in [("执行刚才改好的那份计划。", True),
                              ("别执行刚才改好的那份计划。", False),
                              ("执行前给我看看", False)]:
            command, issue = chat.begin(text)
            tools.begin_request(command, chat)
            self.assertIsNone(issue)
            self.assertEqual(tools.allowed, allowed)
            if allowed:
                self.assertEqual(tools.authorized_plan, self.plan)

    def test_completed_run_survives_new_plan(self):
        self.chat.observe("execute_plan", {}, {"plan_id": self.plan, "run_id":"run-a","status":"succeeded"})
        self.chat.begin("生成新计划")
        self.chat.observe("preview_workflow", {}, {"plan_id":"plan-20261124T000002Z-00000002"})
        chat = Conversation(self.workspace, self.session)
        _, issue = chat.begin("上一次已经完成的计算用了哪个权重？")
        self.assertIsNone(issue)
        self.assertEqual(chat.binding.get("run_id"), "run-a")
