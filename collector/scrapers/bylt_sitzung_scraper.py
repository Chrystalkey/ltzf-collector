import logging
import json
import os
import re
import sys
from typing import Any, FrozenSet, List, Tuple
import uuid
import datetime  # required because of the eval() call later down the line
from datetime import date as dt_date
from datetime import datetime as dt_datetime
from urllib.parse import unquote, urlparse, parse_qs

import aiohttp
from bs4 import BeautifulSoup

import openapi_client.models as models
from collector.interface import SitzungsScraper
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
class BYLTSitzungScraper(SitzungsScraper):
    def __init__(self, config, session: aiohttp.ClientSession):
        start_date = datetime.datetime.now(datetime.UTC)
        start_date -= datetime.timedelta(days=1)
        start_date = start_date - datetime.timedelta(
            days=(start_date.weekday() - 1)
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
    ## List[Tuple[datetime.datetime, FrozenSet[models.Sitzung]]]
    async def listing_page_extractor(self, url: str) -> List[Any]:
        async with self.session.get(url) as result:
            object = json.loads(await result.text())
            # check if there is actual data contained in this listing
            if "Diese Woche finden keine Sitzungen statt." in object["html"]:
                logger.info(f"No Entries in Week listed at url {url}")
                return []
            listing_soup = BeautifulSoup(object["html"], "html.parser")
            listitems = listing_soup.find_all("li")

            day_items = {}
            current_date = None
            for li in listitems:
                if li.get("role") == "heading":
                    # this is a heading, usually a date
                    current_date = parse_natural_date(li.text.strip(), 2025)
                    if current_date is None:
                        print(li)
                        continue
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
            output = []
            for k, v in day_items.items():
                output.append((k, frozenset(v)))
            # an item is a list of individual sessions grouped by day
            return output

    ## listing_item: Tuple[datetime.datetime, FrozenSet[models.Sitzung]]

    async def item_extractor(self, listing_item: Any) -> Any:
        # a listing item is a pair of (date, [entries])
        termin, sitzungen = listing_item
        retsitz = (termin, [])
        for sitzung_soup in sitzungen:
            time = sitzung_soup.find("div", class_="date").text.split(":")

            full_termin = datetime.datetime(
                year=termin.year,
                month=termin.month,
                day=termin.day,
                hour=int(time[0]),
                minute=int(time[1]),
                tzinfo=datetime.UTC,
            )
            title_line = sitzung_soup.find("p", class_="h4").text
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
            sitz_dict = {
                "api_id": str(uuid.uuid4()),
                "titel": title,
                "termin": full_termin,
                "gremium": gremium,
                "nummer": None,  # is extracted from document link(s) below
                "public": True,  # no idea how to extract that
                "link": None,  # nonexistent for bavarian sessions
                "tops": [],  # are the exact state of the last nachtragsTOPs
                "dokumente": [],  # currently only the TOPs
                "experten": [] if "Anhörung" in title_line else None,
            }
            dok_span = sitzung_soup.find("span", class_="agenda-docs")
            internal_docs = []
            for link in dok_span.find_all("a"):
                doc_link = unquote(link.get("href"))
                tphint = "tops"

                ## parse out session number
                parsed_url = urlparse(doc_link)
                sitz_dict["nummer"] = int(parse_qs(parsed_url.query)["sitzungsnr"][0])

                ## general document parsing
                dok = Document(self.session, doc_link, tphint, self.config)
                await dok.run_extraction()
                sitz_dict["dokumente"].append(dok.package())
                internal_docs.append(dok)
            ## extract TOPS from the last TOPList
            sitz_dict["tops"] = await self.extract_tops(internal_docs[-1])
            if "Anhörung" in title_line:
                sitz_dict["experten"] = await self.extract_experts(internal_docs[-1])
            retsitz[1].append(models.Sitzung.from_dict(sitz_dict))
        return retsitz

    async def extract_experts(self, doc: Document) -> List[models.Autor]:
        prompt = """Du erhältst gleich die Tagesordnung einer Anhörung. Analysisere die Tagesordnung und ermittle alle Experten, die angehört wurden.
        Erstelle einen JSON-Datensatz mit namen "autoren".
        Bilde für jeden Experten einen JSON-Datensatz mit folgenden Parametern:

        {
        name: Name des/der Expert:in,
        organisation: Organisation des/der Expert:in. Falls unbekannt lasse das Feld leer,
        fachgebiet: Fachgebiet des/der Expert:in
        }

        Antworte mit nichts anderem als dem gefragen Objekt, formatiere es nicht gesondert. 

        Hier ist der Text:
"""
        try:
            full_text = doc.meta.full_text.strip()
            try:
                response = await self.config.llm_connector.generate(prompt, full_text)
                if "```json" in response:
                    response = response[8:-3]
                object = json.loads(response)
            except Exception as e:
                logger.error(f"Invalid Response from LLM: {e}, got {response}")
                raise
            auts = []
            for atobj in object["autoren"]:
                auts.append(
                    models.Autor.from_dict(
                        {
                            "person": atobj["name"],
                            "organisation": atobj["organisation"],
                            "fachgebiet": atobj["fachgebiet"],
                        }
                    )
                )
            return auts
        except Exception as e:
            logger.error(f"Error extracting Experts from Document: {e}")
            return []

    async def extract_tops(self, doc: Document) -> List[models.Top]:
        extraction_prompt = """Du erhältst gleich die Tagesordnung einer Ausschusssitzung oder Plenarsitzung. Analysiere die Tagesordnung und ermittle alle Tagesordnungspunkte über die beraten wurde und Erstelle ein JSON-Objekt mit dem Namen TOP. 
        Bilde für jeden Gesetzentwurf einen JSON-Datensatz mit folgenden Parametern:

{
titel: Titel des Tagesordnungspunkts oder Diskussionspunkts,
oeff: true falls der TOP öffentlich ist, sonst false,
drucksachen: Drucksachennummern des Gesetzentwurfs als Liste, zum Beispiel 20/12345 (wenn mehrere genannt sind, nenne nur die erste, wenn keine genannt sind lasse die Liste leer), 
anhoerung: Wenn es sich um eine Anhörung handelt, setze das Feld zu true, sonst false.}

Antworte mit nichts anderem als dem gefragen Objekt, formatiere es nicht gesondert. 

Hier ist der Text:"""

        try:
            full_text = doc.meta.full_text.strip()
            try:
                response = await self.config.llm_connector.generate(
                    extraction_prompt, full_text
                )
                if "```json" in response:
                    response = response[8:-3]
                object = json.loads(response)
            except Exception as e:
                logger.error(f"Invalid Response from LLM: {e}, got {response}")
                raise
            tops = []
            nummer = 0
            for top in object["TOP"]:
                nummer += 1
                topdict = {"nummer": nummer, "titel": top["titel"], "dokumente": []}
                for drucksnr in top["drucksachen"]:
                    if "BR" in drucksnr:
                        # bundesratsdrucksachen
                        logger.warning(
                            "Bundesratsdrucksachbehandlung ist noch nicht implementiert"
                        )
                        continue
                    elif not re.fullmatch(r"(Drs. )?\d{2}/\d+", drucksnr):
                        logger.warning(
                            f"Unbekanntes Format für eine Drucksachennummer: {drucksnr}, skipping"
                        )
                        continue
                    if drucksnr.startswith("Drs. "):
                        drucksnr = drucksnr[6:]
                    split = drucksnr.split("/")
                    periode = split[0]
                    dsnr = split[1]
                    link = f"https://www.bayern.landtag.de/parlament/dokumente/drucksachen/?wahlperiodeid%5b%5d={periode}&dknr={dsnr}&dokumentenart=Drucksache"

                    async def transform_link(link):
                        async with self.session.get(link) as link_html:
                            soup = BeautifulSoup(await link_html.text(), "html.parser")
                            doklink = soup.select_one(
                                "div.row:nth-child(6) > div:nth-child(1) > h4:nth-child(1) > a:nth-child(1)"
                            )["href"]
                            return doklink

                    try:
                        link = await transform_link(link)
                    except Exception as e:
                        logger.warning(
                            f"Error Extracting actual pdf link from linked drucksnr: {e} for drucksnr: {drucksnr}"
                        )
                        raise
                    dokument = None
                    if self.config.cache.get_dokument(link):
                        pre_doc = self.config.cache.get_dokument(link)
                        dokument = pre_doc.package()
                        dokument = models.DokRef(dokument)
                    else:
                        pre_doc = Document(self.session, link, "entwurf", self.config)
                        await pre_doc.run_extraction()
                        dokument = pre_doc.package()
                        self.config.cache.store_dokument(link, pre_doc)
                        dokument = models.DokRef(dokument)
                    topdict["dokumente"].append(dokument)
                try:
                    doks = topdict["dokumente"]
                    topdict["dokumente"] = []
                    tops.append(models.Top.from_dict(topdict))
                    tops[-1].dokumente = doks
                except Exception as e:
                    logger.error(f"Dictionary: {topdict}")
                    logger.error(
                        f"Error: Unable to build TOP object from dictionary: {e}"
                    )
            return tops

        except Exception as e:
            logger.error(f"Error extracting TOPS from Document: {e}")
            return []


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
    try:
        split = date.split(" ")  # monday,|12.|march
        while "" in split:
            split.remove("")
        number = int(split[1][:-1])  # 12
        month = split[2].lower()  # march
        return datetime.date(year, month_dict[month], number)
    except Exception as e:
        logger.error(f"Error converting Date `{date}` into date object because: {e}!")
        return None
