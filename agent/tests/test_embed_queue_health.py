import unittest
from types import SimpleNamespace
from unittest import mock

import infra.embed_queue as embed_queue
import internal.chat.photo_rag as photo_rag


class EmbedQueueQualityGateTest(unittest.TestCase):
    def test_has_trusted_description_uses_derived_vlm_status(self):
        self.assertTrue(embed_queue.EmbedQueue._has_trusted_description({"vlmStatus": "healthy"}))
        self.assertTrue(embed_queue.EmbedQueue._has_trusted_description({"vlm_status": "healthy"}))
        self.assertFalse(embed_queue.EmbedQueue._has_trusted_description({"vlmStatus": "review"}))
        self.assertFalse(embed_queue.EmbedQueue._has_trusted_description({}))


class EmbedQueueRecycleTest(unittest.TestCase):
    def test_expired_cleanup_only_removes_purged_ids_from_all_collections(self):
        queue = embed_queue.EmbedQueue.__new__(embed_queue.EmbedQueue)
        queue._go_url = "http://backend"
        queue._store = mock.Mock()
        fine = mock.Mock()
        coarse = mock.Mock()
        queue._group_stores = {"fine": fine, "coarse": coarse}
        queue._store.get_embedded_photo_ids.return_value = {"purged", "recoverable", "active"}
        fine.get_embedded_photo_ids.return_value = {"purged", "recoverable"}
        coarse.get_embedded_photo_ids.return_value = {"active"}
        response = mock.Mock(status_code=200)
        response.json.return_value = ["purged"]

        with mock.patch.object(embed_queue.requests, "get", return_value=response) as get:
            self.assertEqual(queue.cleanup_expired_recycle(), 1)
        get.assert_called_once_with(
            "http://backend/api/v1/photo-recycle/deleted-ids",
            params={"purged": "1"}, timeout=5,
        )
        queue._store.delete.assert_called_once_with(where={"photo_id": "purged"})
        fine.delete.assert_called_once_with(where={"photo_id": "purged"})
        coarse.delete.assert_not_called()


class _GroupStore:
    def __init__(self):
        self.single_calls = []
        self.cover_calls = []

    def add_single_photo(self, *args):
        self.single_calls.append(args)

    def add_group_cover(self, *args, **kwargs):
        self.cover_calls.append((args, kwargs))


class EmbedQueueBurstCollectionTest(unittest.TestCase):
    def test_unassigned_photo_is_written_to_each_selected_burst_collection(self):
        queue = embed_queue.EmbedQueue.__new__(embed_queue.EmbedQueue)
        fine_store = _GroupStore()
        coarse_store = _GroupStore()
        queue._group_stores = {"fine": fine_store, "coarse": coarse_store}
        queue._cover_groups = {}
        queue._single_profiles = {"photo-1813": {"fine", "coarse"}}

        queue._write_group_records(
            "photo-1813", ["佛像和人的合照"], [[0.1]],
            [{"description_version": "v1"}],
        )

        self.assertEqual(fine_store.single_calls[0][0], "photo-1813")
        self.assertEqual(coarse_store.single_calls[0][0], "photo-1813")
        self.assertFalse(fine_store.cover_calls)
        self.assertFalse(coarse_store.cover_calls)


class PhotoRagFilterLogTest(unittest.TestCase):
    def test_filter_input_logs_filenames_instead_of_internal_ids(self):
        cfg = SimpleNamespace(
            rag_distance_threshold=None,
            rag_auto_distance_ratio=0,
        )
        result = [{"metadata": {"photo_id": "uuid-1813"}, "distance": 0.1}]
        response = SimpleNamespace(content="ok")
        chain = SimpleNamespace(invoke=lambda _: response)

        with mock.patch.object(photo_rag, "_retrieve", return_value=result), \
             mock.patch.object(photo_rag, "_fetch_filename_map", return_value={"uuid-1813": "DSC_1813.jpg"}), \
             mock.patch.object(photo_rag, "_build_context", return_value=("context", [])), \
             mock.patch.object(photo_rag, "_build_rag_chain", return_value=chain), \
             self.assertLogs(photo_rag.logger, level="INFO") as logs:
            photo_rag.answer_question(cfg, "佛像和人的合照", granularity="fine")

        rendered = "\n".join(logs.output)
        self.assertIn("photo_ids=['DSC_1813.jpg']", rendered)
        self.assertNotIn("photo_ids=['uuid-1813']", rendered)
