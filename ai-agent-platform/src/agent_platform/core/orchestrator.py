"""Multi-agent orchestrator.

Coordinates multiple sub-agents working on decomposed tasks.
Patterns supported:
  - Supervisor: one lead agent delegates to specialist workers
  - Parallel: independent sub-tasks run concurrently
  - Pipeline: sequential hand-off between agents
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

import structlog

from agent_platform.core.agent_loop import run_agent_loop
from agent_platform.core.session import AgentSession

if TYPE_CHECKING:
    from agent_platform.harness.base import BaseHarness
    from agent_platform.models.gateway import ModelGateway
    from agent_platform.tools.registry import ToolRegistry

logger = structlog.get_logger()


class OrchestrationPattern(str, Enum):
    SUPERVISOR = "supervisor"
    PARALLEL = "parallel"
    PIPELINE = "pipeline"


@dataclass
class SubTask:
    """A decomposed unit of work assigned to a sub-agent."""

    task_id: str
    description: str
    model_id: str = ""  # empty = inherit from parent
    harness_id: str = ""  # empty = inherit from parent
    dependencies: list[str] = field(default_factory=list)
    result: str = ""


@dataclass
class OrchestrationPlan:
    pattern: OrchestrationPattern
    tasks: list[SubTask]
    context: str = ""  # shared context for all sub-agents


class Orchestrator:
    """Executes a multi-agent orchestration plan."""

    def __init__(
        self,
        gateway: "ModelGateway",
        tool_registry: "ToolRegistry",
        harness_factory: dict[str, "BaseHarness"],
    ) -> None:
        self._gateway = gateway
        self._tools = tool_registry
        self._harnesses = harness_factory

    async def execute(self, plan: OrchestrationPlan) -> dict[str, str]:
        """Run the plan and return {task_id: result} mapping."""
        match plan.pattern:
            case OrchestrationPattern.PARALLEL:
                return await self._run_parallel(plan)
            case OrchestrationPattern.PIPELINE:
                return await self._run_pipeline(plan)
            case OrchestrationPattern.SUPERVISOR:
                return await self._run_supervisor(plan)

    async def _run_parallel(self, plan: OrchestrationPlan) -> dict[str, str]:
        """Execute all tasks concurrently."""
        coros = [self._run_single_task(task, plan.context) for task in plan.tasks]
        results = await asyncio.gather(*coros, return_exceptions=True)
        return {
            task.task_id: str(res) if isinstance(res, Exception) else task.result
            for task, res in zip(plan.tasks, results)
        }

    async def _run_pipeline(self, plan: OrchestrationPlan) -> dict[str, str]:
        """Execute tasks sequentially, passing output to next task's context."""
        accumulated_context = plan.context
        results: dict[str, str] = {}
        for task in plan.tasks:
            await self._run_single_task(task, accumulated_context)
            results[task.task_id] = task.result
            accumulated_context += f"\n\n[Result from {task.task_id}]: {task.result}"
        return results

    async def _run_supervisor(self, plan: OrchestrationPlan) -> dict[str, str]:
        """Supervisor pattern: resolve dependencies, then execute ready tasks."""
        completed: dict[str, str] = {}
        pending = list(plan.tasks)

        while pending:
            ready = [t for t in pending if all(d in completed for d in t.dependencies)]
            if not ready:
                logger.error("orchestrator.deadlock", pending=[t.task_id for t in pending])
                break

            coros = [
                self._run_single_task(t, plan.context + self._dep_context(t, completed))
                for t in ready
            ]
            await asyncio.gather(*coros)

            for task in ready:
                completed[task.task_id] = task.result
                pending.remove(task)

        return completed

    async def _run_single_task(self, task: SubTask, context: str) -> None:
        """Create a session for one sub-task and run the agent loop."""
        harness_id = task.harness_id or "react"
        harness = self._harnesses[harness_id]
        session = AgentSession(
            model_id=task.model_id or self._gateway.default_model,
            harness_id=harness_id,
        )
        session.add_message("user", f"{context}\n\nTask: {task.description}")

        result_session = await run_agent_loop(session, self._gateway, self._tools, harness)
        if result_session.messages:
            task.result = result_session.messages[-1].content

    @staticmethod
    def _dep_context(task: SubTask, completed: dict[str, str]) -> str:
        parts = [f"\n[Dependency {d}]: {completed[d]}" for d in task.dependencies]
        return "".join(parts)
