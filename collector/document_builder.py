from abc import ABC, abstractmethod
from pathlib import Path
import logging
import json
import openapi_client.models as models

logger = logging.getLogger(__name__)


class DocumentBuilder(ABC):
    def __init__(self, typehint: models.Doktyp, url, session, config):
        self.output = None
        self.config = config
        self.corrupted = False
        self.url = url
        self.session = session
        self.typehint = typehint
        self.output = None

    def to_dict(self) -> dict:
        return {"output": self.output.to_dict()}

    @classmethod
    def from_dict(cls, dic):
        inst = cls(None, None, None, None)
        inst.output = (
            models.Dokument.from_dict(dic["output"]) if dic["output"] else None
        )
        return inst

    async def download(self) -> Path:
        async with self.session.get(self.url) as response:
            if response.status != 200:
                raise Exception(
                    f"Failed to download document, status: {response.status}"
                )

            with open(f"{self.fileid}.pdf", "wb") as f:
                f.write(await response.read())
        out = Path(f"{self.fileid}.pdf")
        if not out.exists() or out.stat().st_size == 0:
            raise Exception("Downloaded file is empty or doesn't exist")

    @abstractmethod
    async def extract_metadata(self):
        assert False, "Abstract Method Called"

    @abstractmethod
    async def extract_semantics(self):
        assert False, "Abstract Method Called"

    async def extract(self):
        await self.extract_metadata()
        await self.extract_semantics()

    async def build(self) -> models.Dokument:
        logger.debug(f"Building document from url: {self.url}")
        cached = self.config.cache.get_dokument(self.url)
        if cached and cached.output.typ == self.typehint:
            logger.info(f"Document with URL {self.url} was found in cache, serving...")
            return cached.output
        elif cached and cached.typ != self.typehint:
            logger.info(f"Document with URL {self.url} was found in cache, serving...")
            cached.output.typ = self.typehint
            return cached.output
        logger.info(f"Downloading from {self.url}")
        await self.download()
        logger.info(f"Extracting {self.fileid}.pdf / {self.url}")
        await self.extract()
        if self.corrupted:
            logger.warning(
                f"Document with URL {self.url} was corrupted during extraction"
            )
            self.output = None
        logger.info(f"Storing {self.url} in cache")
        self.config.cache.store_dokument(self.url, self)
        return self.output

    def to_json(self) -> dict:
        return json.dumps(self.to_dict())

    @classmethod
    def from_json(cls, jstr: str):
        return cls.from_dict(json.loads(jstr))
