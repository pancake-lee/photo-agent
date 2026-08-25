from pathlib import Path
from types import SimpleNamespace
import unittest

from chain import evaluation
from chain import server


class TestEvaluation(unittest.TestCase):
  def test_golden_queries_default_legacy_granularity_and_reject_unknown(self):
    loaded = evaluation._load_golden_queries_from_items([
        {
            "query_text": "旧用例",
            "relevant_photos": [{"photo_id": "old.jpg", "filename": "old.jpg"}],
        },
        {
            "query_text": "新用例",
            "relevant_photos": [
                {"photo_id": "fine.jpg", "granularity": "fine"},
                {"photo_id": "coarse.jpg", "granularity": "coarse"},
            ],
        },
    ])

    assert loaded[0]["relevant_photos"][0]["granularity"] == "photo"
    assert loaded[1]["relevant_photos"][0]["granularity"] == "fine"
    assert loaded[1]["relevant_photos"][1]["granularity"] == "coarse"

    with self.assertRaisesRegex(ValueError, "未知检索粒度"):
      evaluation._load_golden_queries_from_items([
          {"query_text": "坏用例", "relevant_photos": [{"photo_id": "x", "granularity": "bad"}]}
      ])


  def test_run_evaluation_queries_each_marked_collection(self):
    monkeypatch = SimpleNamespace(
        setattr=lambda obj, name, value: setattr(obj, name, value),
    )
    class FakeEmbedder:
        total_tokens = 0

        def __init__(self, **kwargs):
            pass

        def embed_texts(self, questions):
            return [SimpleNamespace(tolist=lambda: [1.0])]

    class FakeStore:
        stores = {}

        def __init__(self, persist_dir, collection_name):
            self.collection_name = collection_name
            self.stores[collection_name] = self

        def query(self, query_embeddings, n_results):
            ids = {
                "photos": "photo-uuid",
                "photos_burst_fine": "fine-uuid",
                "photos_burst_coarse": "coarse-uuid",
            }
            return [{"metadata": {"photo_id": ids[self.collection_name]}, "distance": 0.1}]

    old = (evaluation.embedder.Embedder, evaluation.chroma_client.ChromaPhotoStore,
           evaluation._build_id_to_filename, evaluation.photo_rag._aggregate_by_photo)
    monkeypatch.setattr(evaluation.embedder, "Embedder", FakeEmbedder)
    monkeypatch.setattr(evaluation.chroma_client, "ChromaPhotoStore", FakeStore)
    monkeypatch.setattr(evaluation, "_build_id_to_filename", lambda _: {
        "photo-uuid": "photo", "fine-uuid": "fine", "coarse-uuid": "coarse",
    })
    monkeypatch.setattr(evaluation.photo_rag, "_aggregate_by_photo", lambda results, top_n: results)

    cfg = SimpleNamespace(
        go_backend_url="http://go",
        embedding_model="test",
        resolve_path=lambda path: Path("/tmp"),
    )
    result = evaluation.run_evaluation(cfg, test_queries=[{
        "question": "同一查询",
        "relevant_photos": [
            {"photo_id": "photo", "granularity": "photo"},
            {"photo_id": "fine", "granularity": "fine"},
            {"photo_id": "coarse", "granularity": "coarse"},
        ],
    }], verbose=False)

    try:
      self.assertEqual(result["details"][0]["hits"], ["photo", "fine", "coarse"])
      self.assertEqual(result["details"][0]["remaining"], [])
      self.assertEqual(set(FakeStore.stores), {"photos", "photos_burst_fine", "photos_burst_coarse"})
    finally:
      evaluation.embedder.Embedder, evaluation.chroma_client.ChromaPhotoStore, \
          evaluation._build_id_to_filename, evaluation.photo_rag._aggregate_by_photo = old


  def test_golden_photo_ref_validates_granularity(self):
    self.assertEqual(server.GoldenPhotoRef(photo_id="x", filename="x").granularity, "photo")
    self.assertEqual(server.GoldenPhotoRef(photo_id="x", filename="x", granularity="fine").granularity, "fine")
    with self.assertRaises(Exception):
      server.GoldenPhotoRef(photo_id="x", filename="x", granularity="invalid")
