from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from chain import evaluation
from chain import server


class TestEvaluation(unittest.TestCase):
  def test_golden_queries_always_use_photo_granularity(self):
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
    assert loaded[1]["relevant_photos"][0]["granularity"] == "photo"
    assert loaded[1]["relevant_photos"][1]["granularity"] == "photo"


  def test_run_evaluation_queries_photo_collection(self):
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

        def get_photo_embedding_versions(self):
            return {"photo-uuid": {""}}

    old = (evaluation.embedder.Embedder, evaluation.chroma_client.ChromaPhotoStore,
           evaluation._build_photo_records, evaluation.photo_rag._aggregate_by_photo)
    monkeypatch.setattr(evaluation.embedder, "Embedder", FakeEmbedder)
    monkeypatch.setattr(evaluation.chroma_client, "ChromaPhotoStore", FakeStore)
    monkeypatch.setattr(evaluation, "_build_photo_records", lambda _: {
        "photo-uuid": {"id": "photo-uuid", "filename": "photo", "description": "可信描述", "vlm_status": "healthy"},
    })
    monkeypatch.setattr(evaluation.photo_rag, "_aggregate_by_photo", lambda results, top_n: results)

    cfg = SimpleNamespace(
        go_backend_url="http://go",
        embedding_model="test",
        resolve_path=lambda path: Path("/tmp"),
        agent_path=lambda *parts: Path("/tmp").joinpath(*parts),
    )
    result = evaluation.run_evaluation(cfg, test_queries=[{
        "id": "case-1",
        "question": "同一查询",
        "relevant_photos": [
            {"photo_id": "photo", "granularity": "photo"},
            {"photo_id": "fine", "granularity": "fine"},
            {"photo_id": "coarse", "granularity": "coarse"},
        ],
    }], verbose=False)

    try:
      self.assertEqual(result["details"][0]["golden_id"], "case-1")
      self.assertEqual(result["details"][0]["hits"], ["photo"])
      self.assertEqual(result["details"][0]["remaining"], ["coarse", "fine"])
      self.assertEqual(set(FakeStore.stores), {"photos"})
      self.assertFalse(result["data_trusted"])
    finally:
      evaluation.embedder.Embedder, evaluation.chroma_client.ChromaPhotoStore, \
          evaluation._build_photo_records, evaluation.photo_rag._aggregate_by_photo = old

  def test_asset_health_requires_healthy_description_and_current_vector(self):
    healthy, asset = evaluation._photo_is_healthy(
        {"id": "p1", "filename": "DSC_1813.jpg", "description": "可信描述", "vlm_status": "healthy"},
        {"p1": {evaluation.hashlib.sha256("可信描述".encode()).hexdigest()}},
    )
    self.assertTrue(healthy)
    self.assertTrue(asset["healthy"])

    healthy, asset = evaluation._photo_is_healthy(
        {"id": "p1", "filename": "DSC_1813.jpg", "description": "可信描述", "vlm_status": "review", "vlm_reason": "命中质量规则"},
        {"p1": {evaluation.hashlib.sha256("可信描述".encode()).hexdigest()}},
    )
    self.assertFalse(healthy)
    self.assertEqual(asset["reason"], "命中质量规则")

  def test_save_evaluation_snapshot_writes_report_id(self):
    with tempfile.TemporaryDirectory() as temp_dir:
      cfg = SimpleNamespace(
          resolve_path=lambda _: Path(temp_dir),
          eval_reports_dir="./docs/eval/reports",
      )
      path = evaluation.save_evaluation_snapshot(cfg, {
          "report_id": "beforefix123", "generated_at": "2026-08-27T12:00:00+00:00",
          "details": [],
      })
      self.assertTrue(path.exists())
      report = evaluation.json.loads(path.read_text(encoding="utf-8"))
      self.assertEqual(report["report_id"], "beforefix123")


  def test_golden_photo_ref_accepts_legacy_granularity_input(self):
    self.assertEqual(server.GoldenPhotoRef(photo_id="x", filename="x").granularity, "photo")
    self.assertEqual(server.GoldenPhotoRef(photo_id="x", filename="x", granularity="fine").granularity, "fine")

  def test_golden_query_id_passes_into_evaluation_input(self):
    loaded = evaluation._load_golden_queries_from_items([
        {"id": "abc123", "query_text": "带 ID 的用例", "relevant_photos": ["DSC_1.jpg"]},
    ])
    self.assertEqual(loaded[0]["id"], "abc123")


