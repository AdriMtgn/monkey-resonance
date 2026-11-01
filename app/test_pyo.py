import pyo
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

logger.info("Creating server...")
s = pyo.Server(nchnls=2)

logger.info("Booting...")
s.boot()

logger.info("Starting...")
s.start()

logger.info("SUCCESS - Server running!")

import time
time.sleep(2)

logger.info("Stopping...")
s.stop()

logger.info("Done!")
