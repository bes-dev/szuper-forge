from pathlib import Path
import runpy
import pytest


@pytest.fixture
def demo(tmp_path):
    create = runpy.run_path(str(Path(__file__).parents[1] / "examples/create_demo.py"))["create"]
    return create(tmp_path / "project")
