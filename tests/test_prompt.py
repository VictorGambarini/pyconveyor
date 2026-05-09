"""Tests for prompt.py — Jinja2 template rendering."""
from __future__ import annotations

from pathlib import Path

import pytest

from pyconveyor.prompt import render_prompt, render_prompt_string, PromptRenderError


class TestRenderPromptString:
    def test_basic_render(self):
        result = render_prompt_string("Hello {{ name }}!", name="World")
        assert result == "Hello World!"

    def test_no_variables(self):
        result = render_prompt_string("Static text.")
        assert result == "Static text."

    def test_undefined_variable_raises(self):
        with pytest.raises(PromptRenderError, match="Undefined variable"):
            render_prompt_string("Hello {{ missing }}!")

    def test_syntax_error_raises(self):
        with pytest.raises(PromptRenderError, match="Syntax error"):
            render_prompt_string("{% if %}broken")

    def test_conditional_template(self):
        tmpl = "{% if greet %}Hello {{ name }}{% else %}Goodbye{% endif %}"
        assert render_prompt_string(tmpl, greet=True, name="Ada") == "Hello Ada"
        assert render_prompt_string(tmpl, greet=False) == "Goodbye"

    def test_loop_template(self):
        tmpl = "{% for item in items %}{{ item }} {% endfor %}"
        result = render_prompt_string(tmpl, items=["a", "b", "c"])
        assert result.strip() == "a b c"


class TestRenderPrompt:
    def test_renders_from_file(self, tmp_path: Path):
        template_dir = tmp_path / "prompts"
        template_dir.mkdir()
        (template_dir / "hello.j2").write_text("Hello {{ name }}!")
        result = render_prompt(template_dir, "hello.j2", name="Ada")
        assert result == "Hello Ada!"

    def test_missing_template_raises(self, tmp_path: Path):
        with pytest.raises(PromptRenderError):
            render_prompt(tmp_path, "nonexistent.j2")

    def test_syntax_error_raises(self, tmp_path: Path):
        template_dir = tmp_path / "prompts"
        template_dir.mkdir()
        (template_dir / "bad.j2").write_text("{% if %}broken")
        with pytest.raises(PromptRenderError, match="Syntax error"):
            render_prompt(template_dir, "bad.j2")

    def test_undefined_variable_raises(self, tmp_path: Path):
        template_dir = tmp_path / "prompts"
        template_dir.mkdir()
        (template_dir / "tmpl.j2").write_text("Hello {{ missing_var }}!")
        with pytest.raises(PromptRenderError, match="Undefined variable"):
            render_prompt(template_dir, "tmpl.j2")
