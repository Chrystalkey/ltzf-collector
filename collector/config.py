from openapi_client import Configuration
from pathlib import Path
import os
import logging
from collector.llm_connector import LLMConnector
from collector.scrapercache import ScraperCache
import sys
from uuid import uuid4

from argparse import ArgumentParser

logger = logging.getLogger(__name__)
import litellm

llmlog = logging.getLogger("LiteLLM")
llmlog.setLevel(logging.WARNING)


class CollectorConfiguration:
    oapiconfig: Configuration = None
    llm_connector: LLMConnector = None
    redis_host: str = None
    redis_port: int = None
    ltzfdb: str = None
    api_obj_log: str = None
    scrapers_dir: Path = None
    api_key: str = None
    trojan_threshold: int = None
    cache: ScraperCache = None
    scrapers: list = []
    linearize: bool = False
    cache_documents: str = None

    def __init__(self):
        global logger
        unset_keys = []
        parser = ArgumentParser(prog="collector", description="Bundleing Scrapers")
        parser.add_argument("--run", nargs="*", help="Run only the scrapers specified")
        parser.add_argument(
            "--linearize",
            help="Await all extraction tasks one-by-one instead of gathering",
            action="store_true",
        )
        parser.add_argument(
            "--dump-config",
            help="Dumps the Configuration and then exits",
            default=False,
            action="store_true",
        )
        parser.add_argument(
            "--ltzf-api-url",
            help="The URL to the Backend you want to use",
            default=os.getenv("LTZF_API_URL", "http://localhost:80"),
        )
        parser.add_argument(
            "--ltzf-api-key",
            help="The API key for the backend",
            default=os.getenv("LTZF_API_KEY"),
        )
        parser.add_argument(
            "--redis-host",
            help="the redis host",
            default=os.getenv("REDIS_HOST", "localhost"),
        )
        parser.add_argument(
            "--redis-port",
            help="the redis port",
            default=os.getenv("REDIS_PORT", "6379"),
        )
        args = parser.parse_args()

        if args.run:
            logger.info(f"Only these scrapers will run: {args.run}")
            self.scrapers = args.run
        else:
            logger.info("All available Scrapers will be run")
            self.scrapers = []
        self.linearize = args.linearize

        # Database
        self.database_url = args.ltzf_api_url
        self.api_key = args.ltzf_api_key
        if not self.api_key:
            unset_keys.append("LTZF_API_KEY")

        # Caching
        self.redis_host = args.redis_host
        self.redis_port = int(args.redis_port)
        self.cache = ScraperCache(self.redis_host, self.redis_port)
        self.cache_documents = os.getenv("DOCUMENT_CACHE")

        # Scraperdir
        self.scrapers_dir = self.scrapers_dir or os.path.join(
            os.path.dirname(__file__), "scrapers"
        )

        # Log Files
        # self.logfile = os.getenv("LOG_FILE")
        # self.errorlog= os.getenv("ERROR_FILE")

        # Thresholds and optionals
        self.api_obj_log = os.getenv("API_OBJ_LOG")
        if not os.getenv("COLLECTOR_ID"):
            logger.debug("Generating new UUID for Collector Identification")
            self.collector_id = str(uuid4())
        else:
            self.collector_id = os.getenv("COLLECTOR_ID")
        if os.getenv("CYCLE_TIME_S"):
            self.cycle_time_s = int(os.getenv("CYCLE_TIME_S"))
        else:
            self.cycle_time_s = 3 * 60 * 60  # == 3 Stunden

        # OpenAPI Configuration
        self.oapiconfig = Configuration(host=self.database_url)
        logger.info(f"Setting API Key to {self.api_key[:16]}")
        self.oapiconfig.api_key["apiKey"] = self.api_key

        # LLM Connector, currently only openai is supported
        oai_key = os.getenv("OPENAI_API_KEY")
        if oai_key:
            self.llm_connector = LLMConnector.from_openai(oai_key)
        else:
            unset_keys.append("OPENAI_API_KEY")
        if len(unset_keys) > 0:
            logger.critical(
                f"The following environment variables are not set: {', '.join(unset_keys)}"
            )
            sys.exit(1)

        ## argument dump if necessary
        if args.dump_config:
            print(vars(self))
            sys.exit(0)
