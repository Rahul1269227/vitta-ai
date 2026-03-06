from __future__ import annotations

from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from sentinelfi.domain.models import CleanupTask
from sentinelfi.services.cleanup_execution_service import CleanupTaskExecutor


class CleanupState(TypedDict, total=False):
    tasks: list[CleanupTask]
    approved_task_ids: list[str]
    executed: list[dict]
    skipped: list[str]


class CleanupGraphFactory:
    def __init__(self, executor: CleanupTaskExecutor | None = None):
        self.executor = executor or CleanupTaskExecutor()

    def build(self):
        graph = StateGraph(CleanupState)
        graph.add_node("approval_gate", self.approval_gate)
        graph.add_node("execute_writes", self.execute_writes)

        graph.add_edge(START, "approval_gate")
        graph.add_edge("approval_gate", "execute_writes")
        graph.add_edge("execute_writes", END)
        return graph.compile()

    def approval_gate(self, state: CleanupState) -> CleanupState:
        approved = set(state.get("approved_task_ids", []))
        tasks = state.get("tasks", [])

        permitted: list[CleanupTask] = []
        skipped: list[str] = []
        for task in tasks:
            if not task.requires_approval or task.task_id in approved:
                permitted.append(task)
            else:
                skipped.append(task.task_id)

        state["tasks"] = permitted
        state["skipped"] = skipped
        return state

    def execute_writes(self, state: CleanupState) -> CleanupState:
        executed: list[dict] = []
        for task in state.get("tasks", []):
            executed.append(self.executor.execute(task))
        state["executed"] = executed
        return state
