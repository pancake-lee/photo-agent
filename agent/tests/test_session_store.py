import sqlite3
import tempfile
import unittest
from pathlib import Path

import internal.chat.session_store as session_store


class TestSessionStore(unittest.TestCase):
    def test_message_granularity_is_persisted(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = session_store.SessionStore(str(Path(temp_dir) / "sessions.db"))
            session = store.create_session()
            store.add_message(session["session_id"], "assistant", "回答", granularity="fine")

            messages = store.get_messages(session["session_id"])

            self.assertEqual(messages[0]["granularity"], "fine")

    def test_assistant_message_trace_id_is_persisted(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = session_store.SessionStore(str(Path(temp_dir) / "sessions.db"))
            session = store.create_session()
            store.add_message(
                session["session_id"], "assistant", "回答", trace_id="trace-123",
            )

            self.assertEqual(
                store.get_session(session["session_id"])["messages"][0]["trace_id"],
                "trace-123",
            )

    def test_last_granularity_is_persisted_on_session(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "sessions.db"
            store = session_store.SessionStore(str(db_path))
            session = store.create_session()

            store.update_last_granularity(session["session_id"], "coarse")

            reopened_store = session_store.SessionStore(str(db_path))
            reopened = reopened_store.get_session(session["session_id"])
            self.assertEqual(reopened["last_granularity"], "coarse")

    def test_legacy_messages_table_migrates_granularity_column(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "sessions.db"
            conn = sqlite3.connect(db_path)
            conn.executescript("""
                CREATE TABLE sessions (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    query_type TEXT,
                    usage_json TEXT DEFAULT '{}',
                    created_at TEXT NOT NULL
                );
                INSERT INTO sessions VALUES ('legacy', '旧会话', '2026-08-27', '2026-08-27');
                INSERT INTO messages (session_id, role, content, created_at)
                VALUES ('legacy', 'assistant', '旧回复', '2026-08-27');
            """)
            conn.commit()
            conn.close()

            store = session_store.SessionStore(str(db_path))

            messages = store.get_messages("legacy")
            self.assertIsNone(messages[0]["granularity"])
            self.assertIsNone(messages[0]["trace_id"])
            self.assertEqual(store.get_session("legacy")["last_granularity"], "photo")


if __name__ == "__main__":
    unittest.main()
