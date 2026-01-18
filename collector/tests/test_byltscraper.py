import asyncio
import jsondiff
from unittest.mock import Mock
from collector.scrapers.bylt_scraper import BYLTScraper
from collector.convert import sanitize_for_serialization
from collector.config import CollectorConfiguration
from oapicode.openapi_client import Configuration
import os
import json
import glob
import aiohttp
import pytest
from oapicode.openapi_client import models
from bs4 import BeautifulSoup

SCRAPER_NAME = "bylt_scraper"


class FakeLLMConnector:
    async def generate(self, prompt: str, text: str) -> str:
        return "dummy"

    async def extract_info(
        self, text: str, prompt: str, schema: dict, key: str, cache: ScraperCache
    ) -> dict:
        # return a dict with the right schema
        # all strings are "dummy"
        # all lists are empty
        # all numbers are 5
        return {
            "titel": "dummy",
            "kurztitel": "dummy",
            "troja": 5,
            "schlagworte": [],
            "summary": "dummy",
            "meinung": 5,
            "date": "2025-01-01T00:00:00Z",
            "autoren": [],
            "institutionen": [],
        }


def create_scraper(session):
    global SCRAPER_NAME
    from collector.llm_connector import LLMConnector

    os.environ["LTZF_API_KEY"] = "test"
    os.environ["OPENAI_API_KEY"] = "test"
    config = CollectorConfiguration()
    config.llm_connector = FakeLLMConnector()
    config.oapiconfig = Configuration(host="http://localhost")

    scraper = BYLTScraper(config, session)
    return scraper


def json_difference(a, b):
    return jsondiff.diff(
        json.dumps(a, indent=2, ensure_ascii=False),
        json.dumps(b, indent=2, ensure_ascii=False),
    )


# Input offline-saved html, output a known listing
@pytest.mark.asyncio
async def test_soup_to_listing():
    async with aiohttp.ClientSession(
        connector=aiohttp.TCPConnector(limit_per_host=1)
    ) as session:
        scraper = create_scraper(session)
        data_dir = os.path.join(os.path.dirname(__file__), SCRAPER_NAME)
        cases_html = glob.glob(os.path.join(data_dir, "list_*.htmltest"))
        cases_out = glob.glob(os.path.join(data_dir, "list_*.json"))

        if len(cases_html) != len(cases_out):
            assert False, "html/out files of list test cases should be matching"
        cases_html.sort()
        cases_out.sort()

        for i in range(len(cases_html)):
            with open(cases_html[i], "r") as hf:
                with open(cases_out[i], "r") as ho:
                    output = json.load(ho)
                    soup = BeautifulSoup(hf.read(), features="html.parser")
                    assert set(await scraper.soup_to_listing(soup)) == set(
                        output["result"]
                    )


def nullify_uuids(vg: models.Vorgang) -> models.Vorgang:
    import uuid

    NULL_UUID = uuid.UUID("00000000-0000-0000-0000-000000000000")

    vg.api_id = NULL_UUID
    for s in vg.stationen:
        s.api_id = NULL_UUID
        for d in s.dokumente:
            if isinstance(d.actual_instance, str):
                d = str(NULL_UUID)
            else:
                d.actual_instance.api_id = NULL_UUID
        for d in s.stellungnahmen:
            if isinstance(d, models.Dokument):
                d.api_id = NULL_UUID
            elif isinstance(d.actual_instance, str):
                d = str(NULL_UUID)
            else:
                d.actual_instance.api_id = NULL_UUID


@pytest.mark.asyncio
async def test_soup_to_item():
    import os

    os.environ["LTZF_API_KEY"] = "xtest"
    os.environ["OPENAI_API_KEY"] = "ytest"
    # TODO: Input offline-saved html, output a known vorgang
    async with aiohttp.ClientSession(
        connector=aiohttp.TCPConnector(limit_per_host=1)
    ) as session:
        scraper = create_scraper(session)
        data_dir = os.path.join(os.path.dirname(__file__), SCRAPER_NAME)
        cases_html = glob.glob(os.path.join(data_dir, "vorgang_*.htmltest"))
        cases_out = glob.glob(os.path.join(data_dir, "vorgang_*.json"))

        if len(cases_html) != len(cases_out):
            assert False, "html/out files of vorgang test cases should be matching"
        cases_html.sort()
        cases_out.sort()
        scraper.item_count = len(cases_html)

        for i in range(len(cases_html)):
            with open(cases_html[i], "r") as hf:
                with open(cases_out[i], "r") as ho:
                    output = json.load(ho)
                    soup = BeautifulSoup(hf.read(), features="html.parser")
                    out_object = models.Vorgang.from_dict(output["result"])
                    scraped_object = await scraper.soup_to_item(output["origin"], soup)

                    # TODO: This is a stand-in for a correct solution.
                    # we could check more properties
                    assert type(out_object) == type(scraped_object), f"Scenario {i+1}/{len(cases_html)}: {cases_html[i]}"
                    assert len(out_object.stationen) == len(scraped_object.stationen), f"Scenario {i+1}/{len(cases_html)}: {cases_html[i]}"



@pytest.mark.asyncio
async def test_canary_item():
    # TODO: Only "online" version of item test that checks if the format
    # is the same
    pass


@pytest.mark.asyncio
async def test_canary_listing():
    # TODO: Only "online" version of listing test that checks if the format
    # is the same
    pass
