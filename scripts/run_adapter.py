#!/usr/bin/env python3
"""
nBogne Adapter - Main Entry Point

This script starts the nBogne Adapter for health data transmission over GPRS.

Usage:
    python -m scripts.run_adapter
    python -m scripts.run_adapter --config config/production.yaml
    python -m scripts.run_adapter --config config/default.yaml --log-level DEBUG

Environment Variables:
    NBOGNE_CONFIG_PATH - Path to configuration file
    NBOGNE_LOG_LEVEL - Override log level (DEBUG, INFO, WARNING, ERROR)
    NBOGNE_FACILITY_ID - Override facility ID
    NBOGNE_MEDIATOR_ENDPOINT - Override mediator endpoint
"""

import argparse
import os
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from nbogne import NBogneAdapter, Config
from nbogne.logging_config import setup_logging


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="nBogne Adapter - Health data transmission over GPRS",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Run with default configuration
    python -m scripts.run_adapter
    
    # Run with custom configuration
    python -m scripts.run_adapter --config config/production.yaml
    
    # Run with debug logging
    python -m scripts.run_adapter --log-level DEBUG
    
    # Override facility ID
    NBOGNE_FACILITY_ID=FAC-002 python -m scripts.run_adapter

Environment Variables:
    NBOGNE_CONFIG_PATH      Path to configuration file
    NBOGNE_LOG_LEVEL        Log level (DEBUG, INFO, WARNING, ERROR)
    NBOGNE_FACILITY_ID      Facility identifier
    NBOGNE_MEDIATOR_ENDPOINT Mediator URL
    NBOGNE_MODEM_PORT       Serial port for modem
    NBOGNE_MODEM_APN        Mobile carrier APN
        """
    )
    
    parser.add_argument(
        "--config", "-c",
        default=os.environ.get("NBOGNE_CONFIG_PATH", "config/default.yaml"),
        help="Path to configuration file (default: config/default.yaml)"
    )
    
    parser.add_argument(
        "--log-level", "-l",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        default=os.environ.get("NBOGNE_LOG_LEVEL"),
        help="Override log level"
    )
    
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate configuration and exit without starting"
    )
    
    parser.add_argument(
        "--version", "-v",
        action="store_true",
        help="Show version and exit"
    )
    
    return parser.parse_args()


def main():
    """Main entry point."""
    args = parse_args()
    
    # Handle version flag
    if args.version:
        from nbogne import __version__
        print(f"nBogne Adapter v{__version__}")
        sys.exit(0)
    
    # Load configuration
    config_path = Path(args.config)
    if not config_path.exists():
        print(f"Error: Configuration file not found: {config_path}")
        print(f"Create a configuration file or copy from config/default.yaml")
        sys.exit(1)
    
    try:
        config = Config.from_file(str(config_path), use_env=True)
    except Exception as e:
        print(f"Error: Failed to load configuration: {e}")
        sys.exit(1)
    
    # Override log level if specified
    if args.log_level:
        config.logging.level = args.log_level
    
    # Setup logging
    logger = setup_logging(config.logging)
    
    # Log configuration (redacted)
    logger.info(f"Configuration loaded from: {config_path}")
    logger.debug(f"Configuration: {config.to_dict()}")
    
    # Handle dry run
    if args.dry_run:
        logger.info("Dry run - configuration validated successfully")
        logger.info(f"  Facility: {config.facility.id} ({config.facility.name})")
        logger.info(f"  Mediator: {config.mediator.endpoint}")
        logger.info(f"  EMR: {config.emr.type} at {config.emr.base_url}")
        logger.info(f"  Queue: {config.queue.db_path}")
        logger.info(f"  Server: {config.server.host}:{config.server.port}{config.server.path}")
        sys.exit(0)
    
    # Create and run adapter
    logger.info("=" * 60)
    logger.info("nBogne Adapter Starting")
    logger.info("=" * 60)
    logger.info(f"Facility: {config.facility.id} ({config.facility.name})")
    logger.info(f"Mediator: {config.mediator.endpoint}")
    logger.info(f"EMR Receiver: http://{config.server.host}:{config.server.port}{config.server.path}")
    logger.info("=" * 60)
    
    try:
        adapter = NBogneAdapter(config)
        adapter.run(handle_signals=True)
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)
    
    logger.info("nBogne Adapter stopped")


if __name__ == "__main__":
    main()
