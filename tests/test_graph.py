"""Tests for graph.py — Mermaid DAG generation."""
from __future__ import annotations

from pathlib import Path

from pyconveyor.graph import _label, _node_shape, generate_mermaid

PIPELINES = Path(__file__).parent / "fixtures" / "pipelines"


class TestLabel:
    def test_label_basic(self):
        step = {"name": "extract", "type": "llm"}
        label = _label(step)
        assert "extract" in label
        assert "llm" in label

    def test_label_with_model(self):
        step = {"name": "extract", "type": "llm", "model": "gpt4"}
        label = _label(step)
        assert "model: gpt4" in label

    def test_label_with_schema(self):
        step = {"name": "extract", "type": "llm", "schema": "module:MyModel"}
        label = _label(step)
        assert "schema: MyModel" in label

    def test_label_with_fn(self):
        step = {"name": "transform", "type": "transform", "fn": "module:my_func"}
        label = _label(step)
        assert "fn: my_func" in label

    def test_label_schema_no_colon(self):
        step = {"name": "step", "type": "llm", "schema": "MyModel"}
        label = _label(step)
        assert "schema: MyModel" in label


class TestNodeShape:
    def test_llm_shape(self):
        assert _node_shape({"type": "llm"}) == ("[", "]")

    def test_transform_shape(self):
        assert _node_shape({"type": "transform"}) == ("([", "])")

    def test_io_shape(self):
        assert _node_shape({"type": "io"}) == ("{", "}")

    def test_validate_shape(self):
        assert _node_shape({"type": "validate"}) == ("{{", "}}")

    def test_condition_shape(self):
        assert _node_shape({"type": "condition"}) == ("{", "}")

    def test_parallel_shape(self):
        assert _node_shape({"type": "parallel"}) == ("[(", ")]")

    def test_unknown_defaults_to_llm(self):
        assert _node_shape({"type": "unknown_type"}) == ("[", "]")


class TestGenerateMermaid:
    def test_flowchart_header(self, tmp_path: Path):
        pipeline = tmp_path / "simple.yaml"
        pipeline.write_text(
            "models:\n"
            "  m:\n"
            "    provider: mock\n"
            "    model: m\n"
            "    mock_responses: ['ok']\n"
            "steps:\n"
            "  - name: step1\n"
            "    type: llm\n"
            "    model: m\n"
            "    prompt_string: hello\n"
        )
        result = generate_mermaid(pipeline)
        assert result.startswith("flowchart TD")

    def test_single_step_node(self, tmp_path: Path):
        pipeline = tmp_path / "single.yaml"
        pipeline.write_text(
            "models:\n"
            "  m:\n"
            "    provider: mock\n"
            "    model: m\n"
            "    mock_responses: ['ok']\n"
            "steps:\n"
            "  - name: my_step\n"
            "    type: llm\n"
            "    model: m\n"
            "    prompt_string: hello\n"
        )
        result = generate_mermaid(pipeline)
        assert "my_step" in result

    def test_two_steps_have_edge(self, tmp_path: Path):
        pipeline = tmp_path / "two_steps.yaml"
        pipeline.write_text(
            "models:\n"
            "  m:\n"
            "    provider: mock\n"
            "    model: m\n"
            "    mock_responses: ['ok']\n"
            "steps:\n"
            "  - name: step_a\n"
            "    type: llm\n"
            "    model: m\n"
            "    prompt_string: hello\n"
            "  - name: step_b\n"
            "    type: llm\n"
            "    model: m\n"
            "    prompt_string: world\n"
        )
        result = generate_mermaid(pipeline)
        assert "step_a --> step_b" in result

    def test_parallel_step_renders_subgraph(self):
        result = generate_mermaid(PIPELINES / "parallel.yaml")
        assert "subgraph" in result
        assert "primary" in result
        assert "reviewer" in result

    def test_condition_step_renders_branches(self):
        result = generate_mermaid(PIPELINES / "condition.yaml")
        assert "greet" in result

    def test_step_with_model_in_label(self, tmp_path: Path):
        pipeline = tmp_path / "labeled.yaml"
        pipeline.write_text(
            "models:\n"
            "  gpt4:\n"
            "    provider: mock\n"
            "    model: gpt-4\n"
            "    mock_responses: ['ok']\n"
            "steps:\n"
            "  - name: analyze\n"
            "    type: llm\n"
            "    model: gpt4\n"
            "    schema: module:MySchema\n"
            "    prompt_string: analyze\n"
        )
        result = generate_mermaid(pipeline)
        assert "model: gpt4" in result
        assert "schema: MySchema" in result
