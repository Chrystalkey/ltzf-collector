import asyncio
import jsondiff
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


def create_scraper(session):
    global SCRAPER_NAME
    config = CollectorConfiguration(
        api_key="test",
        openai_api_key="test",
    )
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
                    soup = BeautifulSoup(hf.read(), features="lxml")
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
                    soup = BeautifulSoup(hf.read(), features="lxml")
                    out_object = models.Vorgang.from_dict(output["result"])
                    assert nullify_uuids(
                        await scraper.soup_to_item(output["origin"], soup)
                    ) == nullify_uuids(out_object), f"Origin: {cases_html[i]}"


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