class TestAppendGoldenPhotos(unittest.TestCase):
  """TF1-5 追加期望照片：粒度、去重、UUID 解析与错误反馈。"""

  def _case(self) -> dict:
    return {
        "id": "case-1",
        "query_text": "佛像和人的合照",
        "relevant_photos": [
            {"photo_id": "DSC_1", "filename": "DSC_1", "uuid": "u1", "granularity": "photo"},
        ],
        "category": "",
        "notes": "",
        "created_at": "2026-08-25T00:00:00",
        "updated_at": "2026-08-25T00:00:00",
    }

  def test_append_resolves_uuid_and_forces_photo_semantics(self):
    items = [self._case()]
    target, added = server._append_photos_to_case(
        items,
        "case-1",
        [server.GoldenPhotoRef(photo_id="DSC_2.jpg", filename="DSC_2.jpg", granularity="coarse")],
        {"DSC_2": "u2"},
    )

    self.assertEqual(added, 1)
    self.assertEqual(target["relevant_photos"][-1], {
        "photo_id": "DSC_2",
        "filename": "DSC_2",
        "uuid": "u2",
    })
    self.assertNotEqual(target["updated_at"], "2026-08-25T00:00:00")

  def test_append_skips_same_photo_regardless_of_legacy_granularity(self):
    items = [self._case()]
    _, added = server._append_photos_to_case(
        items,
        "case-1",
        [
            server.GoldenPhotoRef(photo_id="DSC_1", filename="DSC_1"),
            server.GoldenPhotoRef(photo_id="DSC_1", filename="DSC_1", granularity="fine"),
        ],
        {"DSC_1": "u1"},
    )

    self.assertEqual(added, 0)
    self.assertEqual(len(items[0]["relevant_photos"]), 1)

  def test_append_reports_missing_case_photo_and_empty_input(self):
    with self.assertRaises(server.fastapi.HTTPException) as ctx:
      server._append_photos_to_case([self._case()], "nope", [
          server.GoldenPhotoRef(photo_id="DSC_2", filename="DSC_2"),
      ], {"DSC_2": "u2"})
    self.assertEqual(ctx.exception.status_code, 404)

    with self.assertRaises(server.fastapi.HTTPException) as ctx:
      server._append_photos_to_case([self._case()], "case-1", [], {})
    self.assertEqual(ctx.exception.status_code, 400)

    with self.assertRaises(server.fastapi.HTTPException) as ctx:
      server._append_photos_to_case([self._case()], "case-1", [
          server.GoldenPhotoRef(photo_id="DSC_404", filename="DSC_404"),
      ], {})
    self.assertEqual(ctx.exception.status_code, 400)
    self.assertIn("不在图库", ctx.exception.detail)


class TestUpdateGoldenQuery(unittest.TestCase):
  def _case(self) -> dict:
    return {
        "id": "case-1",
        "query_text": "旧查询",
        "relevant_photos": [{"photo_id": "DSC_1", "filename": "DSC_1", "uuid": "u1"}],
        "category": "旧分类",
        "notes": "旧备注",
        "created_at": "2026-08-25T00:00:00",
        "updated_at": "2026-08-25T00:00:00",
    }

  def test_update_replaces_fields_and_deduplicates_photos(self):
    items = [self._case()]
    target = server._update_golden_query(
        items,
        "case-1",
        "  新查询  ",
        [
            server.GoldenPhotoRef(photo_id="DSC_2.jpg", filename="DSC_2.jpg", uuid="u2"),
            server.GoldenPhotoRef(photo_id="DSC_2", filename="DSC_2", uuid="u2"),
        ],
        " 新分类 ",
        " 新备注 ",
        {},
    )

    self.assertEqual(target["query_text"], "新查询")
    self.assertEqual(target["category"], "新分类")
    self.assertEqual(target["notes"], "新备注")
    self.assertEqual(target["relevant_photos"], [{
        "photo_id": "DSC_2",
        "filename": "DSC_2",
        "uuid": "u2",
    }])
    self.assertNotEqual(target["updated_at"], "2026-08-25T00:00:00")

  def test_update_rejects_invalid_input(self):
    for query_text, photos, status_code in [("  ", ["photo"], 400), ("有效", [], 400)]:
      with self.subTest(query_text=query_text, photos=photos):
        with self.assertRaises(server.fastapi.HTTPException) as ctx:
          server._update_golden_query(
              [self._case()], "case-1", query_text,
              [server.GoldenPhotoRef(photo_id=p, filename=p, uuid=p) for p in photos],
              "", "", {},
          )
        self.assertEqual(ctx.exception.status_code, status_code)

    with self.assertRaises(server.fastapi.HTTPException) as ctx:
      server._update_golden_query(
          [self._case()], "missing", "有效",
          [server.GoldenPhotoRef(photo_id="DSC_2", filename="DSC_2", uuid="u2")],
          "", "", {},
      )
    self.assertEqual(ctx.exception.status_code, 404)
