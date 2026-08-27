import unittest
from types import SimpleNamespace
from unittest import mock

from chain.embed_queue import EmbedQueue
from chain import photo_rag


class EmbedQueueQualityGateTest(unittest.TestCase):
    def test_has_trusted_description_uses_derived_vlm_status(self):
        self.assertTrue(EmbedQueue._has_trusted_description({"vlmStatus": "healthy"}))
        self.assertTrue(EmbedQueue._has_trusted_description({"vlm_status": "healthy"}))
        self.assertFalse(EmbedQueue._has_trusted_description({"vlmStatus": "review"}))
        self.assertFalse(EmbedQueue._has_trusted_description({}))


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
        queue = EmbedQueue.__new__(EmbedQueue)
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
