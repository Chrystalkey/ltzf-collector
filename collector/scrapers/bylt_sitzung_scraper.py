import logging
import json
import os
import re
from typing import List, Tuple
import uuid
import datetime  # required because of the eval() call later down the line
from datetime import date as dt_date
from datetime import datetime as dt_datetime
from urllib.parse import unquote, urlparse, parse_qs

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


## Listing pages are weekly.
## this means a listing page gets extracted into days containing a list of sessions
## currently this is represented by an item being a tuple of datetime and a list of Sitzung
## item = Tuple[datetime.datetime, List[models.Sitzung]]
# scrapes from yesterday until four weeks from now
class BYLTSitzungScraper(Scraper):
    def __init__(self, config, session: aiohttp.ClientSession):
        start_date = datetime.datetime.now().astimezone(
            datetime.UTC
        ) - datetime.timedelta(days=1)
        start_date = start_date - datetime.timedelta(
            weeks=(start_date.weekday - 1)
        )  # reset date to monday of the respective week
        listing_urls = []
        for week in range(4):  # four weeks
            date = (start_date + datetime.timedelta(weeks=week)).date()
            listing_urls.append(
                f"https://www.bayern.landtag.de/ajaxcalendar.html?week={date.day}.{date.month}.{date.year}&currentDate=1.{date.month}.{date.year}&all=true&fullYear=false&contentUid=51169"
            )

        super().__init__(config, uuid.uuid4(), listing_urls, session)
        # Add headers for API key authentication
        self.session.headers.update({"api-key": config.api_key})

    # since a single url yields up to six days
    async def listing_page_extractor(
        self, url
    ) -> List[Tuple[datetime.datetime, List[models.Sitzung]]]:
        async with self.session.get(url) as result:
            object = json.loads(await result.text())
            listing_soup = BeautifulSoup(object["html"], "html.parser")
            listitems = listing_soup.find_all("li")

            day_items = {}
            current_date = None
            for li in listitems:
                if li.get("role") == "heading":
                    # this is a heading, usually a date
                    current_date = parse_natural_date(li.text, 2025)
                    day_items[current_date] = []
                elif li.find("div", class_="agenda-item") != None:
                    agitem = li.find("div", class_="agenda-item")
                    # this is an actual entry with a date
                    title = agitem.find("p", class_="h4").text
                    if title.startswith("Ausschuss für") or title.startswith(
                        "Plenarsitzung"
                    ):
                        day_items[current_date].append(agitem)
                else:
                    continue

            return (
                day_items.items()
            )  # an item is a list of individual sessions grouped by day

    async def item_extractor(
        self, listing_item: Tuple[datetime.datetime, List[models.Sitzung]]
    ):
        # a listing item is a pair of (date, [entries])
        for termin, sitzungen in listing_item:
            for sitzung in sitzungen:
                time = sitzung.find("div", class_="date").text.split(":")

                full_termin = datetime.datetime(
                    year=termin.year,
                    month=termin.month,
                    day=termin.day,
                    hour=int(time[0]),
                    minute=int(time[1]),
                )
                title_line = sitzung.find("p", class_="h4").text
                title = None
                grname = None
                if " - " in title_line:
                    split = title_line.split("-")
                    title = split[1].strip()
                    grname = split[0].strip()
                else:
                    grname = title_line
                gremium = models.Gremium.from_dict(
                    {
                        "parlament": "BY",
                        "wahlperiode": 19,
                        "name": grname,
                    }
                )
                sitzung = models.Sitzung.from_dict(
                    {
                        "titel": title,
                        "termin": full_termin,
                        "gremium": gremium,
                        "nummer": None,  # can be extracted from document link
                        "public": True,  # no idea how to extract that
                        "link": None,  # nonexistent for bavarian sessions
                        "tops": [],  # are the exact state of the last nachtragsTOPs
                        "dokumente": [],  # currently only the TOPs
                        "experten": [] if "Anhörung" in title_line else None,
                    }
                )
                dok_span = sitzung.find("span", class_="agenda-docs")
                internal_docs = []
                for link in dok_span.find_all("a"):
                    doc_link = unquote(link.get("href"))
                    tphint = "tops"

                    ## parse out session number
                    parsed_url = urlparse(doc_link)
                    sitzung["nummer"] = parse_qs(parsed_url.query)["sitzungsnr"][0]

                    ## general document parsing
                    dok = Document(self.session, doc_link, tphint, self.config)
                    dok.run_extraction()
                    sitzung.dokumente.append(dok.package())
                    internal_docs.append(dok)
                ## extract TOPS from the last TOPList
                sitzung["tops"] = self.extract_tops(internal_docs[-1])

    async def extract_tops(self, doc: Document) -> List[models.Top]:
        extraction_prompt = """Du wirst den Text von Tagesordnungspunkten für eine Sitzung erhalten.
        Extrahiere die Tagesordnungspunkte in der Reihenfolge in der sie erscheinen, sowie die damit assoziierten Drucksachennummern.
        Gib dein Ergebnis in JSON aus, wie folgt: {'tops': [{'titel': 'titel des TOPs', 'drucksachen': [<Liste an behandelten Drucksachennummern als string>]}]}
        Antworte mit nichts anderem als den gefragen Informationen, formatiere sie nicht gesondert.END PROMPT"""
        try:
            full_text = self.meta.full_text.strip()
            response = await self.config.llm_connector.generate(
                extraction_prompt, full_text
            )
            object = json.loads(response)
            tops = []
            nummer = 0
            for top in object["tops"]:
                nummer += 1
                tops.append(
                    models.Top.from_dict(
                        {"nummer": nummer, "titel": top["titel"], "dokumente": []}
                    )
                )
                for drucksnr in top["drucksachen"]:
                    split = drucksnr.split("/")
                    periode = split[0]
                    dsnr = split[1]
                    link = f"https://www.bayern.landtag.de/parlament/dokumente/drucksachen/?wahlperiodeid%5b%5d={periode}&dknr={dsnr}&dokumentenart=Drucksache"
                    dokument = None
                    if self.config.cache.get_dokument(link):
                        dokument = self.config.cache.get_dokument(link)
                    else:
                        pre_doc = Document(self.session, link, "entwurf", self.config)
                        pre_doc.run_extraction()
                        dokument = pre_doc.package()
                        self.config.cache.store_dokument(link, dokument)
                    tops.dokumente.append(dokument)
            return tops

        except Exception as e:
            logger.error(f"Error extracting TOPS from Document: {e}")


def parse_natural_date(date: str, year: int) -> datetime.date:
    month_dict = {
        "january": 1,
        "february": 2,
        "march": 3,
        "april": 4,
        "may": 5,
        "june": 6,
        "july": 7,
        "august": 8,
        "september": 9,
        "october": 10,
        "november": 11,
        "december": 12,
    }
    split = date.split(" ")  # monday,|12.|march
    number = int(split[1][:-1])  # 12
    month = split[2].lower()  # march
    return datetime.date(year, month_dict[month], number)
