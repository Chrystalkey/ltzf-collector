from litellm import acompletion
import litellm
import logging
import time
import asyncio
from typing import Optional
import json
import jsonschema
from collector.scrapercache import ScraperCache

logger = logging.getLogger("collector")
MIN_TEXT_LEN = 20
MAX_TRIES = 10

import datetime
import asyncio

RATE_COUNT = 2
RATE_INTERVAL = datetime.timedelta(seconds=1.0)

lock = asyncio.Lock()
used = 0
last_tick = datetime.datetime.now()


async def guard_llm_rate():
    global RATE_COUNT, RATE_INTERVAL
    global lock, used, last_tick

    while True:
        await asyncio.sleep(1)
        async with lock:
            now = datetime.datetime.now()
            if now - last_tick > RATE_INTERVAL:
                last_tick = now
                used = 1
                return
            elif used < RATE_COUNT:
                used += 1
                return


litellm.suppress_debug_info = True


class LLMConnector:
    def __init__(
        self,
        model_name: str,
        api_key: Optional[str] = None,
        api_base: Optional[str] = None,
    ):
        self.model_name = model_name
        self.api_key = api_key
        self.api_base = api_base

    @classmethod
    def from_openai(cls, api_key: str, model: str = "gpt-5-nano"):
        return cls(model_name=model, api_key=api_key)

    async def generate(self, prompt: str, text: str) -> str:
        try:
            await guard_llm_rate()
            response = await acompletion(
                model=self.model_name,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a helpful assistant that extracts structured information from documents.",
                    },
                    {"role": "user", "content": f"{prompt}\n\n{text}"},
                ],
                api_key=self.api_key,
                api_base=self.api_base,
                temperature=1.0,
            )
            response._response_headers
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"Error generating response: {e}")
            raise e

    async def extract_info(
        self, prompt: str, text: str, schema: dict, key: str, cache: ScraperCache
    ) -> dict:
        global MIN_TEXT_LEN, MAX_TRIES
        effective_key = f"llm-response:{key}"
        cached = cache.get_raw(effective_key, "LLM Response")
        if cached:
            logger.info(f"Used cached llm response for {key}")
            return json.loads(cached)

        text = text.strip()
        if len(text) < MIN_TEXT_LEN:
            logger.warning(f"Extremely short text: `{text}`")
        tries = 0
        effective_prompt = prompt
        while tries < MAX_TRIES:
            response = await self.generate(effective_prompt, text)
            try:
                obj = json.loads(response)
                jsonschema.validate(obj, schema)
                cache.store_raw(effective_key, response, "LLM Response")
                return obj
            except Exception as e:
                logger.warning(f"Error Occurred: {e}")
                logger.warning(f"Invalid response format from LLM: {response}")
                if tries == MAX_TRIES:
                    raise Exception("Error: Unable to bring the llm to reason")
                tries += 1
                logger.warning(f"Retrying... (Try {tries}/{MAX_TRIES})")
                effective_prompt = (
                    f"Try again ({tries}/{MAX_TRIES}), make sure to adhere to the given structure:\n"
                    + prompt
                )
                continue
