
from pydantic import BaseModel

from app.llm.base import ProviderResult
from app.llm.providers.cassette import CassetteProvider


class AnthropicProvider:
    """Live Anthropic calls using tool-use to force structured JSON output.
    Records each response to a cassette so the same run can later replay offline."""

    def __init__(self, api_key: str, record: bool = True):
        self.api_key = api_key
        self.record = record
        self._cassette = CassetteProvider()

    def complete(self, model: str, system: str, prompt: str, schema: type[BaseModel]) -> ProviderResult:
        import anthropic  # lazy: only needed in live mode

        client = anthropic.Anthropic(api_key=self.api_key)
        tool = {
            "name": "emit",
            "description": "Return the structured result.",
            "input_schema": schema.model_json_schema(),
        }
        resp = client.messages.create(
            model=model,
            max_tokens=2048,
            system=system,
            tools=[tool],
            tool_choice={"type": "tool", "name": "emit"},
            messages=[{"role": "user", "content": prompt}],
        )

        data = next((b.input for b in resp.content if b.type == "tool_use"), None)
        if data is None:
            raise ValueError("Model did not return a tool_use block")

        result = ProviderResult(
            data=data,
            prompt_tokens=resp.usage.input_tokens,
            completion_tokens=resp.usage.output_tokens,
            cache_hit=False,
        )
        if self.record:
            self._cassette.save(model, system, prompt, result)
        return result
