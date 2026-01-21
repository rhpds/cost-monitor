#!/usr/bin/env python3
"""
Historical Data Collection Job

Collects cost data for the specified historical period from all configured
cloud providers and stores it in the database.
"""

import os
import sys
import asyncio
import logging
from datetime import date, timedelta
from pathlib import Path

# Add the project root to the Python path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.api.data_service import collect_missing_data
from src.config.settings import get_config


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def main():
    """Main collection function"""
    logger.info("🚀 Starting historical data collection job")

    # Get configuration
    try:
        config = get_config()
        logger.info("✅ Configuration loaded successfully")
    except Exception as e:
        logger.error(f"❌ Failed to load configuration: {e}")
        return 1

    # Get historical days from environment variable
    historical_days = int(os.getenv('HISTORICAL_DAYS', '7'))
    end_date = date.today()
    start_date = end_date - timedelta(days=historical_days)

    logger.info(f"📅 Collecting data for date range: {start_date} to {end_date} ({historical_days} days)")

    # Define providers to collect from
    providers = ['aws', 'azure', 'gcp']

    try:
        # Collect missing data for the specified date range
        await collect_missing_data(start_date, end_date, providers)

        logger.info("🎉 Historical data collection completed successfully")
        return 0

    except Exception as e:
        logger.error(f"❌ Historical data collection failed: {e}")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)