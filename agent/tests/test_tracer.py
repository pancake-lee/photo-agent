import pathlib
import tempfile
import unittest

import internal.evals.tracer as tracer_mod


class TracerTest(unittest.TestCase):
    def test_save_payload_logs_its_file_reference(self):
        with tempfile.TemporaryDirectory() as directory:
            tracer = tracer_mod.Tracer(project_root=directory, agent_data_dir="data/agent")
            with self.assertLogs("internal.evals.tracer", level="INFO") as logs:
                payload_ref = tracer.save_payload("runtime-llm.json", "{}")

            self.assertTrue((pathlib.Path(directory) / payload_ref).is_file())
            self.assertIn(payload_ref, "\n".join(logs.output))
