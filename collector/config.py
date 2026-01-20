from openapi_client import Configuration
from pathlib import Path
from collector.llm_connector import LLMConnector
from collector.scrapercache import ScraperCache
from uuid import uuid4
from argparse import ArgumentParser

import os
import logging
import sys
import toml

### global logging setup
logger = logging.getLogger(__name__)
import litellm

llmlog = logging.getLogger("LiteLLM")
llmlog.setLevel(logging.WARNING)

# print(logging.root.manager.loggerDict)
# sys.exit(0)
### end global logging setup


class ConfigProp:
    """
    This class caputures all parsing behaviour of a single config option.
    """

    def __init__(
        self,
        attribute_name,
        config_file,
        environment=None,
        argname=None,
        default=None,
        cli_setup_f=None,
        required=False,
    ):
        self.attr = attribute_name
        self.cfg = config_file
        self.env = environment
        self.value = default
        # the value is set by: "default", "config file", "environment", "command line option"
        self.value_set_by = "dft"

        # the arg name is what I have to read out of `args` of the argparse lib
        self.arg = argname
        # the cli setup f is a lambda passed in and called like cli_setup(parser).
        # this then sets up the argument as required for parsing
        self.cli_setup = cli_setup_f

        self.required = required

    def __str__(self):
        output = "Property: " + vars(self) + "\n"


