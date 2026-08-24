from pathlib import Path

import pytest

from app.core.exceptions import ArtifactNotFoundError, RunNotFoundError
from app.repositories.run_repository import RunRepository
from app.schemas.run import RunRecord


def make_record() -> RunRecord:
    return RunRecord(
        run_id="a1b2c3d4e5",
        url="https://example.com",
        goal="check title",
        headless=True,
        status="running",
        started_at="2026-08-24T00:00:00+00:00",
    )


def test_save_get_and_list(tmp_path: Path) -> None:
    repository = RunRepository(tmp_path)
    repository.create_directory("a1b2c3d4e5")
    repository.save(make_record())

    assert repository.get("a1b2c3d4e5").goal == "check title"
    assert repository.list(10)[0].run_id == "a1b2c3d4e5"


def test_reject_invalid_run_id(tmp_path: Path) -> None:
    repository = RunRepository(tmp_path)
    with pytest.raises(RunNotFoundError):
        repository.get("../unsafe")


def test_artifact_allowlist(tmp_path: Path) -> None:
    repository = RunRepository(tmp_path)
    with pytest.raises(ArtifactNotFoundError):
        repository.artifact_path("a1b2c3d4e5", "error.txt")

