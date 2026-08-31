import asyncio
import json
import pathlib
import tempfile
import unittest
import unittest.mock
from types import SimpleNamespace

import cli.server as server


class ServerHealthTest(unittest.TestCase):
    def test_cli_log_flag_enables_human_readable_console_output(self):
        import cli.photo_agent as photo_agent

        args = photo_agent._build_arg_parser().parse_args([
            "-c", "config.yaml", "--serve", "-l",
        ])

        self.assertTrue(args.console_logging)

    def test_health_reports_pricing_degradation_without_blocking_app_creation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)

            class Config:
                llm_model = "llm"
                agent_data_dir = "data/agent"
                chat_db_path = "data/agent/sqlite/chat.db"

                @staticmethod
                def resolve_path(path: str) -> pathlib.Path:
                    return root / path

                @staticmethod
                def agent_path(*parts: str) -> pathlib.Path:
                    return root.joinpath("data", "agent", *parts)

            agent = unittest.mock.MagicMock()
            agent.pricing_status = {"available": False, "error": "价格配置无效"}
            with (
                unittest.mock.patch.object(server.photo_agent, "PhotoAgent", return_value=agent),
                unittest.mock.patch.object(server.chroma_client, "ChromaPhotoStore"),
                unittest.mock.patch.object(server.embed_queue, "EmbedQueue"),
                unittest.mock.patch.object(server.threading.Thread, "start"),
            ):
                app = server.create_app(Config())
                health = next(
                    route.endpoint
                    for route in app.routes
                    if route.path == "/api/chat/health"
                )
                response = asyncio.run(health())

            self.assertEqual(response, {
                "status": "ok",
                "model": "llm",
                "pricing_available": False,
                "pricing_error": "价格配置无效",
            })

    def test_message_endpoint_streams_runtime_steps_before_final_and_persists_them(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)

            class Config:
                llm_model = "llm"
                agent_data_dir = "data/agent"
                chat_db_path = "data/agent/sqlite/chat.db"
                go_backend_url = "http://backend"

                @staticmethod
                def resolve_path(path: str) -> pathlib.Path:
                    return root / path

                @staticmethod
                def agent_path(*parts: str) -> pathlib.Path:
                    return root.joinpath("data", "agent", *parts)

            agent = unittest.mock.MagicMock()
            agent.pricing_status = {"available": True, "error": ""}

            def route(_question, granularity, tracer, progress_callback):
                progress_callback("runtime.started", {"message": "任务已进入多步处理"})
                progress_callback("runtime.step", {"steps": [{
                    "step": 1, "title": "查询照片", "status": "已完成",
                    "decision": "先找候选", "result": "找到 3 张候选", "facts": [], "details": {},
                }]})
                return {"answer": "已完成", "query_type": "runtime", "photos": []}

            agent.route.side_effect = route
            with (
                unittest.mock.patch.object(server.photo_agent, "PhotoAgent", return_value=agent),
                unittest.mock.patch.object(server.chroma_client, "ChromaPhotoStore"),
                unittest.mock.patch.object(server.embed_queue, "EmbedQueue"),
                unittest.mock.patch.object(server.threading.Thread, "start"),
                unittest.mock.patch.object(server, "_build_chat_asset_snapshot", return_value=[]),
            ):
                app = server.create_app(Config())

            session = app.state.store.create_session()
            endpoint = next(route.endpoint for route in app.routes if route.path.endswith("/messages") and route.methods == {"POST"})
            tracer = unittest.mock.MagicMock(trace_id="trace-123")
            req = SimpleNamespace(app=app, state=SimpleNamespace(tracer=tracer))
            response = asyncio.run(endpoint(
                session["session_id"], server.SendMessageRequest(question="发帖"), req,
            ))

            async def read_events():
                chunks = []
                async for chunk in response.body_iterator:
                    chunks.append(chunk)
                return "".join(chunks)

            raw = asyncio.run(read_events())
            names = [block.split("\n", 1)[0].split(": ", 1)[1] for block in raw.strip().split("\n\n")]
            self.assertEqual(names, ["accepted", "runtime.started", "runtime.step", "final"])
            final = json.loads(raw.strip().split("\n\n")[-1].split("data: ", 1)[1])
            self.assertEqual(final["runtime_steps"][0]["title"], "查询照片")
            messages = app.state.store.get_messages(session["session_id"])
            self.assertEqual(messages[-1]["runtime_steps"], final["runtime_steps"])
