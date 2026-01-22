import importlib.util
import logging
import os
import sys
import time
import uuid

import aiohttp
import asyncio

from dotenv import load_dotenv
from pathlib import Path

from collector.config import CollectorConfiguration
from collector.interface import Scraper, VorgangsScraper, SitzungsScraper

load_dotenv()

### global logging setup
logger = logging.getLogger("collector")
errfile_logger = logging.getLogger("collector_extraction")
parsewr_logger = logging.getLogger("collector_scraper")

import litellm

llmlog = logging.getLogger("LiteLLM")
llmlog.setLevel(logging.WARNING)

# print(logging.root.manager.loggerDict)
# sys.exit(0)
### end global logging setup


async def main(config: CollectorConfiguration):
    global logger

    logger.info("Starting new Scraping Cycle")
    # Load all the scrapers from the scrapers dir
    async with aiohttp.ClientSession(
        connector=aiohttp.TCPConnector(limit_per_host=1)
    ) as session:
        scrapers: list[Scraper] = load_scrapers(config, session)
        scraper_tasks = []
        for scraper in scrapers:
            logger.info(f"Running scraper: {scraper.__class__.__name__}")
            scraper_tasks.append(scraper.run())
        logger.info(f"Running {len(scraper_tasks)} scraper tasks concurrently")
        if not config.linearize:
            ret = await asyncio.gather(*scraper_tasks, return_exceptions=True)
            for r in ret:
                if isinstance(r, Exception):
                    print(f"Some Task failed: {r}")
        else:
            for t in scraper_tasks:
                await t


def load_scrapers(config, session):
    scrapers = []
    available_scrapers = []
    coll_id = uuid.UUID(config.collector_id)
    logger.info(f"Set Collector ID to {coll_id}")
    scraper_path = str((Path(".") / config.scrapers_dir).absolute())
    logger.info(f"Scraper Directory set to: {scraper_path}")
    for filename in os.listdir(config.scrapers_dir):
        if not filename.endswith("_scraper.py"):
            continue
        module_name = filename[:-3]
        module_path = os.path.join(config.scrapers_dir, filename)
        spec = importlib.util.spec_from_file_location(module_name, module_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for attr in dir(module):
            cls = getattr(module, attr)
            if not (
                isinstance(cls, type)
                and (
                    issubclass(cls, VorgangsScraper) or issubclass(cls, SitzungsScraper)
                )
                and cls is not VorgangsScraper
                and cls is not SitzungsScraper
                and not isinstance(cls, module.__class__)
            ):
                continue

            logger.info(f"Found scraper: {cls.__name__}")
            available_scrapers.append(cls.__name__)

            enabled = False or len(config.scrapers) == 0
            for scn in config.scrapers:
                if cls.__name__.lower().startswith(scn.lower()):
                    enabled = True
                    break
            if not enabled:
                continue

            scrapers.append(cls(config, session))

    ## pretty logging
    snames = [type(s).__name__ for s in scrapers]

    logger.info(f"Found these scrapers: {", ".join(available_scrapers)}")
    logger.info(f"Enabled Scrapers are: {", ".join(snames)}")
    return scrapers


if __name__ == "__main__":

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-5s: %(filename)-20s: %(message)s",
    )

    config = CollectorConfiguration()
    config.load()

    logger.info("Starting collector manager.")
    logger.info("Configuration Complete")
    last_run = None
    while True:
        if last_run is not None and time.time() - last_run < config.cycle_time_s:
            logger.info("Last scraping cycle finished, running again in 3 hours. Bye!")
            time.sleep(config.cycle_time_s - (time.time() - last_run))
            continue
        try:
            last_run = time.time()
            asyncio.run(main(config))
        except KeyboardInterrupt:
            logger.info("Shutting down.")
            break
        except Exception as e:
            logger.error(f"Error: {e}")
            continue
