from litellm import acompletion
import logging
import time
import asyncio
from typing import Optional

logger = logging.getLogger(__name__)
MAX_CALLS = 20
PER_SECONDS = 30


class RateLimit:
    def __init__(self, max_calls, per_seconds):
        self.max_calls = max_calls
        self.per_seconds = per_seconds
        self.call_count = 0
        self.reset_time = time.time() + per_seconds
        self.lock = asyncio.Lock()

    async def acquire_slot(self):
        while True:
            now = time.time()
            if now >= self.reset_time:
                await self.lock.acquire()
                self.call_count = 0
                self.lock.release()
                self.reset_time = time.time() + self.per_seconds
            if self.call_count < self.max_calls:
                await self.lock.acquire()
                self.call_count += 1
                self.lock.release()
                return
            asyncio.sleep(2.0)


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
        self.rate_limit = RateLimit(MAX_CALLS, PER_SECONDS)

    @classmethod
    def from_openai(cls, api_key: str, model: str = "gpt-4o-mini"):
        return cls(model_name=model, api_key=api_key)

    async def generate(self, prompt: str, text: str) -> str:
        await self.rate_limit.acquire_slot()

        try:
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
                temperature=0.0,
            )
            response._response_headers
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"Error generating response: {e}")
            raise e
