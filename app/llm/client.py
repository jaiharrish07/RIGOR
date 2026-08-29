"""LLM client wrapper. Groq primary, OpenRouter fallback.

Both providers are OpenAI-compatible, so we use the `openai` Python
client with different base URLs.
"""
import json
from typing import Protocol

from openai import OpenAI, RateLimitError, APIError
from app.config import settings


class LLMClient(Protocol):
    """Every LLM client must implement this method."""

    def call_structured(
        self,
        system: str,
        user: str,
        tool_name: str,
        tool_schema: dict,
    ) -> dict:
        """Call the LLM with a system + user prompt and expect a structured
        response matching the tool schema. Returns the arguments the model
        passed to the tool."""
        ...


class GroqClient:
    """Groq client. Uses OpenAI-compatible API."""

    def __init__(self, api_key: str, model: str):
        self.client = OpenAI(
            api_key=api_key,
            base_url="https://api.groq.com/openai/v1",
        )
        self.model = model

    def call_structured(self, system, user, tool_name, tool_schema):
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            tools=[{
                "type": "function",
                "function": {
                    "name": tool_name,
                    "description": f"Return structured output for {tool_name}",
                    "parameters": tool_schema,
                },
            }],
            tool_choice={"type": "function", "function": {"name": tool_name}},
            temperature=0,  # deterministic
        )

        tool_calls = response.choices[0].message.tool_calls
        if not tool_calls:
            raise ValueError("LLM did not return a tool call")

        args_str = tool_calls[0].function.arguments
        return json.loads(args_str)


class OpenRouterClient:
    """OpenRouter client. Uses free-tier models as fallback."""

    def __init__(self, api_key: str, model: str):
        self.client = OpenAI(
            api_key=api_key,
            base_url="https://openrouter.ai/api/v1",
        )
        self.model = model

    def call_structured(self, system, user, tool_name, tool_schema):
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            tools=[{
                "type": "function",
                "function": {
                    "name": tool_name,
                    "description": f"Return structured output for {tool_name}",
                    "parameters": tool_schema,
                },
            }],
            tool_choice={"type": "function", "function": {"name": tool_name}},
            temperature=0,
        )

        tool_calls = response.choices[0].message.tool_calls
        if not tool_calls:
            raise ValueError("LLM did not return a tool call")

        args_str = tool_calls[0].function.arguments
        return json.loads(args_str)


class ChainedClient:
    """Try primary first. On rate limit or error, fall back to backup."""

    def __init__(self, primary: LLMClient, backup: LLMClient):
        self.primary = primary
        self.backup = backup

    def call_structured(self, system, user, tool_name, tool_schema):
        try:
            return self.primary.call_structured(system, user, tool_name, tool_schema)
        except (RateLimitError, APIError) as e:
            print(f"Primary LLM failed: {e}. Falling back to backup.")
            return self.backup.call_structured(system, user, tool_name, tool_schema)


def get_default_client() -> LLMClient:
    """Return the standard Groq -> OpenRouter chained client."""
    groq = GroqClient(api_key=settings.groq_api_key, model=settings.groq_model)
    openrouter = OpenRouterClient(api_key=settings.openrouter_api_key, model=settings.openrouter_model)
    return ChainedClient(primary=groq, backup=openrouter)