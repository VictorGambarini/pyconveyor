"""Tests for BatchRunner and BatchResult."""
from __future__ import annotations

from pathlib import Path

import pytest

from pyconveyor.batch import BatchResult, BatchRunner
from pyconveyor.runner import RunContext

PIPELINES = Path(__file__).parent / "fixtures" / "pipelines"


class TestBatchRunner:
    def test_run_all_returns_batch_result(self):
        br = BatchRunner(PIPELINES / "hello.yaml", max_workers=2)
        items = [{"name": "Ada"}, {"name": "Bob"}]
        result = br.run_all(items)
        assert isinstance(result, BatchResult)
        assert len(result) == 2

    def test_batch_result_iterable(self):
        br = BatchRunner(PIPELINES / "hello.yaml", max_workers=1)
        items = [{"name": "Ada", "id": "ada-001"}]
        result = br.run_all(items)
        pairs = list(result)
        assert len(pairs) == 1
        item_id, rctx = pairs[0]
        assert item_id == "ada-001"

    def test_batch_result_indexing(self):
        br = BatchRunner(PIPELINES / "hello.yaml", max_workers=1)
        items = [{"name": "Ada", "id": "ada-001"}]
        result = br.run_all(items)
        item_id, rctx = result[0]
        assert item_id == "ada-001"

    def test_results_not_failed(self):
        br = BatchRunner(PIPELINES / "hello.yaml", max_workers=2)
        items = [{"name": "Ada"}, {"name": "Bob"}]
        result = br.run_all(items)
        for _, rctx in result:
            assert not rctx.failed

    def test_step_results_correct(self):
        br = BatchRunner(PIPELINES / "hello.yaml", max_workers=1)
        items = [{"name": "Ada"}]
        result = br.run_all(items)
        _, rctx = result[0]
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
        result = br.run_all(items, key="doc_id")
        ids = [r[0] for r in result]
        assert set(ids) == {"ada", "bob"}

    def test_empty_items_returns_empty_result(self):
        br = BatchRunner(PIPELINES / "hello.yaml", max_workers=1)
        result = br.run_all([])
        assert isinstance(result, BatchResult)
        assert len(result) == 0

    def test_on_batch_item_end_hook_called(self):
        br = BatchRunner(PIPELINES / "hello.yaml", max_workers=1, progress=False)
        items = [{"name": "Ada", "id": "ada"}, {"name": "Bob", "id": "bob"}]
        seen: list[tuple] = []

        @br.on_batch_item_end
        def capture(item_id, rctx):
            seen.append((item_id, rctx.failed))

        br.run_all(items)
        assert len(seen) == 2
        assert all(not failed for _, failed in seen)

    def test_on_batch_item_end_called_per_item(self):
        br = BatchRunner(PIPELINES / "hello.yaml", max_workers=1, progress=False)
        items = [{"name": f"User{i}", "id": i} for i in range(5)]
        call_count = [0]

        @br.on_batch_item_end
        def counter(item_id, rctx):
            call_count[0] += 1

        br.run_all(items)
        assert call_count[0] == 5

    def test_hook_error_does_not_abort_batch(self):
        br = BatchRunner(PIPELINES / "hello.yaml", max_workers=1, progress=False)
        items = [{"name": "Ada", "id": "ada"}]

        @br.on_batch_item_end
        def bad_hook(item_id, rctx):
            raise RuntimeError("hook failure")

        result = br.run_all(items)
        assert len(result) == 1


class TestBatchResult:
    def _make(self, n_success: int = 2, n_fail: int = 1) -> BatchResult:
        items: list[tuple] = []
        for i in range(n_success):
            rctx = RunContext({})
            items.append((f"ok-{i}", rctx))
        for i in range(n_fail):
            rctx = RunContext({})
            rctx.failed = True
            items.append((f"fail-{i}", rctx))
        return BatchResult(items)

    def test_successes_filtered(self):
        br = self._make(n_success=3, n_fail=1)
        assert len(br.successes) == 3

    def test_failures_filtered(self):
        br = self._make(n_success=2, n_fail=2)
        assert len(br.failures) == 2

    def test_error_rate(self):
        br = self._make(n_success=3, n_fail=1)
        assert br.error_rate == pytest.approx(0.25)

    def test_error_rate_empty(self):
        br = BatchResult([])
        assert br.error_rate == 0.0

    def test_summary_counts(self):
        br = self._make(n_success=4, n_fail=1)
        s = br.summary()
        assert s.total == 5
        assert s.succeeded == 4
        assert s.failed == 1

    def test_summary_failed_ids(self):
        br = self._make(n_success=1, n_fail=2)
        s = br.summary()
        assert set(s.failed_ids) == {"fail-0", "fail-1"}

    def test_all_success_zero_error_rate(self):
        br = self._make(n_success=5, n_fail=0)
        assert br.error_rate == 0.0
        assert br.summary().failed == 0
