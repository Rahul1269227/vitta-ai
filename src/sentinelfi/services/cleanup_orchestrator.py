from __future__ import annotations

from pathlib import Path

from sentinelfi.core.config import Settings
from sentinelfi.domain.models import CleanupTask
from sentinelfi.graph.cleanup_graph import CleanupGraphFactory
from sentinelfi.services.cleanup_execution_service import CleanupTaskExecutor


class CleanupOrchestrator:
    def __init__(
        self,
        output_dir: str | Path = "output/cleanup",
        settings: Settings | None = None,
    ):
        executor = CleanupTaskExecutor(output_dir=output_dir, settings=settings)
        self.graph = CleanupGraphFactory(executor=executor).build()

    def run(self, tasks: list[CleanupTask], approved_task_ids: list[str]):
        return self.graph.invoke({"tasks": tasks, "approved_task_ids": approved_task_ids})
