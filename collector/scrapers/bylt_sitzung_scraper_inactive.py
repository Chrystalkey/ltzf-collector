import logging
import json
from typing import Any, List
import uuid
import datetime
from datetime import date as dt_date
from datetime import datetime as dt_datetime
from urllib.parse import unquote, urlparse, parse_qs

import aiohttp
from bs4 import BeautifulSoup

import openapi_client.models as models
from collector.interface import SitzungsScraper
from collector.scrapers.by_dok import ByTagesordnung

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
        start_date = dt_datetime.now(datetime.UTC)
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
    ## List[Tuple[datetime.datetime, FrozenSet[models.Sitzung as BS4]]]
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
                        logger.warning(f"Current Date not parsable: {li}")
                        continue
                    day_items[current_date] = []
                elif li.find("div", class_="agenda-item") is not None:
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

    ## listing_item: Tuple[datetime.datetime, FrozenSet[models.Sitzung as BS4]]

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
                dok = await ByTagesordnung(
                    tphint, doc_link, self.session, self.config
                ).build()
                sitz_dict["dokumente"].append(dok)
                internal_docs.append(dok)
            ## extract TOPS from the last TOPList
            if len(internal_docs) == 0:
                logger.warning("Sitzung was found without available number or TOP File")
                continue
            sitz_dict["tops"] = await self.extract_tops(internal_docs[-1])
            if "Anhörung" in title_line:
                sitz_dict["experten"] = await self.extract_experts(internal_docs[-1])
            retsitz[1].append(models.Sitzung.from_dict(sitz_dict))
        return retsitz

    ## this is a special function working on an already built document
    ## most importantly, this expands the scope of a "single-run extraction"
    ## but I think here is the right place for it.
    async def extract_experts(self, doc: ByTagesordnung) -> List[models.Autor]:
        prompt = """Du erhältst gleich die Tagesordnung einer Anhörung. Analysisere die Tagesordnung und ermittle alle Experten, die angehört wurden.
        Erstelle eine json-style liste mit Einträgen wiefolgt:.
        Bilde für jeden Experten einen JSON-Datensatz mit folgenden Parametern:

        {
            name: Name des/der Expert:in,
            organisation: Organisation des/der Expert:in.,
            fachgebiet: Fachgebiet des/der Expert:in
        }

        Antworte mit nichts anderem als dem gefragen Objekt, formatiere es nicht gesondert. 

        Hier ist der Text:"""
        schema = {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "organisation": {"type": "string"},
                    "fachgebiet": {"type": "string"},
                },
                "required": ["name", "organisation", "fachgebiet"],
            },
        }
        try:
            experts_raw = await self.config.llm_connector.extract_info(
                self.full_text[0 : min(3000, len(self.full_text))],
                prompt,
                schema,
                f"experts:{doc.url}",
                self.config.cache,
            )
            expert_dicts = json.loads(experts_raw)

            experts = []
            for atobj in expert_dicts:
                experts.append(models.Autor.from_dict(atobj))
            return experts

        except Exception as e:
            logger.error(f"Error extracting semantics: {e}")
            logger.error(
                "LLM Response was inadequate or contained ill-formatted fields even after retry"
            )
            self.corrupted = True
            raise


def parse_natural_date(date: str, year: int) -> dt_date:
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
        return dt_date(year, month_dict[month], number)
    except Exception as e:
        logger.error(f"Error converting Date `{date}` into date object because: {e}!")
        return None


if __name__ == "__main__":
    import asyncio

    async def minimain():
        from argparse import ArgumentParser
        from collector.config import CollectorConfiguration
        from oapicode.openapi_client import Configuration
        import aiohttp
        import json
        from dotenv import load_dotenv

        def jdmp(o):
            import uuid
            import datetime
            import bs4

            if isinstance(o, uuid.UUID) or isinstance(o, bs4.element.Tag):
                return str(o)
            if isinstance(o, datetime.datetime):
                return o.astimezone(datetime.UTC).isoformat()
            if isinstance(o, datetime.date):
                return o.isoformat()
            print(type(o))
            if isinstance(o, frozenset):
                return json.dumps(list(o), indent=1, default=jdmp)
            return json.dumps(o, indent=1, default=jdmp)

        load_dotenv()
        parser = ArgumentParser(
            prog="byltsitzung scraper",
            description="Parst Sitzungen aus dem Bayerischen Landtag",
        )
        parser.add_argument("-l", "--listing", nargs="*")
        parser.add_argument("-i", "--item", nargs="*")
        parser.add_argument("-n", "--no-cache", action="store_true")
        parser.add_argument("-d", "--debug-logging", action="store_true")
        args = parser.parse_args()

        lstn = [] if not args.listing else args.listing
        itms = [] if not args.item else args.item

        logging.basicConfig(
            level=(logging.DEBUG if args.debug_logging else logging.INFO),
            format="%(asctime)s | %(levelname)-8s: %(filename)-20s: %(message)s",
        )
        async with aiohttp.ClientSession() as session:
            config = CollectorConfiguration(api_key="test", openai_api_key="test")
            config.oapiconfig = Configuration(host="http://localhost")
            config.cache.disabled = args.no_cache
            scraper = BYLTSitzungScraper(config, session)
            for lurl in lstn:
                dic = {"origin": lurl, "result": []}
                dic["result"] = await scraper.listing_page_extractor(lurl)
                print(json.dumps(dic["result"], indent=1, default=jdmp))

            scraper.item_count = len(itms)

            for itm in itms:
                dic = {"origin": lurl, "result": []}
                dic["result"] = (await scraper.item_extractor(itm)).to_dict()
                print(json.dumps(dic, indent=1, default=jdmp))

    asyncio.run(minimain())
