import datetime
from hashlib import sha256
import json
import logging
from abc import ABC, abstractmethod
from datetime import timedelta
from typing import Any, List, Optional, Tuple
from uuid import UUID
from pathlib import Path

import aiohttp
import asyncio
from collector.convert import sanitize_for_serialization
from collector.config import CollectorConfiguration

import openapi_client
from openapi_client import models

logger = logging.getLogger(__name__)


class Scraper(ABC):
    listing_urls: List[str] = []
    result_objects: List[models.Vorgang] = []
    collector_id: UUID = None

    config: CollectorConfiguration = None

    session: aiohttp.ClientSession = None
    session_headers: dict[str, str] = {}

    def __init__(
        self,
        config: CollectorConfiguration,
        collector_id: UUID,
        listing_urls: List[str],
        session: aiohttp.ClientSession,
    ):
        self.collector_id = collector_id
        self.listing_urls = listing_urls
        self.config = config
        self.result_objects = []
        self.session = session
        self.session_headers = {}
        global logger
        logger.info(
            f"Initialized {self.__class__.__name__} with {len(self.listing_urls)} listing urls"
        )
        logger.info(f"Set Collector ID to {self.collector_id}")

    @abstractmethod
    def log_item(self, item: models.Vorgang, override=True):
        assert False, "Abstract Base Method Called"

    async def senditem(self, item: Any) -> Optional[Any]:
        assert False, "Abstract Base Method Called"

    @abstractmethod
    async def run(self):
        assert False, "Abstract Base Method Called"

    async def item_processing(self, item):
        """Process an item by extracting and sending it to the API"""
        try:
            extracted_item = await self.item_extractor(item)
            sent_item = await self.senditem(extracted_item)
            return [sent_item, item]
        except Exception as e:
            logger.error(f"Error processing item {item}: {e}", exc_info=True)
            raise

    # extracts the listing page that is behind self.listing_url into the urls of individual pages
    @abstractmethod
    async def listing_page_extractor(self, url: str) -> List[Any]:
        """
        Extract a listing page into individual item URLs

        Args:
            url: The listing page URL

        Returns:
            A list of item URLs found on the listing page
        """
        assert False, "Warn: Abstract Method Called"

    # extracts the individual pages containing all info into a Vorgang object
    @abstractmethod
    async def item_extractor(self, listing_item: Any) -> Any:
        """
        Extract an individual item into a Vorgang object

        Args:
            listing_item: The item URL or identifier

        Returns:
            A Vorgang object containing the extracted information
        """
        assert False, "Warn: Abstract Method Called"


