import asyncio
from bs4 import BeautifulSoup
import jsondiff
from collector.scrapers.bylt_sitzung_scraper import BYLTSitzungScraper
from collector.convert import sanitize_for_serialization
from collector.config import CollectorConfiguration
from oapicode.openapi_client import Configuration
import os
import json
import glob
import re
import datetime
import aiohttp
from oapicode.openapi_client import models

SCRAPER_NAME = "bylt_sitzung_scraper"


def create_scraper(session):
    global SCRAPER_NAME
    config = CollectorConfiguration(
        api_key="test",
        openai_api_key="test",
    )
    config.oapiconfig = Configuration(host="http://localhost")
    scraper = BYLTSitzungScraper(config, session)
    return scraper


async def inner_bylt_listing_extract():
    async with aiohttp.ClientSession(
        connector=aiohttp.TCPConnector(limit_per_host=1)
    ) as session:
        scraper = create_scraper(session)

        # Find all JSON files in the SCRAPER_NAME subdirectory that start with "session_listing_"
        test_data_dir = os.path.join(os.path.dirname(__file__), SCRAPER_NAME)

        # Find all JSON files in the directory that start with "session_listing_"
        listing_files = glob.glob(os.path.join(test_data_dir, "session_listing_*.json"))

        # Process the first matching file found
        if listing_files:
            with open(listing_files[0], "r", encoding="utf-8") as f:
                listing = json.load(f)
                output = await scraper.listing_page_extractor(listing.get("url"))
                assert len(output) >= len(listing.get("output"))
                for item in range(min(len(output), len(listing.get("output")))):
                    li = output[item]
                    exp = listing["output"][item]
                    assert li[0] == exp["date"]
                    assert len(li[1]) == exp["count"]


def json_difference(a, b):
    return jsondiff.diff(
        json.dumps(a, indent=2, ensure_ascii=False),
        json.dumps(b, indent=2, ensure_ascii=False),
    )


async def inner_bylt_item_extract():
    async with aiohttp.ClientSession(
        connector=aiohttp.TCPConnector(limit_per_host=1)
    ) as session:
        scraper = create_scraper(session)

        test_data_dir = os.path.join(os.path.dirname(__file__), SCRAPER_NAME)

        # Find all JSON files in the directory that start with "vg_item_"
        item_files = glob.glob(os.path.join(test_data_dir, "session_item_*.json"))
        for file in item_files:
            with open(file, "r", encoding="utf-8") as f:
                item_scenario = json.load(f)
                input = item_scenario["input_item"]
                item = (
                    datetime.date.fromisoformat(input["date"]),
                    [BeautifulSoup(ein, "html.parser") for ein in input["html"]],
                )
                loaded = await scraper.item_extractor(item)
                assert loaded is not None
                expected = item_scenario["output"]

                assert len(expected) == len(loaded[1])
                assert item[0] == loaded[0]
                for i in range(len(expected)):
                    exp = expected[i]
                    li = loaded[1][i]
                    assert datetime.datetime.fromisoformat(exp["termin"]) == li.termin
                    gr = li.gremium
                    assert exp["gremium"]["parlament"] == gr.parlament
                    assert exp["gremium"]["wahlperiode"] == gr.wahlperiode
                    assert exp["gremium"]["name"] == gr.name

                    assert exp["nummer"] == li.nummer
                    assert exp["public"] == li.public
                    assert exp["dokumente"] == len(li.dokumente)


def test_bylt_listing_extract():
    asyncio.run(inner_bylt_listing_extract())


def test_bylt_item_extract():
    asyncio.run(inner_bylt_item_extract())
