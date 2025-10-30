from collector.scrapercache import ScraperCache
from collector.document import Document
from collector.config import CollectorConfiguration
from oapicode.openapi_client import Configuration
from oapicode.openapi_client import models
from uuid import uuid4

import datetime


def test_documents():
    cache = ScraperCache("localhost", 6379)
    config = CollectorConfiguration(api_key="test", openai_api_key="test")
    config.oapiconfig = Configuration(host="http://localhost")

    mock_dok = Document(None, "blub", "entwurf", config)
    success = cache.store_dokument("blub", mock_dok)
    assert not success, "Expected to not Store unprocessed Document object"
    mock_dok.extraction_success = True
    mock_dok.download_success = True
    success = cache.store_dokument("blub", mock_dok)
    assert success, "Expected to successfully store document"
    returned = cache.get_dokument("blub")
    assert returned is not None, "Retrieval Failed, returned None"
    assert (
        returned.to_json() == mock_dok.to_json()
    ), "Retrieved Document did not match stored one"
    raw_ret = cache.get_raw("dok:blub")
    assert (
        raw_ret is not None
    ), "Expected Raw Key to be dok:blub, but was unable to retrieve under that name"


def test_vorgang():
    cache = ScraperCache("localhost", 6379)
    config = CollectorConfiguration(
        api_key="test",
        openai_api_key="test",
    )
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
    config = CollectorConfiguration(
        api_key="test",
        openai_api_key="test",
    )
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