class VorgangsScraper(Scraper):
    def log_item(self, item: models.Vorgang, override=True):
        logdir = (
            self.config.api_obj_log
            if self.config.api_obj_log
            else ("locallogs" if override else None)
        )
        if logdir is not None:
            logger.info(f"Logging Item to {logdir}")
            try:
                filepath = Path(logdir) / f"{self.collector_id}.json"
                if not filepath.parent.exists():
                    logger.info(f"Creating Filepath: {filepath.parent}")
                    filepath.parent.mkdir(parents=True)
                with filepath.open("a", encoding="utf-8") as file:
                    file.write(json.dumps(sanitize_for_serialization(item)) + ",\n")
            except Exception as e:
                logger.error(f"Failed to write to API object log: {e}")

    async def senditem(self, item: models.Vorgang) -> Optional[models.Vorgang]:
        global logger
        logger.info(f"Sending Item with id `{item.api_id}` to Database")
        logger.debug(f"Collector ID: {self.collector_id}")

        # Save to log file if configured
        self.log_item(item)

        # Send to API
        with openapi_client.ApiClient(self.config.oapiconfig) as api_client:
            api_instance = openapi_client.DefaultApi(api_client)
            try:
                ret = api_instance.vorgang_put(str(self.collector_id), item)
                logger.info(f"API Response: {ret}")
                return item
            except openapi_client.ApiException as e:
                logger.error(f"API Exception: {e}")
                if e.status == 422:
                    logger.error(sanitize_for_serialization(item))
                    logger.error(
                        "Unprocessable Entity, tried to send item(see above)\n"
                    )
                    self.log_item(item, True)
                elif e.status == 401:
                    logger.error("Authentication failed. Check your API key.")
                return None
            except Exception as e:
                logger.error(f"Unexpected error sending item to API: {e}")
                return None

    async def run(self):
        """
        Main method to run the scraper:
        1. Extract all listing pages
        2. Extract individual items
        3. Send items to API
        4. Store in cache
        """
        global logger
        item_list = []
        tasks = []
        logger.debug(f"{self.__class__.__name__}::extract")

        # Extract all listing pages
        try:
            for lpage in self.listing_urls:
                logger.debug(f"Initializing listing page extractor for {lpage}")
                tasks.append(self.listing_page_extractor(lpage))

            # Wait for all listing page extractor tasks to complete
            item_list = await asyncio.gather(*tasks, return_exceptions=True)

            # Handle any exceptions from listing page extractors
            for i, result in enumerate(item_list):
                if isinstance(result, Exception):
                    logger.error(
                        f"Error extracting listing page {self.listing_urls[i]}: {result}"
                    )
                    item_list[i] = []  # Replace exception with empty list

            # Flatten the list of lists into a set to eliminate duplicates
            iset = set(x for xs in item_list if isinstance(xs, list) for x in xs)
        except Exception as e:
            logger.error(f"Error extracting listing pages: {e}", exc_info=True)
            return

        # Process all items
        tasks = []
        processed_count = 0
        skipped_count = 0

        for item in iset:
            # Check if item is already in cache
            cached = self.config.cache.get_vorgang(str(item))
            if cached is not None:
                logger.debug(f"URL {item} found in cache, skipping...")
                skipped_count += 1
                continue

            logger.debug(f"Initializing item extractor for {item}")
            tasks.append(self.item_processing(item))
            processed_count += 1

        logger.info(
            f"Processing {processed_count} items, skipped {skipped_count} cached items"
        )

        # Process all items
        temp_res = []
        if tasks:
            try:
                # for task in tasks:
                #     await task
                temp_res = await asyncio.gather(*tasks, return_exceptions=True)
            except Exception as e:
                logger.error(f"Error during item extraction: {e}", exc_info=True)

        # Process results and store in cache
        success_count = 0
        error_count = 0

        for result in temp_res:
            if not isinstance(result, Exception) and result and result[0]:
                obj = result[0]
                item = result[1]
                self.result_objects.append(obj)
                self.config.cache.store_vorgang(str(item), obj)
                success_count += 1
            else:
                error_count += 1
                if isinstance(result, Exception):
                    logger.error(
                        f"Item extraction failed with exception: {result}",
                        exc_info=True,
                    )
                else:
                    logger.error(f"Item extraction failed with result: {result}")

        logger.info(
            f"Extractor {self.__class__.__name__} completed: {success_count} successes, {error_count} errors"
        )


