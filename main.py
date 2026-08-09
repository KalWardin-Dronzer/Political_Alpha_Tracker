"""
Political Alpha Tracker — Daily Pipeline Entry Point

This module parses CLI arguments and runs the pipeline using the PipelineOrchestrator.
"""

import sys
import logging
import argparse

# Fix Windows console emoji printing
if sys.stdout.encoding != 'utf-8' and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

from src.config import DATA_DIR
from src.pipeline_orchestrator import PipelineOrchestrator

# Configure global logging for the pipeline
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(
            DATA_DIR / "pipeline.log",
            mode="a",
            encoding="utf-8",
        ),
    ],
)
logger = logging.getLogger("main")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Political Alpha Tracker — Daily Pipeline"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run without sending alerts or writing to graph",
    )
    parser.add_argument(
        "--scan-volume",
        action="store_true",
        help="Run the Phase 3 Volume Tracker instead of the regular pipeline",
    )
    args = parser.parse_args()

    # Ensure data directory exists
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    try:
        orchestrator = PipelineOrchestrator(dry_run=args.dry_run)
        
        if args.scan_volume:
            orchestrator.run_volume_scan()
        else:
            orchestrator.run_daily_pipeline()
            
    except Exception as e:
        logger.exception(f"Pipeline failed with error: {e}")
        # Try to send error alert
        try:
            from src.cache_manager import CacheManager
            from src.notifier import Notifier
            cache = CacheManager()
            notifier = Notifier(cache)
            notifier.send_system_alert(
                "Pipeline Failure",
                f"Daily pipeline crashed:\n{str(e)[:500]}",
                "ERROR",
            )
        except Exception:
            pass
        sys.exit(1)
