"""Async evaluation worker.

Pulls eval jobs from a Redis queue, executes them, and stores results.
Designed to run as a separate process (see docker-compose.yml).

Queue protocol (Redis list: "eval_jobs"):
  - LPUSH a JSON job spec
  - Worker BRPOP, runs evaluation, stores result in history

Usage:
    python -m agent_platform.eval.worker
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
from datetime import datetime, timezone
from typing import Any

import structlog

from agent_platform.eval.history import EvalHistory
from agent_platform.eval.reporters import generate_html_dashboard
from agent_platform.eval.runner import EvalConfig, EvalReport, EvalRunner
from agent_platform.eval.scorers import ScorerRegistry
from agent_platform.observability.logger import setup_logging

logger = structlog.get_logger()

QUEUE_KEY = "eval_jobs"
RESULT_KEY_PREFIX = "eval_result:"
POLL_TIMEOUT = 5  # seconds


class EvalWorker:
    """Background worker that processes evaluation jobs from Redis."""

    def __init__(self, redis_url: str = "") -> None:
        self._redis_url = redis_url or os.environ.get("REDIS_URL", "redis://localhost:6379/0")
        self._redis: Any = None
        self._running = False
        self._history = EvalHistory()
        self._scorer_registry = ScorerRegistry()

    async def _get_redis(self) -> Any:
        if self._redis is None:
            from redis.asyncio import from_url
            self._redis = from_url(self._redis_url, decode_responses=True)
        return self._redis

    async def start(self) -> None:
        """Main loop: poll for jobs and execute them."""
        setup_logging(level=os.environ.get("LOG_LEVEL", "INFO"))
        self._running = True
        logger.info("eval_worker.started", redis=self._redis_url)

        while self._running:
            try:
                job = await self._poll_job()
                if job:
                    await self._process_job(job)
            except Exception as exc:
                logger.error("eval_worker.error", error=str(exc))
                await asyncio.sleep(1)

    async def stop(self) -> None:
        self._running = False
        if self._redis:
            await self._redis.close()
        logger.info("eval_worker.stopped")

    async def _poll_job(self) -> dict[str, Any] | None:
        """Block-wait for a job from the Redis queue."""
        r = await self._get_redis()
        result = await r.brpop(QUEUE_KEY, timeout=POLL_TIMEOUT)
        if result is None:
            return None
        _, raw = result
        return json.loads(raw)

    async def _process_job(self, job: dict[str, Any]) -> None:
        """Execute an evaluation job."""
        job_id = job.get("job_id", "unknown")
        logger.info("eval_worker.job_start", job_id=job_id)

        try:
            config = EvalConfig(**job.get("config", {}))
            runner = EvalRunner(scorer_registry=self._scorer_registry)
            report = await runner.run(config)

            # Save to history
            history_path = self._history.save(report)

            # Generate dashboard
            trend = self._history.get_trend(name_filter=config.name)
            dashboard_path = f"eval/results/{config.name}_dashboard.html"
            generate_html_dashboard(report, history=trend, output_path=dashboard_path)

            # Store result in Redis for API polling
            r = await self._get_redis()
            result_data = {
                "job_id": job_id,
                "status": "completed",
                "history_path": history_path,
                "dashboard_path": dashboard_path,
                "summary": report.to_dict()["summary"],
                "completed_at": datetime.now(timezone.utc).isoformat(),
            }
            await r.setex(
                f"{RESULT_KEY_PREFIX}{job_id}",
                3600,  # 1 hour TTL
                json.dumps(result_data),
            )

            logger.info(
                "eval_worker.job_complete",
                job_id=job_id,
                avg_score=report.average_score,
                passes_gate=report.passes_gate(),
            )

        except Exception as exc:
            logger.error("eval_worker.job_failed", job_id=job_id, error=str(exc))
            r = await self._get_redis()
            await r.setex(
                f"{RESULT_KEY_PREFIX}{job_id}",
                3600,
                json.dumps({"job_id": job_id, "status": "failed", "error": str(exc)}),
            )

    @staticmethod
    async def submit_job(redis_url: str, config: dict[str, Any], job_id: str = "") -> str:
        """Submit an eval job to the queue. Returns the job_id."""
        from redis.asyncio import from_url
        import uuid

        job_id = job_id or uuid.uuid4().hex[:12]
        r = from_url(redis_url, decode_responses=True)
        await r.lpush(QUEUE_KEY, json.dumps({"job_id": job_id, "config": config}))
        await r.close()
        return job_id

    @staticmethod
    async def get_result(redis_url: str, job_id: str) -> dict[str, Any] | None:
        """Poll for a job result."""
        from redis.asyncio import from_url

        r = from_url(redis_url, decode_responses=True)
        raw = await r.get(f"{RESULT_KEY_PREFIX}{job_id}")
        await r.close()
        if raw:
            return json.loads(raw)
        return None


async def _main() -> None:
    worker = EvalWorker()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda: asyncio.ensure_future(worker.stop()))

    await worker.start()


if __name__ == "__main__":
    asyncio.run(_main())
