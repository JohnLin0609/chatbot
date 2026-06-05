"""CLI: batch-score captured eval traces with the LLM-as-judge.

  python -m interfaces.judge            # one batch (judge_batch_size traces)
  python -m interfaces.judge --limit 5  # judge up to 5 un-judged traces
  python -m interfaces.judge --all      # judge every un-judged trace
"""

import argparse
import asyncio
import logging

from core.config import get_settings
from core.eval.factory import build_judge_runner
from core.persistence.db import create_engine, create_sessionmaker

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("judge-cli")


async def run(limit: int | None, judge_all: bool) -> None:
    settings = get_settings()
    sm = create_sessionmaker(create_engine(settings.postgres_dsn))
    runner = build_judge_runner(settings, sm)

    before = await runner.status()
    log.info("traces: %d total, %d judged, %d un-judged",
             before["total_traces"], before["judged"], before["unjudged"])

    batch = None if judge_all else (limit or settings.judge_batch_size)
    res = await runner.run_batch(limit=batch)
    log.info("run %s: judged %d, skipped %d, remaining %d",
             res["judge_run_id"][:8], res["judged"], res["skipped"], res["remaining"])

    after = await runner.status()
    log.info("avg scores: %s", after["avg_scores"])


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Batch-judge eval traces")
    ap.add_argument("--limit", type=int, default=None, help="max traces to judge")
    ap.add_argument("--all", action="store_true", help="judge every un-judged trace")
    args = ap.parse_args()
    asyncio.run(run(args.limit, args.all))
