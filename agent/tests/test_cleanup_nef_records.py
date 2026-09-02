import importlib.util
import pathlib
import sqlite3
import tempfile
import unittest


SCRIPT_PATH = pathlib.Path(__file__).resolve().parents[1] / "cli" / "cleanup_nef_records.py"
SPEC = importlib.util.spec_from_file_location("cleanup_nef_records", SCRIPT_PATH)
cleanup = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(cleanup)


class CleanupNefRecordsTest(unittest.TestCase):
    def test_find_and_delete_only_nef_photo_records(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = pathlib.Path(directory) / "photos.db"
            with sqlite3.connect(db_path) as conn:
                conn.executescript("""
                    CREATE TABLE photos (id TEXT PRIMARY KEY, filename TEXT, file_type TEXT);
                    CREATE TABLE ai_processing_history (photo_id TEXT, status TEXT);
                    INSERT INTO photos VALUES ('jpg-1', 'DSC_001.jpg', 'jpg');
                    INSERT INTO photos VALUES ('nef-1', 'DSC_001.nef', 'NEF');
                    INSERT INTO ai_processing_history VALUES ('jpg-1', 'healthy');
                    INSERT INTO ai_processing_history VALUES ('nef-1', 'healthy');
                """)
            records = cleanup.find_nef_records(db_path)
            self.assertEqual(records, [{"id": "nef-1", "filename": "DSC_001.nef"}])
            cleanup.delete_database_records(db_path, ["nef-1"])
            with sqlite3.connect(db_path) as conn:
                self.assertEqual(conn.execute("SELECT id FROM photos ORDER BY id").fetchall(), [("jpg-1",)])
                self.assertEqual(conn.execute("SELECT photo_id FROM ai_processing_history").fetchall(), [("jpg-1",)])
