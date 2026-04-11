"""Shared test fixtures."""

import pytest


@pytest.fixture
def workspace_dir(tmp_path):
    """Create an isolated workspace for file operation tests."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "test.py").write_text("print('hello')\n")
    (ws / "subdir").mkdir()
    (ws / "subdir" / "data.txt").write_text("some data\n")
    return ws
