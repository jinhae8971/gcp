"""Evaluation dataset management.

Supports JSONL format for task definitions. Each task includes:
  - A description of the problem
  - Expected output or test commands to verify
  - Metadata for categorization
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class EvalTask:
    """A single evaluation task."""

    task_id: str
    description: str
    category: str = "general"
    difficulty: str = "medium"  # easy | medium | hard
    expected_output: str = ""
    test_command: str = ""  # Shell command to verify correctness
    files: dict[str, str] = field(default_factory=dict)  # Initial file contents
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EvalTask":
        return cls(
            task_id=data["task_id"],
            description=data["description"],
            category=data.get("category", "general"),
            difficulty=data.get("difficulty", "medium"),
            expected_output=data.get("expected_output", ""),
            test_command=data.get("test_command", ""),
            files=data.get("files", {}),
            metadata=data.get("metadata", {}),
        )


@dataclass
class EvalDataset:
    """Collection of evaluation tasks."""

    name: str
    tasks: list[EvalTask] = field(default_factory=list)

    @classmethod
    def load(cls, path: str) -> "EvalDataset":
        """Load tasks from a JSONL file."""
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"Dataset not found: {path}")

        tasks: list[EvalTask] = []
        with open(p) as f:
            for line in f:
                line = line.strip()
                if line:
                    tasks.append(EvalTask.from_dict(json.loads(line)))

        return cls(name=p.stem, tasks=tasks)

    def filter_by_category(self, category: str) -> list[EvalTask]:
        return [t for t in self.tasks if t.category == category]

    def filter_by_difficulty(self, difficulty: str) -> list[EvalTask]:
        return [t for t in self.tasks if t.difficulty == difficulty]
