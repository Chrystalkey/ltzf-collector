import asyncio
from collector.scrapercache import ScraperCache
from collector.document_builder import DocumentBuilder
from collector.config import CollectorConfiguration
from oapicode.openapi_client import Configuration
from oapicode.openapi_client import models
import uuid

import datetime


class MockDoc(DocumentBuilder):
    def __init__(self, typehint: models.Doktyp, url, session, config):
        self.output = None
        self.full_text = None
        self.hash = None
        self.zp_erstellt = None
        self.zp_modifiziert = None
        self.fileid = uuid.uuid4()
        self.trojanergefahr = None
        self.extraction_success = False
        self.drucksnr = None
        self.tops = None
        super().__init__(typehint, url, session, config)

    def to_dict(self) -> dict:
        return {}

    @classmethod
    def from_dict(cls, dic):
        inst = cls(None, "blub", "entwurf", None)
        return inst

    async def extract_metadata(self):
        pass

    async def extract_semantics(self):
        self.extraction_success = True
        pass

    async def extract(self):
        self.download_success = True
        self.extraction_success = True


def test_documents():
    config = CollectorConfiguration()
    config.load_only_env()
    config.oapiconfig = Configuration(host="http://localhost")

    mock_dok = MockDoc(None, "blub", "entwurf", config)
    success = config.cache.store_dokument("blub", mock_dok)
    assert not success, "Expected to not Store unprocessed Document object"

    asyncio.run(mock_dok.extract())
    success = config.cache.store_dokument("blub", mock_dok)
    assert success, "Expected to successfully store document"
    returned = config.cache.get_dokument("blub")
    assert returned is not None, "Retrieval Failed, returned None"
    assert returned == mock_dok.to_json(), "Retrieved Document did not match stored one"
    raw_ret = config.cache.get_raw("dok:blub")
    assert (
        raw_ret is not None
    ), "Expected Raw Key to be dok:blub, but was unable to retrieve under that name"


def test_vorgang():
    cache = ScraperCache("localhost", 6379)
    config = CollectorConfiguration()
    config.oapiconfig = Configuration(host="http://localhost")

    mock_vg = models.Vorgang.from_dict(
        {
            "api_id": str(uuid.uuid4()),
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
                        "gremium": models.Gremium.from_dict(
                            {"parlament": "BB", "name": "plenum", "wahlperiode": 19}
                        ),
                        "typ": "preparl-regent",
                        "trojanergefahr": 4,
                        "dokumente": [],
                    }
                )
            ],
        }
    )
    success = cache.store_vorgang("blub", mock_vg)
    assert success, "Failed to Store Vorgang"
    returned = cache.get_vorgang("blub")
    assert returned is not None, "Retrieval Failed, returned None"
    assert returned == mock_vg, "Retrieved Vorgang did not match stored one"
    raw_ret = cache.get_raw("vg:blub")
    assert (
        raw_ret is not None
    ), "Expected Raw Key to be vg:blub, but was unable to retrieve under that name"


def test_website():
    cache = ScraperCache("localhost", 6379)
    config = CollectorConfiguration()
    config.oapiconfig = Configuration(host="http://localhost")

    mock_website = "<html>Website data as html or whatever</html>"
    success = cache.store_html("blub", mock_website)
    assert success, "Failed to Store Html Website"
    returned = cache.get_html("blub")
    assert returned is not None, "Retrieval Failed, returned None"
    assert returned == mock_website, "Retrieved Website did not match stored one"
    raw_ret = cache.get_raw("html:blub")
    assert (
        raw_ret is not None
    ), "Expected Raw Key to be html:blub, but was unable to retrieve under that name"
