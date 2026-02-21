"""
wsgi.py — Production entry point for Render / Gunicorn
Runs initial forecast on import, then serves Flask dashboard.
Background scheduler runs in a separate thread.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config.settings import settings

logging.basicConfig(
    level=getattr(logging, settings.log_level),
    format="%(asctime)s  %(levelname)-8s  %(name)-24s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("tpv.wsgi")

from shared.message_bus import MessageBus
from agents.tpv_agent import TPVAgent
from web_app_v2 import create_app

# Initialize agent and run first forecast
bus = MessageBus()
agent = TPVAgent(bus)

def _run_initial_forecast():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(agent.run_daily_forecast())
    logger.info("Initial forecast complete")
    # Start the daily scheduler in this thread's event loop
    loop.run_until_complete(agent._daily_scheduler())

# Run forecast + scheduler in background thread
forecast_thread = threading.Thread(target=_run_initial_forecast, daemon=True)
forecast_thread.start()

# Create Flask app for gunicorn
app = create_app(agent)

logger.info("WSGI app ready — TPV Predictions Agent")
