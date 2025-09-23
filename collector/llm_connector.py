from litellm import acompletion
import logging
from typing import Optional
import json
import jsonschema

logger = logging.getLogger(__name__)
MIN_TEXT_LEN = 20


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
    def from_openai(cls, api_key: str, model: str = "gpt-4o-mini"):
        return cls(model_name=model, api_key=api_key)

    async def generate(self, prompt: str, text: str) -> str:
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
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"Error generating response: {e}")
            raise e

    async def extract_info(self, text: str, prompt: str, schema: dict) -> dict:
        global MIN_TEXT_LEN
        MAX_TRIES = 10

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
                return obj
            except Exception as e:
                logger.warning(f"Invalid response format from LLM: {response}")
                if tries == MAX_TRIES:
                    raise Exception("Error: Unable to bring the llm to reason")
                tries += 1
                effective_prompt = (
                    f"Try again ({tries}/{MAX_TRIES}), make sure to adhere to the given structure:\n"
                    + prompt
                )
                continue
