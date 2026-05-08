"""Tests for BatchRunner."""
from __future__ import annotations

from pathlib import Path

from pyconveyor.batch import BatchRunner

PIPELINES = Path(__file__).parent / "fixtures" / "pipelines"


class TestBatchRunner:
    def test_run_all_returns_list(self):
        br = BatchRunner(PIPELINES / "hello.yaml", max_workers=2)
        items = [{"name": "Ada"}, {"name": "Bob"}]
        results = br.run_all(items)
        assert len(results) == 2

    def test_results_have_item_id(self):
        br = BatchRunner(PIPELINES / "hello.yaml", max_workers=1)
        items = [{"name": "Ada", "id": "ada-001"}]
        results = br.run_all(items)
        assert len(results) == 1
        item_id, rctx = results[0]
        assert item_id == "ada-001"

    def test_results_not_failed(self):
        br = BatchRunner(PIPELINES / "hello.yaml", max_workers=2)
        items = [{"name": "Ada"}, {"name": "Bob"}]
        results = br.run_all(items)
        for _, rctx in results:
            assert not rctx.failed

    def test_step_results_correct(self):
        br = BatchRunner(PIPELINES / "hello.yaml", max_workers=1)
        items = [{"name": "Ada"}]
        results = br.run_all(items)
        _, rctx = results[0]
        assert "greet" in rctx.steps
        assert rctx.steps["greet"].status == "success"

    def test_run_generator(self):
        br = BatchRunner(PIPELINES / "hello.yaml", max_workers=1)
        items = [{"name": "Ada"}, {"name": "Bob"}]
        gen = list(br.run(items))
        assert len(gen) == 2

    def test_custom_key_fn(self):
        br = BatchRunner(PIPELINES / "hello.yaml", max_workers=1)
        items = [{"name": "Ada", "doc_id": "ada"}, {"name": "Bob", "doc_id": "bob"}]
        results = br.run_all(items, key="doc_id")
        ids = [r[0] for r in results]
        # IDs should be the doc_id values
        assert set(ids) == {"ada", "bob"}
