"""Smoke test: every subpackage of planner can be imported."""

import importlib

import pytest

SUBPACKAGES = ["agent", "parser", "solver", "checker", "calendar", "api"]


@pytest.mark.parametrize("name", SUBPACKAGES)
def test_subpackage_imports(name: str) -> None:
    module = importlib.import_module(f"planner.{name}")
    assert module.__doc__, f"planner.{name} needs a docstring"