class CollectorConfiguration:
    def __init__(self):
        configurations = []
        # main
        configurations.append(
            ConfigProp(
                "linearize",
                "main.linearize",
                None,
                "linearize",
                False,
                lambda p: p.add_argument(
                    "--linearize",
                    help="Await all extraction tasks one-by-one instead of gathering",
                    action="store_true",
                ),
            )
        )
        configurations.append(
            ConfigProp("collector_id", "main.collector-uuid", "COLLECTOR_ID")
        )
        configurations.append(
            ConfigProp("cycle_time_s", "main.cycle-time-s", "CYCLE_TIME_S", None, 10800)
        )

        # cache config
        configurations.append(
            ConfigProp(
                "redis_host", "cache.redis-host", "REDIS_HOST", None, "localhost"
            )
        )
        configurations.append(
            ConfigProp("redis_port", "cache.redis-port", "REDIS_PORT", None, 6379)
        )
        configurations.append(
            ConfigProp("cache_documents", "cache.document-cache", "DOCUMENT_CACHE")
        )

        # backend
        configurations.append(
            ConfigProp(
                "database_url",
                "backend.ltzf-api-url",
                "LTZF_API_URL",
                None,
                "http://localhost:80",
            )
        )
        # special case: no default but required argument
        configurations.append(
            ConfigProp(
                "api_key",
                "backend.ltzf-api-key",
                "LTZF_API_KEY",
                "ltzf_api_key",
                None,
                lambda p: p.add_argument(
                    "--ltzf-api-key",
                    help="The key with which you auth yourself as collector to the backend",
                ),
                True,
            )
        )

        # scraper configs
        configurations.append(
            ConfigProp(
                "scrapers_dir",
                "scrapers.scraper-dir",
                "SCRAPER_DIR",
                None,
                "./collector/scrapers",
            )
        )
        configurations.append(
            ConfigProp(
                "scrapers",
                "scrapers.scrapers",
                None,
                "run",
                [],
                lambda p: p.add_argument(
                    "--run", help="run only scrapers specified", nargs="*"
                ),
            )
        )
        # logging
        configurations.append(
            ConfigProp("api_obj_log", "logging.api-obj-log", "API_OBJ_LOG", None)
        )
        configurations.append(ConfigProp("logfile", "logging.logfile"))
        configurations.append(ConfigProp("parsewarn", "logging.parsewarn"))
        configurations.append(ConfigProp("errorfile", "logging.errorfile"))

        # llm
        configurations.append(
            ConfigProp(
                "openai_api_key",
                "llm.openai-api-key",
                "OPENAI_API_KEY",
                "openai_api_key",
                None,
                lambda p: p.add_argument(
                    "--openai-api-key", help="Your key to run an llm with"
                ),
                True,
            )
        )
        self.config_file = None
        self.dump_config = False
        self.configurations = configurations

    def load_only_env(self):
        # environment configuration
        for config in self.configurations:
            if config.env is None:
                continue
            env_prop = os.getenv(config.env)
            if env_prop:
                if type(config.value) == type(int):
                    config.value = int(env_prop)
                elif type(config.value) == type(list):
                    config.value = env_prop.split(";")
                else:
                    config.value = env_prop
                config.value_set_by = "env"
        for config in self.configurations:
            if config.required and config.value is None:
                missing_required.append(config)
            setattr(self, config.attr, config.value)
        self.oapiconfig = Configuration(host=self.database_url)
        self.oapiconfig.api_key["apiKey"] = self.api_key

        self.cache = ScraperCache(self.redis_host, self.redis_port)

        self.llm_connector = LLMConnector.from_openai(self.openai_api_key)

    def load(self):
        parser = ArgumentParser(prog="collector", description="Bundled Scrapers")
        parser.add_argument("--config-file", help="the config file to use")
        parser.add_argument(
            "--dump-config",
            help="Await all extraction tasks one-by-one instead of gathering",
            action="store_true",
        ),

        for config in self.configurations:
            if config.arg:
                config.cli_setup(parser)
        args = parser.parse_args()

        # config file
        config_file = None
        if not args.config_file and Path("collector.toml").is_file():
            config_file = "collector.toml"
        elif args.config_file:
            config_file = args.config_file
        self.config_file = config_file

        if config_file:
            with open(config_file) as f:
                loaded = toml.load(f)
                for config in self.configurations:
                    if config.cfg:
                        cfg_path = config.cfg.split(".")

                        if (
                            cfg_path[0] not in loaded
                            or cfg_path[1] not in loaded[cfg_path[0]]
                        ):
                            continue
                        cfg_prop = loaded[cfg_path[0]][cfg_path[1]]
                        if cfg_prop:
                            config.value = cfg_prop
                            config.value_set_by = "cfg"
        # environment configuration
        for config in self.configurations:
            if config.env is None:
                continue
            env_prop = os.getenv(config.env)
            if env_prop:
                if type(config.value) == type(int):
                    config.value = int(env_prop)
                elif type(config.value) == type(list):
                    config.value = env_prop.split(";")
                else:
                    config.value = env_prop
                config.value_set_by = "env"
        # passed argument configuration
        for config in self.configurations:
            if not config.arg:
                continue
            arg_prop = getattr(args, config.arg, None)
            if arg_prop:
                if type(config.value) == type(int):
                    config.value = int(arg_prop)
                else:
                    config.value = arg_prop
                config.value_set_by = "cli"

        # now do something with it
        if args.dump_config:
            logger.info(str(self))
            sys.exit(0)
        else:
            missing_required = []
            for config in self.configurations:
                if config.required and config.value is None:
                    missing_required.append(config)
                setattr(self, config.attr, config.value)
            if len(missing_required) > 0:
                output = ""
                for mr in missing_required:
                    output += mr.attr + ", "
                logger.critical(f"Missing required configurations: \n{output}")
                sys.exit(1)

        ### now go and initialize the secondary objects
        self.oapiconfig = Configuration(host=self.database_url)
        self.oapiconfig.api_key["apiKey"] = self.api_key

        self.cache = ScraperCache(self.redis_host, self.redis_port)

        self.llm_connector = LLMConnector.from_openai(self.openai_api_key)

    def __str__(self):
        output = "Configuration of Collector\n"
        output += f"Config File: {self.config_file}\n"
        output += "dft=default|env=environment var|cli=command line argument\n"
        for config in self.configurations:
            name = config.cfg or config.attr
            missing = config.required and config.value is None
            output += f"{config.value_set_by}{name:.>25}: {config.value}"
            if missing:
                output += " MISSING\n"
            else:
                output += "\n"
        return output
