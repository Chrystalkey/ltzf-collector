import logging
import json
import os
import re
import uuid
import datetime  # required because of the eval() call later down the line
from datetime import date as dt_date
from datetime import datetime as dt_datetime

import aiohttp
from bs4 import BeautifulSoup

import openapi_client.models as models
from collector.interface import Scraper
from collector.document import Document
import toml

logger = logging.getLogger(__name__)
NULL_UUID = uuid.UUID("00000000-0000-0000-0000-000000000000")
TEST_DATE = dt_datetime.fromisoformat("1940-01-01T00:00:00+00:00")

sample_url = "https://www.bayern.landtag.de/ajaxcalendar.html?week=17.03.2025&currentDate=1.4.2025&all=true&fullYear=false&contentUid=51169"

# scrapes from yesterday until four weeks from now
class BYLTSitzungScraper(Scraper):
    def __init__(self, config, session: aiohttp.ClientSession):
        start_date = datetime.datetime.now().astimezone(datetime.UTC) - datetime.timedelta(days=1)
        listing_urls = []
        for week in range(4): # four weeks
            date = (start_date + datetime.timedelta(weeks=week)).date()
            listing_urls.append(f"https://www.bayern.landtag.de/ajaxcalendar.html?week={date.day}.{date.month}.{date.year}&currentDate=1.{date.month}.{date.year}&all=true&fullYear=false&contentUid=51169")

        super().__init__(config, uuid.uuid4(), listing_urls, session)
        # Add headers for API key authentication
        self.session.headers.update({"api-key": config.api_key})


    # since a single url yields up to six days
    async def listing_page_extractor(self, url):
        async with self.session.get(url) as result:
            object = json.loads(await result.text())
            listing_soup = BeautifulSoup(object["html"], "html.parser")
            listitems = listing_soup.find_all("li")
            current_date = None
            for li in listitems:
                if li.get("role") == "heading":
                    # this is a heading, usually a date
                    current_date = li.text
                elif li.find("div", class_="agenda-item"):
                    

            resitem = []
            for item in items:
                if "Ausschuss " in item.text or "Plenarsitzung" in item.text:
                    resitem.append(item)
            return [resitem] # an item is a list of individual sessions
    
    async def item_extractor(self, listing_item):
        for sitzung in listing_item:
            pass