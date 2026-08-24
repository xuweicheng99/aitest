from __future__ import annotations

import json
import re
from pathlib import Path

from app.core.exceptions import ArtifactNotFoundError, RunNotFoundError
from app.schemas.run import RunRecord, RunSummary


RUN_ID_PATTERN = re.compile(r"^[a-f0-9]{10}$")
ALLOWED_ARTIFACTS = {"screenshot.png", "trace.zip", "result.json"}


class RunRepository:
    def __init__(self, runs_dir: Path) -> None:
        self.runs_dir = runs_dir
        self.runs_dir.mkdir(parents=True, exist_ok=True)

    def create_directory(self, run_id: str) -> Path:
        self._validate_run_id(run_id)
        run_dir = self.runs_dir / run_id
        run_dir.mkdir(parents=False, exist_ok=False)
        return run_dir

    def save(self, record: RunRecord) -> None:
        run_dir = self.runs_dir / record.run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        target = run_dir / "result.json"
        temporary = run_dir / "result.json.tmp"
        temporary.write_text(
            record.model_dump_json(indent=2),
            encoding="utf-8",
        )
        temporary.replace(target)

    def save_error_text(self, run_id: str, message: str) -> None:
        (self.runs_dir / run_id / "error.txt").write_text(message, encoding="utf-8")

    def get(self, run_id: str) -> RunRecord:
        self._validate_run_id(run_id)
        path = self.runs_dir / run_id / "result.json"
        if not path.is_file():
            raise RunNotFoundError("测试运行记录不存在")
        try:
            return RunRecord.model_validate_json(path.read_text(encoding="utf-8"))
        except (ValueError, json.JSONDecodeError) as exc:
            raise RunNotFoundError("测试运行记录无效或来自旧版本") from exc

    def list(self, limit: int) -> list[RunSummary]:
        records: list[RunRecord] = []
        candidates = sorted(
            self.runs_dir.glob("*/result.json"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        for path in candidates:
            try:
                records.append(RunRecord.model_validate_json(path.read_text(encoding="utf-8")))
            except (ValueError, OSError):
                continue
            if len(records) >= limit:
                break
        return [
            RunSummary(
                run_id=record.run_id,
                url=record.url,
                goal=record.goal,
                status=record.status,
                mode=record.mode,
                started_at=record.started_at,
                finished_at=record.finished_at,
            )
            for record in records
        ]

    def artifact_path(self, run_id: str, artifact: str) -> Path:
        self._validate_run_id(run_id)
        if artifact not in ALLOWED_ARTIFACTS:
            raise ArtifactNotFoundError("测试产物不存在")
        path = self.runs_dir / run_id / artifact
        if not path.is_file():
            raise ArtifactNotFoundError("测试产物不存在")
        return path

    @staticmethod
    def _validate_run_id(run_id: str) -> None:
        if not RUN_ID_PATTERN.fullmatch(run_id):
            raise RunNotFoundError("测试运行 ID 无效")

