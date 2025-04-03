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

            day_items = {}
            current_date = None
            for li in listitems:
                if li.get("role") == "heading":
                    # this is a heading, usually a date
                    current_date = parse_natural_date(li.text)
                    day_items[current_date] = []
                elif li.find("div", class_="agenda-item") != None:
                    agitem = li.find("div", class_="agenda-item")
                    # this is an actual entry with a date
                    title = agitem.find("p", class_="h4").text
                    if title.startswith("Ausschuss für") or title.startswith("Plenarsitzung"):
                        day_items[current_date].append(agitem)
                else:
                    continue
            
            return day_items.items() # an item is a list of individual sessions ordered by day
    
    async def item_extractor(self, listing_item):
        # a listing item is a pair of (date, [entries])
        for (termin, sitzungen) in listing_item:
            for sitzung in sitzungen:
                time = sitzung.find("div", class_="date").text.split(":")

                full_termin = datetime.datetime(year=termin.year, month=termin.month,day=termin.day,
                                                hour=int(time[0]), minute=int(time[1]))
                title_line = sitzung.find("p", class_="h4").text
                title = None
                grname = None
                if " - " in title_line:
                    split = title_line.split("-")
                    title = split[1].strip()
                    grname = split[0].strip()
                else:
                    grname = title_line
                gremium  = models.Gremium.from_dict({
                    "parlament": "BY",
                    "wahlperiode": 19,
                    "name": grname
                })
                sitzung = models.Sitzung.from_dict({
                    "titel": title,
                    "termin": full_termin,
                    "gremium": gremium,
                    "nummer" : None,
                    "public" : True,
                    "link": None,
                    "tops": [],
                    "dokumente": [],
                    "experten": [] if "Anhörung" in title_line else None,
                })
                dok_span = sitzung.find("span", class_="agenda-docs")
                for link in dok_span.find_all("a"):
                    doc_link = link.get("href")
                    # for each doc build + extract document


def parse_natural_date(date) -> datetime.date:
    split = date.split(" ")
    number = split[0][:-1]
    month = split[1].lower()
