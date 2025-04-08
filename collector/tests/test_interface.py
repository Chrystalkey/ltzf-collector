from collector.interface import Scraper
from collector.config import CollectorConfiguration, Configuration
from oapicode.openapi_client import models
import os
import datetime
import aiohttp
import asyncio
from uuid import uuid4


class MockScraper(Scraper):
    pass

    async def listing_page_extractor(self, url):
        return []

    async def item_extractor(self, listing_item):
        return "Nothing"


def test_log_object():
    asyncio.run(inner_test_log_object())


async def inner_test_log_object():
    config = CollectorConfiguration(
        api_key="test", openai_api_key="test", testing_mode=True
    )
    config.testing_mode = True
    config.oapiconfig = Configuration(host="http://localhost")
    mock_vg = models.Vorgang.from_dict(
        {
            "api_id": str(uuid4()),
            "titel": "TestTitel",
            "kurztitel": "Kurztesttitel",
            "wahlperiode": 27,
            "verfassungsaendernd": False,
            "typ": "gg-land-volk",
            "ids": [models.VgIdent.from_dict({"typ": "initdrucks", "id": "27/512"})],
            "initiatoren": [
                models.Autor.from_dict(
                    {"person": "Peter Zwegat", "organisation": "Die Linke"}
                )
            ],
            "stationen": [
                models.Station.from_dict(
                    {
                        "titel": "Testtitelstation",
                        "zp_start": datetime.datetime.now().astimezone(datetime.UTC),
                        "zp_modifiziert": datetime.datetime.now().astimezone(
                            datetime.UTC
                        ),
                        "parlament": "BB",
                        "typ": "preparl-regent",
                        "trojanergefahr": 4,
                        "dokumente": [],
                    }
                )
            ],
        }
    )
    nonexistent_path = "nonex_testpath/abc123"
    config.api_obj_log = nonexistent_path
    async with aiohttp.ClientSession(
        connector=aiohttp.TCPConnector(limit_per_host=1)
    ) as session:
        cid = uuid4()
        scraper = MockScraper(config, cid, [], session)
        scraper.log_item(mock_vg)
        assert os.path.exists(nonexistent_path)
        assert os.path.exists(f"{nonexistent_path}/{cid}.json")
        os.remove(f"{nonexistent_path}/{cid}.json")
        os.removedirs(nonexistent_path)
