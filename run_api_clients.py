#!/usr/bin/env python3
"""
Script to run all API clients.

Usage:
  python run_api_clients.py
"""
import asyncio
import json
import logging
import sys
import traceback

import config
from interlace.client import InterlaceClient
from nova_api.client import NovaClient
from tronscan.client import TronscanClient
from utils.logger import logger


def get_config():
    """Get configuration from config.py"""
    return {
        'testing': config.get('testing', False),
        'testing_url': config.get('testing_url', '')
    }

def main():
    """Run the selected API client."""
    parser = argparse.ArgumentParser(
        description="Run various API clients"
    )
    parser.add_argument(
        'client',
        choices=['nova', 'interlace', 'tronscan'],
        help='Which client to run'
    )
    parser.add_argument(
        '--address',
        help='TRX address to query (only for tronscan)',
        default=None
    )

    args = parser.parse_args()

    # Determine which script to run
    if args.client == 'nova':
        script = 'run_nova.py'
        command = [sys.executable, script]
    elif args.client == 'interlace':
        script = 'run_interlace.py'
        command = [sys.executable, script]
    elif args.client == 'tronscan':
        script = 'run_tronscan.py'
        command = [sys.executable, script]
        if args.address:
            command.extend(['--address', args.address])

    # Run the selected script
    logger.info(f"Running {script}...")
    try:
        subprocess.run(command, check=True)
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to run {script}: {e}")
        return 1
    except FileNotFoundError:
        logger.error(f"Script {script} not found")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
