import asyncio
import pathlib
import tempfile
import unittest
import unittest.mock

import cli.server as server


class ServerHealthTest(unittest.TestCase):
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
