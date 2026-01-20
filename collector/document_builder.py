from abc import ABC, abstractmethod
from pathlib import Path
import os
import logging
import hashlib
import json
import openapi_client.models as models

logger = logging.getLogger(__name__)


class DocumentBuilder(ABC):
    def __init__(self, typehint: models.Doktyp, url, session, config):
        assert config
        assert url
        self.output = None
        self.config = config
        self.corrupted = False
        self.local_path = None
        self.url = url
        self.session = session
        self.typehint = typehint

    @abstractmethod
    def to_dict(self) -> dict:
        assert False, "Abstract Method Called"

    @classmethod
    @abstractmethod
    def from_dict(cls, dic):
        assert False, "Abstract Method Called"

    async def download(self) -> Path:
        url_hash = hashlib.sha256(bytes(self.url, encoding="utf-8")).hexdigest()
        if self.config.cache_documents:
            base_dir = Path(self.config.cache_documents)
            if not base_dir.exists():
                os.mkdir(base_dir)
                logger.info(f"Created Directory {base_dir}")
        else:
            base_dir = Path(".")
        obj_path = (base_dir / f"{url_hash}.pdf").absolute()
        self.local_path = obj_path

        if self.config.cache_documents and obj_path.exists() and not obj_path.is_dir():
            return

        async with self.session.get(self.url) as response:
            if response.status != 200:
                raise Exception(
                    f"Failed to download document, status: {response.status}"
                )
            with open(self.local_path, "wb") as f:
                f.write(await response.read())
        if not obj_path.exists() or obj_path.stat().st_size == 0:
            raise Exception("Downloaded file is empty or doesn't exist")
        self.download_success = True

    @abstractmethod
    async def extract_metadata(self):
        assert False, "Abstract Method Called"

    @abstractmethod
    async def extract_semantics(self):
        assert False, "Abstract Method Called"

    async def extract(self):
        await self.extract_metadata()
        await self.extract_semantics()
        self.extraction_success = True

    ## downloads, extracts and packages things into .output (=models.Dokument)
    ## or fetches it from cache if applicable
    async def build(self):
        logger.debug(f"Building document from url: {self.url}")
        cached = self.config.cache.get_dokument(self.url)
        if cached:
            cached = self.from_json(cached)
            if cached.output.typ == self.typehint:
                logger.debug(
                    f"Document with URL {self.url} was found in cache, serving..."
                )
                return cached
            elif cached.typ != self.typehint:
                logger.warning(
                    f"Document with URL {self.url} was found in cache with another type {cached.typ} vs. {self.typehint}, serving..."
                )
                cached.output.typ = self.typehint
                return cached
        logger.info(f"Downloading from {self.url}")
        await self.download()
        logger.info(f"Extracting {self.local_path} / {self.url}")
        await self.extract()
        if self.corrupted:
            logger.warning(
                f"Document with URL {self.url} was corrupted during extraction"
            )
            self.output = None
            return self
        logger.info(f"Storing {self.url} in cache")
        self.config.cache.store_dokument(self.url, self)
        return self

    def __del__(self):
        # cache_documents is not set => no persistence path is given
        # meaning the docs should be cleaned up after using them
        # if the property doesn't even exist it means the doc was loaded from
        # the cache / json, so no file even exists
        if getattr(self.config, "cache_documents", None) is not None:
            self.remove_file()

    def remove_file(self):
        """Clean up any temporary files created during document processing"""
        try:
            if (
                self.local_path
                and Path(self.local_path).exists()
                and self.config.cache_documents is None
            ):
                logger.info(f"Removing {self.local_path}")
                os.remove(self.local_path)
        except Exception as e:
            logger.warning(
                f"Failed to remove temporary PDF file. Exception ignored: {e}"
            )

    def to_json(self) -> dict:
        return json.dumps(self.to_dict(), default=str)

    @classmethod
    def from_json(cls, jstr: str):
        return cls.from_dict(json.loads(jstr))
