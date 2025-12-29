import datetime
from hashlib import sha256
import json
import logging
from abc import ABC, abstractmethod
from datetime import timedelta
import sys
from typing import Any, List, Optional, Set, Tuple
from uuid import UUID
from pathlib import Path

import aiohttp
import asyncio
from collector.convert import sanitize_for_serialization
from collector.config import CollectorConfiguration

import openapi_client
from openapi_client import models
import openapi_client.api
import openapi_client.api.collector_schnittstellen_api
import openapi_client.api_client

logger = logging.getLogger(__name__)


class Scraper(ABC):
    listing_urls: List[str] = []
    scraper_id: UUID = None

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
        assert isinstance(config, CollectorConfiguration)
        assert isinstance(collector_id, UUID)
        assert isinstance(session, aiohttp.ClientSession)
        self.scraper_id = collector_id
        self.listing_urls = listing_urls
        self.config = config
        self.session = session
        self.session_headers = {}
        self.item_count = 0
        self.items_done = 0
        global logger
        logger.info(
            f"Initialized {self.__class__.__name__} with {len(self.listing_urls)} listing urls"
        )

    # Process Listing Page URLs
    # This takes in a list of listing page urls and outputs
    # a deduplicated, cleaned set of extracted items
    async def process_lpurls(self, lpurls: List[str]) -> Set[Any]:
        global logger
        logger.info("Processing Listing Page URLs Now")

        tasks = []
        try:
            for lpage in self.listing_urls:
                tasks.append(self.listing_page_extractor(lpage))
                logging.info(f"Extracting from url `{lpage}`")

            # Wait for all listing page extractor tasks to complete
            item_list = []
            if self.config.linearize:
                for t in tasks:
                    item_list.append(await t)
            else:
                item_list = await asyncio.gather(*tasks, return_exceptions=True)
            self.item_count = len(item_list)
            # Handle any exceptions from listing page extractors
            for i, result in enumerate(item_list):
                if isinstance(result, Exception):
                    logger.error(
                        f"{self.__class__.__name__}: Error extracting listing page {self.listing_urls[i]}: {result}"
                    )
                    item_list[i] = []  # Replace exception with empty list

            # Flatten the list of lists into a set to eliminate duplicates
            iset = set(x for xs in item_list if isinstance(xs, list) for x in xs)
            return iset
        except Exception as e:
            logger.error(
                f"{self.__class__.__name__}: Error gathering listing page extraction: {e}",
                exc_info=True,
            )

    # This is a helper to gather-await extracting and sending in one go instead of
    # first gathering then sending in bulk. Returns a None if the extraction failed or
    # returned no result, and a tuple containing ({input item}, {extracted and sent item}) and the extracted item
    # for comparison
    async def helper_extract_send_item(self, item):
        """Process an item by extracting and sending it to the API"""
        extracted_item = await self.item_extractor(item)
        logger.info(f"Extracted Item {item}")
        if extracted_item:
            ## because: If sent_item is None something went wrong
            sent_item = await self.send_result(extracted_item)
            ## cache the shit out of the items
            key = await self.make_cache_key(item)
            await self.store_extracted_result(key, extracted_item)
            return (sent_item, item)
        else:
            return None

    # Process Items
    # Takes in a set of items, outputs an extracted + sent set of results
    async def process_items(self, items: Set[Any]) -> List[Any]:
        tasks = []
        processed_count = 0
        skipped_count = 0
        logger.info("Processing Items Now")

        for item in sorted(items):
            # Check if item is already in cache
            key = await self.make_cache_key(item)
            cached = await self.get_cached_result(key)
            if cached is not None:
                logger.debug(f"{key} found in cache, skipping...")
                skipped_count += 1
                continue

            tasks.append(self.helper_extract_send_item(item))
            processed_count += 1

        logger.info(
            f"{self.__class__.__name__}: Processing {processed_count} items, skipping {skipped_count} cached items"
        )
        temp_res = []
        try:
            # temp_res = await asyncio.gather(*tasks, return_exceptions=True)
            if self.config.linearize:
                for t in tasks:
                    temp_res.append(await t)
            else:
                temp_res = await asyncio.gather(*tasks, return_exceptions=True)
        except Exception as e:
            logger.error(
                f"{self.__class__.__name__}: Error during item extraction gathering: {e}",
                exc_info=True,
            )

        return temp_res

    # Process Results
    # Takes in a set of results (=extracted+sent items) and does some cleanup and
    # error handling.
    # The input is in the format [(extracted_item, input_item), ...]
    async def process_results(self, results: List[Any]) -> Tuple[int, int, int]:
        output = []
        success_count = 0
        error_count = 0
        ignored_count = 0
        for result in results:
            if result and not isinstance(result, Exception) and result[0]:
                extracted_item = result[0]
                output.append(extracted_item)

                success_count += 1
            elif not result or (not isinstance(result, Exception) and not result[0]):
                ignored_count += 1
                continue
            else:
                error_count += 1
                if isinstance(result, Exception):
                    logger.error(
                        f"{self.__class__.__name__}: Item extraction failed with exception: {result}",
                        exc_info=True,
                    )
                else:
                    logger.error(
                        f"{self.__class__.__name__}: Item extraction failed with result: {result}"
                    )
        logger.info(
            f"Extractor {self.__class__.__name__} completed: {success_count} successes, {error_count} errors"
        )
        return (success_count, ignored_count, error_count)

    async def run(self):
        global logger
        # Extract all listing pages
        iset = await self.process_lpurls(self.listing_urls)

        # Process + send all items them
        rset = await self.process_items(iset)

        # do cleanup and logging, post-action
        await self.process_results(rset)

    # abstract method to be implemented below. Taking in an item,
    # this method's job is to look up wether this item was already processed
    # (= is being found in cache by means of make_cache_key)
    # and return it if that is the case. Returns none otherwise.
    @abstractmethod
    async def get_cached_result(self, item_key: str) -> Optional[Any]:
        assert False, "Abstract Base Method Called"

    @abstractmethod
    async def store_extracted_result(self, item_key: str, result: Any) -> Optional[Any]:
        assert False, "Abstract Base Method Called"

    # this method is used for logging purposes and is encouraged to be used in get_cached_result
    # as key. The idea is to transform the item to the key used in the database to extract whatever result.
    @abstractmethod
    async def make_cache_key(self, item: Any) -> Optional[str]:
        assert False, "Abstract Base Method Called"

    # function to log an item to a predetermined location on error or on debug mode (config.api_obj_log is not None)
    # @item: the item to be logged
    # @override: if set, log to default directory, regardless of wether config.api_obj_log has been set
    @abstractmethod
    def log_item(self, item: Any, override=True):
        assert False, "Abstract Base Method Called"

    # function to take an item and send it. Should a recoverable error occurr, (meaning if sending again later might work)
    # the method must return None. On success, return the item that was put in
    # otherwise, raise an exception
    @abstractmethod
    async def send_result(self, item: Any) -> Optional[Any]:
        assert False, "Abstract Base Method Called"

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
                filepath = Path(logdir) / f"{self.scraper_id}.jsonl"
                if not filepath.parent.exists():
                    logger.info(f"Creating Filepath: {filepath.parent}")
                    filepath.parent.mkdir(parents=True)
                with filepath.open("a", encoding="utf-8") as file:
                    file.write(json.dumps(item, default=str) + ",\n")
            except Exception as e:
                logger.error(f"Failed to write to API object log: {e}")

    async def send_result(self, item: models.Vorgang) -> Optional[models.Vorgang]:
        global logger
        logger.info(f"Sending Item with id `{item.api_id}` to Database")
        logger.debug(f"Collector ID: {self.scraper_id}")

        # Save to log file if configured
        self.log_item(item)

        # Send to API
        with openapi_client.ApiClient(self.config.oapiconfig) as api_client:
            api_instance = openapi_client.api.collector_schnittstellen_api.CollectorSchnittstellenApi(
                api_client
            )
            try:
                _ret = api_instance.vorgang_put(str(self.scraper_id), item)
                logger.info("Object sent successfully")
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
                    logger.critical("Authentication failed. Check your API key.")
                    sys.exit(1)
                return None
            except Exception as e:
                logger.error(f"Unexpected error sending item to API: {e}")
                return None

    async def make_cache_key(self, item):
        return str(item)  # item is just a url in this case. easy!

    async def get_cached_result(self, item_key):
        return self.config.cache.get_vorgang(item_key)

    async def store_extracted_result(self, item_key, result):
        self.config.cache.store_vorgang(item_key, result)


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
                filepath = Path(logdir) / f"{self.scraper_id}.jsonl"
                if not filepath.parent.exists():
                    logger.info(f"Creating Filepath: {filepath.parent}")
                    filepath.parent.mkdir(parents=True)
                with filepath.open("a", encoding="utf-8") as file:
                    file.write(json.dumps(item, default=str) + ",\n")
            except Exception as e:
                logger.error(f"Failed to write to API object log: {e}")

    async def store_extracted_result(self, item_key, result):
        self.config.cache.store_raw(item_key, str(result))

    async def send_result(
        self, item: Tuple[datetime.datetime, List[models.Sitzung]]
    ) -> Optional[Tuple[datetime.datetime, List[models.Sitzung]]]:
        global logger
        logger.info(f"Sending Item with Date `{item[0]}` to Database")
        logger.debug(f"Collector ID: {self.scraper_id}")

        # Save to log file if configured
        self.log_item(item)

        # Send to API
        with openapi_client.ApiClient(self.config.oapiconfig) as api_client:
            api_instance = openapi_client.api.collector_schnittstellen_api.CollectorSchnittstellenApi(
                api_client
            )
            try:
                ret = api_instance.kal_date_put(
                    x_scraper_id=str(self.scraper_id),
                    parlament=models.Parlament.BY,
                    datum=item[0],
                    sitzung=item[1],
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
                    logger.critical("Authentication failed. Check your API key.")
                    sys.exit(1)
                return None
            except Exception as e:
                logger.error(f"Unexpected error sending item to API: {e}")
                return None

    async def get_cached_result(self, item_key):
        return self.config.cache.get_raw(item_key)

    async def make_cache_key(self, item):
        return f"sz:{str(sha256(str(item).encode()))}"
