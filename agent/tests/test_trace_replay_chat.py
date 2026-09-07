import tempfile
import unittest

import internal.evals.trace_replay as trace_replay
import internal.evals.tracer as tracer_mod


class TraceReplayChatTest(unittest.TestCase):
    def test_replay_keeps_route_summary_and_feedback_events(self):
        with tempfile.TemporaryDirectory() as directory:
            tracer = tracer_mod.Tracer(project_root=directory, agent_data_dir="data/agent")
            tracer.emit("chat.route_decision", {"query_type": "sql"}, module="chat")
            tracer.emit("chat.execution_summary", {
                "execution_mode": "direct_sql", "duration_ms": 12, "cost": 0.001,
            }, module="chat")
            tracer.emit("chat.feedback", {"verdict": "helpful"}, module="chat")

            steps, expired = trace_replay.replay_trace(directory, tracer.trace_id)

            self.assertFalse(expired)
            self.assertEqual([step.event for step in steps], [
                "chat.route_decision", "chat.execution_summary", "chat.feedback",
            ])
