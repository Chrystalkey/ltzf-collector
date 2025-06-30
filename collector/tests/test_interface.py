from collector.interface import Scraper, VorgangsScraper, SitzungsScraper
from collector.config import CollectorConfiguration, Configuration
from oapicode.openapi_client import models
import os
import datetime
import aiohttp
import asyncio
from uuid import uuid4


class MockSitzungsScraper(SitzungsScraper):
    async def listing_page_extractor(self, url):
        return []

    async def item_extractor(self, listing_item):
        return "Nothing"


class MockVorgangsScraper(VorgangsScraper):
    async def listing_page_extractor(self, url):
        return []

    async def item_extractor(self, listing_item):
        return "Nothing"


class MockBaseScraperSuccess(Scraper):
    async def get_cached_result(self, item_key):
        return None

    async def make_cache_key(self, item):
        return "Liebe, Harry. Liebe."

    async def log_item(self, item, override=True):
        return

    async def send_result(self, item):
        return item

    async def listing_page_extractor(self, url):
        return [url, url]

    async def item_extractor(self, listing_item):
        if listing_item == "None":
            return None
        return f"processed:{listing_item}"

    async def store_extracted_result(self, item_key, result):
        return


async def inner_test_process_lpurl():
    config = CollectorConfiguration(
        api_key="test", openai_api_key="test", testing_mode=True
    )
    config.testing_mode = True
    config.oapiconfig = Configuration(host="http://localhost")
    async with aiohttp.ClientSession(
        connector=aiohttp.TCPConnector(limit_per_host=1)
    ) as session:
        cid = uuid4()
        lpu = ["a", "b"]
        scraper = MockBaseScraperSuccess(config, cid, lpu, session)
        ret = await scraper.process_lpurls(scraper.listing_urls)
        assert set(ret) == set(lpu)

        scraper = MockBaseScraperSuccess(config, cid, [], session)
        ret = await scraper.process_lpurls(scraper.listing_urls)
        assert set(ret) == set()


def test_test_process_lpurl():
    asyncio.run(inner_test_process_lpurl())


async def inner_test_process_items():
    config = CollectorConfiguration(
        api_key="test", openai_api_key="test", testing_mode=True
    )
    config.testing_mode = True
    config.oapiconfig = Configuration(host="http://localhost")
    async with aiohttp.ClientSession(
        connector=aiohttp.TCPConnector(limit_per_host=1)
    ) as session:
        cid = uuid4()
        lpu = ["a", "b"]
        scraper = MockBaseScraperSuccess(config, cid, lpu, session)
        results = await scraper.process_items(["item1", "item2", "None"])
        assert set(results) == set(
            [("processed:item1", "item1"), ("processed:item2", "item2"), None]
        )


def test_test_process_items():
    asyncio.run(inner_test_process_items())


async def inner_test_process_results():
    config = CollectorConfiguration(
        api_key="test", openai_api_key="test", testing_mode=True
    )
    config.testing_mode = True
    config.oapiconfig = Configuration(host="http://localhost")
    async with aiohttp.ClientSession(
        connector=aiohttp.TCPConnector(limit_per_host=1)
    ) as session:
        cid = uuid4()
        scraper = MockBaseScraperSuccess(config, cid, [], session)
        ret = await scraper.process_results(
            [
                None,
                None,
                [None, "abc123"],
                [None, "abaölsdkfja0"],
                ["x", "y"],
                Exception("abv123"),
            ]
        )
        assert ret == (1, 4, 1)


def test_test_process_results():
    asyncio.run(inner_test_process_results())


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
        scraper = MockSitzungsScraper(config, cid, [], session)
        scraper.log_item(mock_vg)
        assert os.path.exists(nonexistent_path)
        assert os.path.exists(f"{nonexistent_path}/{cid}.jsonl")
        os.remove(f"{nonexistent_path}/{cid}.jsonl")
        os.removedirs(nonexistent_path)

        cid = uuid4()
        scraper = MockVorgangsScraper(config, cid, [], session)
        scraper.log_item(mock_vg)
        assert os.path.exists(nonexistent_path)
        assert os.path.exists(f"{nonexistent_path}/{cid}.jsonl")
        os.remove(f"{nonexistent_path}/{cid}.jsonl")
        os.removedirs(nonexistent_path)


def test_log_object():
    asyncio.run(inner_test_log_object())
