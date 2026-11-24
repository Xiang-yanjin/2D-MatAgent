"""CLI status, output channels and credential-safe diagnostics."""
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from matagent import cli


class CliLoggingTests(unittest.TestCase):
    def setUp(self):
        for field in ("handlers", "level", "propagate"):
            current = getattr(cli.logger, field)
            self.addCleanup(setattr, cli.logger, field, current)
        cli.logger.handlers = []
        self.agent = MagicMock()
        self.agent.session.id = "saved-session"
        self.agent.sessions_dir = Path("sessions")
        self.agent.max_steps = 10

    def invoke(self, *args):
        stdout, stderr = StringIO(), StringIO()
        with (patch("sys.argv", ["matagent", "--demo", *args]),
              patch.object(cli, "build_agent") as build,
              redirect_stdout(stdout), redirect_stderr(stderr)):
            build.return_value.__enter__.return_value = self.agent
            try:
                code = cli.main()
            except SystemExit as exc:
                code = exc.code
        return code, stdout.getvalue(), stderr.getvalue()

    def test_model_error_logs_only_safe_fields(self):
        secret = "Bearer synthetic-test-credential"
        self.agent.run.return_value = SimpleNamespace(status="error", response=secret)
        code, out, err = self.invoke(secret)
        self.assertEqual(code, 1)
        self.assertIn("ERROR matagent event=model_call_failed session=saved-session", err)
        self.assertNotIn(secret, out + err)

    def test_success_outputs_answer_without_warnings(self):
        self.agent.run.return_value = SimpleNamespace(status="success", response="完成")
        code, out, err = self.invoke("查询")
        self.assertEqual((code, err), (0, ""))
        self.assertIn("完成", out)

    def test_step_limit_is_logged(self):
        self.agent.run.return_value = SimpleNamespace(status="max_steps", response="")
        code, _, err = self.invoke("查询")
        self.assertEqual(code, 1)
        self.assertIn("WARNING matagent event=max_steps session=saved-session", err)

    def test_truncation_keeps_partial_answer(self):
        self.agent.run.return_value = SimpleNamespace(status="truncated", response="部分回答")
        code, out, err = self.invoke("查询")
        self.assertEqual(code, 1)
        self.assertIn("部分回答", out)
        self.assertIn("event=truncated session=saved-session", err)

    def test_failed_resume_omits_requested_id_and_exception_text(self):
        secret = "synthetic-secret"
        self.agent.resume.side_effect = ValueError("Authorization: " + secret)
        code, out, err = self.invoke("--resume", secret)
        self.assertEqual(code, 2)
        self.assertIn("event=session_restore_failed", err)
        self.assertNotIn(secret, out + err)
