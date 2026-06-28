#!/usr/bin/env python3
"""CLI entry point for the bug-report specification refinement artifact.

Usage:
    python run.py <phase> [options]

Phases:
    enhance               Generate TrajSpec reports
    vanilla_baseline      Generate Agentic-Base reports
    raw_traj_ablation     Ablation: raw Thoughts instead of compressed analysis
    merge                 Merge original + generated reports
"""

import sys

from src.config import load_config
from src.log import setup_logging


def main():
    cfg = load_config()
    logger = setup_logging(log_dir=cfg.log_dir, phase=cfg.phase)

    logger.info(f"Phase: {cfg.phase}")
    logger.info(f"Model: {cfg.openai_model}, Temperature: {cfg.llm_temperature}")

    if cfg.phase == "enhance":
        from src.agents.multi_agent import run_pipeline
        run_pipeline(cfg)

    elif cfg.phase == "vanilla_baseline":
        from src.agents.vanilla_baseline import run_pipeline
        run_pipeline(cfg)

    elif cfg.phase == "raw_traj_ablation":
        from src.agents.raw_trajectory_ablation import run_pipeline
        run_pipeline(cfg)

    elif cfg.phase == "merge":
        from src.merge import run_merge
        if not cfg.merge_original or not cfg.merge_enhanced or not cfg.merge_output:
            logger.error("merge requires --merge-original, --merge-enhanced, --merge-output")
            sys.exit(1)
        run_merge(cfg.merge_original, cfg.merge_enhanced, cfg.merge_output, cfg.merge_strict)

    else:
        logger.error(f"Unknown phase: {cfg.phase}")
        sys.exit(1)

    logger.info("Done.")


if __name__ == "__main__":
    main()