class SitzungsScraper(Scraper):
    def log_item(self, item, override=True):
        logdir = (
            self.config.api_obj_log
            if self.config.api_obj_log
            else ("locallogs" if override else None)
        )
        if logdir is not None:
            logger.info(f"Logging Item to {logdir}")
            try:
                filepath = Path(logdir) / f"{self.collector_id}.json"
                if not filepath.parent.exists():
                    logger.info(f"Creating Filepath: {filepath.parent}")
                    filepath.parent.mkdir(parents=True)
                with filepath.open("a", encoding="utf-8") as file:
                    file.write(json.dumps(sanitize_for_serialization(item)) + ",\n")
            except Exception as e:
                logger.error(f"Failed to write to API object log: {e}")

    async def senditem(
        self, item: Tuple[datetime.datetime, List[models.Sitzung]]
    ) -> Optional[Tuple[datetime.datetime, List[models.Sitzung]]]:
        global logger
        logger.info(f"Sending Item with Date `{item[0]}` to Database")
        logger.debug(f"Collector ID: {self.collector_id}")

        # Save to log file if configured
        self.log_item(item)

        # Send to API
        with openapi_client.ApiClient(self.config.oapiconfig) as api_client:
            api_instance = openapi_client.DefaultApi(api_client)
            try:
                ret = api_instance.kal_date_put(
                    parlament=models.Parlament.BY, datum=item[0], sitzung=item[1]
                )
                logger.info(f"API Response: {ret}")
                return item
            except openapi_client.ApiException as e:
                logger.error(f"API Exception: {e}")
                if e.status == 422:
                    logger.error(sanitize_for_serialization(item))
                    logger.error(
                        "Unprocessable Entity, tried to send item(see above)\n"
                    )
                    self.log_item(item, True)
                elif e.status == 401:
                    logger.error("Authentication failed. Check your API key.")
                return None
            except Exception as e:
                logger.error(f"Unexpected error sending item to API: {e}")
                return None

    async def run(self):
        """
        Main method to run the scraper:
        1. Extract all listing pages
        2. Extract individual items
        3. Send items to API
        4. Store in cache
        """
        global logger
        item_list = []
        tasks = []
        logger.debug(f"{self.__class__.__name__}::extract")

        # Extract all listing pages
        try:
            for lpage in self.listing_urls:
                logger.debug(f"Initializing listing page extractor for {lpage}")
                tasks.append(self.listing_page_extractor(lpage))

            # Wait for all listing page extractor tasks to complete
            item_list = await asyncio.gather(*tasks, return_exceptions=True)

            # Handle any exceptions from listing page extractors
            for i, result in enumerate(item_list):
                if isinstance(result, Exception):
                    logger.error(
                        f"Error extracting listing page {self.listing_urls[i]}: {result}"
                    )
                    item_list[i] = []  # Replace exception with empty list

            # Flatten the list of lists into a set to eliminate duplicates
            iset = set(x for xs in item_list if isinstance(xs, list) for x in xs)
        except Exception as e:
            logger.error(f"Error extracting listing pages: {e}", exc_info=True)
            return

        # Process all items
        tasks = []
        processed_count = 0
        skipped_count = 0

        for item in iset:
            # Check if item is already in cache
            item_hash = f"sz:{str(sha256(str(item).encode()))}"
            cached = self.config.cache.get_raw(item_hash)
            if cached is not None:
                logger.debug(f"URL {item} found in cache, skipping...")
                skipped_count += 1
                continue

            logger.debug(f"Initializing item extractor for {item}")
            tasks.append(self.item_processing(item))
            processed_count += 1

        logger.info(
            f"Processing {processed_count} items, skipped {skipped_count} cached items"
        )

        # Process all items
        temp_res = []
        if tasks:
            try:
                # for task in tasks:
                #     await task
                temp_res = await asyncio.gather(*tasks, return_exceptions=True)
            except Exception as e:
                logger.error(f"Error during item extraction: {e}", exc_info=True)

        # Process results and store in cache
        success_count = 0
        error_count = 0

        for result in temp_res:
            if not isinstance(result, Exception) and result and result[0]:
                obj = result[0]
                item = result[1]
                self.result_objects.append(obj)
                item_hash = f"sz:{str(sha256(str(item).encode()))}"
                self.config.cache.store_raw(item_hash, str(obj))
                success_count += 1
            else:
                error_count += 1
                if isinstance(result, Exception):
                    logger.error(
                        f"Item extraction failed with exception: {result}",
                        exc_info=True,
                    )
                else:
                    logger.error(f"Item extraction failed with result: {result}")

        logger.info(
            f"Extractor {self.__class__.__name__} completed: {success_count} successes, {error_count} errors"
        )
