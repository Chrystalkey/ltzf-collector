from datetime import timedelta
import json
from openapi_client import models
from collector.convert import sanitize_for_serialization
from collector.document import Document
from pathlib import Path
from typing import Optional, Dict, Any
import logging
import redis
import sys


logger = logging.getLogger(__name__)


class ScraperCache:
    """
    Handles caching of scraped data at different levels (Vorgang and Dokumente).
    Provides methods to read from and write to cache using Redis.
    """

    redis_client: Optional[redis.Redis] = None
    default_expiration_min: int = 60 * 24 * 14  # fortnite
    disabled: bool = False

    def __init__(
        self,
        redis_host: str,
        redis_port: int,
        default_expiration_min: int = None,
        disabled: bool = False,
    ):
        global logger
        self.disabled = disabled
        if disabled or redis_host is None or redis_port is None:
            self.disabled = True
            logger.warning("Cacheing disabled")
            return

        if default_expiration_min:
            self.cache_expiry_minutes = default_expiration_min

        try:
            self.redis_client = redis.Redis(
                host=redis_host, port=redis_port, decode_responses=True
            )
            # Test connection
            self.redis_client.ping()
            logger.info(f"Connected to Redis at {redis_host}:{redis_port}")
        except redis.ConnectionError as e:
            logger.error(f"Failed to connect to Redis: {e}")
            sys.exit(1)
        except Exception as e:
            logger.error(f"Unexpected error connecting to Redis: {e}")
            sys.exit(1)

    def store_raw(
        self, key: str, value: str, typehint: str = "Raw Value", expiry: int = None
    ):
        if self.disabled:
            return True
        try:
            logger.debug(f"Storing raw kv-pair with key `{key}`")
            success = self.redis_client.set(key, value)
            if not success:
                logger.warning(f"Storing {typehint} (key=`{key}`) failed!")
                return False
            return True
        except Exception as e:
            logger.error(f"Error storing raw value with key `{key}`")
            return False

    def get_raw(self, key: str, typehint: str = "Raw Value") -> Optional[str]:
        if self.disabled:
            return None
        try:
            success = self.redis_client.get(key)
            if not success:
                logger.warning(f"{typehint} (key=`{key}`) not found in cache")
                return None
            return success
        except Exception as e:
            logger.error(f"Error retrieving raw value with key `{key}`")

    def store_vorgang(self, key: str, value: models.Vorgang, expiry: int = None):
        value = json.dumps(sanitize_for_serialization(value))
        key = f"vg:{key}"
        return self.store_raw(key, value, "Vorgang")

    def store_dokument(self, key: str, value: Document, expiry: int = None):
        """Store Document data in Redis cache

        Only caches documents that were successfully downloaded and processed
        """
        if self.disabled:
            return True
        # Skip caching if document wasn't successfully processed
        if not getattr(value, "download_success", True) or not getattr(
            value, "extraction_success", True
        ):
            logger.warning(f"Not caching document {key} due to failed processing")
            return False

        key = f"dok:{key}"
        value = value.to_json()
        return self.store_raw(key, value, "Dokument")

    def get_vorgang(self, key: str) -> Optional[models.Vorgang]:
        key = f"vg:{key}"
        ret = self.get_raw(key, "Vorgang")
        if ret is None:
            return None
        return models.Vorgang.from_json(ret)

    def get_dokument(self, key: str) -> Optional[Document]:
        key = f"dok:{key}"
        ret = self.get_raw(key, "Dokument")
        if ret is None:
            return None
        return Document.from_json(ret)

    def store_html(self, key: str, value: str, expiry: int = None):
        key = f"html:{key}"
        return self.store_raw(key, value, "Website")

    def get_html(self, key: str):
        key = f"html:{key}"
        return self.get_raw(key, "Website")

    def clear(self):
        """Clear all cache data"""
        if self.disabled:
            return True
        try:
            self.redis_client.flushall()
            logger.info("Cache cleared")
            return True
        except Exception as e:
            logger.error(f"Error clearing cache: {e}")
            return False
