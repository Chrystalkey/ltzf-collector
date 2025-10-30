import importlib.util
import logging
import os
import time
import uuid

import aiohttp
import asyncio

# from openapi_client import Configuration
from dotenv import load_dotenv

from collector.config import CollectorConfiguration
from collector.interface import Scraper, VorgangsScraper, SitzungsScraper

load_dotenv()
logger = logging.getLogger(__name__)


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
    coll_id = uuid.UUID(config.collector_id)
    logger.info(f"Set Collector ID to {coll_id}")
    for filename in os.listdir(config.scrapers_dir):
        if filename.endswith("_scraper.py"):
            if len(config.scrapers) != 0:
                enabled = False
                for scn in config.scrapers:
                    if filename.startswith(scn):
                        enabled = True
                        break
                if not enabled:
                    continue
            module_name = filename[:-3]
            module_path = os.path.join(config.scrapers_dir, filename)
            spec = importlib.util.spec_from_file_location(module_name, module_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            for attr in dir(module):
                cls = getattr(module, attr)
                if (
                    isinstance(cls, type)
                    and (
                        issubclass(cls, VorgangsScraper)
                        or issubclass(cls, SitzungsScraper)
                    )
                    and cls is not Scraper
                    and cls is not VorgangsScraper
                    and cls is not SitzungsScraper
                    and not isinstance(cls, module.__class__)
                ):
                    logger.info(f"Found scraper: {cls.__name__}")
                    scrapers.append(cls(coll_id, config, session))
    return scrapers


if __name__ == "__main__":
    from argparse import ArgumentParser

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s: %(filename)-20s: %(message)s",
    )
    parser = ArgumentParser(prog="collector", description="Bundleing Scrapers")
    parser.add_argument("--run", nargs="*", help="Run only the scrapers specified")
    parser.add_argument(
        "--linearize",
        help="Await all extraction tasks one-by-one instead of gathering",
        action="store_true",
    )
    args = parser.parse_args()
    print(args)
    try:
        logger.info(f"Only these scrapers will run: {args.run}")
        config = CollectorConfiguration(None, None, args.run, args.linearize)
    except Exception:
        config = CollectorConfiguration(None, None)

    logger.info("Starting collector manager.")
    logger.info("Configuration Complete")
    CYCLE_TIME = 3 * 60 * 60  # 3 hours
    last_run = None
    while True:
        if last_run is not None and time.time() - last_run < CYCLE_TIME:
            logger.info("Last scraping cycle finished, running again in 3 hours. Bye!")
            time.sleep(CYCLE_TIME - (time.time() - last_run))
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
