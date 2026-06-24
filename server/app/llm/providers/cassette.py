import hashlib
import json
from pathlib import Path

from pydantic import BaseModel

from app.llm.base import ProviderResult

CASSETTE_DIR = Path(__file__).resolve().parent.parent / "cassettes"


def cassette_key(model: str, system: str, prompt: str) -> str:
    payload = json.dumps({"model": model, "system": system, "prompt": prompt}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


class CassetteProvider:
    """Replays recorded responses keyed by (model, system, prompt). Needs no
    network or API key — this is what CI and offline replay use."""

    def __init__(self, cassette_dir: Path = CASSETTE_DIR):
        self.dir = cassette_dir

    def complete(self, model: str, system: str, prompt: str, schema: type[BaseModel]) -> ProviderResult:
        key = cassette_key(model, system, prompt)
        path = self.dir / f"{key}.json"
        if not path.exists():
            raise FileNotFoundError(
                f"No cassette for key {key} (model={model}). "
                f"Record it in live mode or seed {path}."
            )
        rec = json.loads(path.read_text())
        return ProviderResult(
            data=rec["data"],
            prompt_tokens=rec.get("prompt_tokens", 0),
            completion_tokens=rec.get("completion_tokens", 0),
            cache_hit=True,
        )

    def save(self, model: str, system: str, prompt: str, result: ProviderResult) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        key = cassette_key(model, system, prompt)
        (self.dir / f"{key}.json").write_text(
            json.dumps(
                {
                    "data": result.data,
                    "prompt_tokens": result.prompt_tokens,
                    "completion_tokens": result.completion_tokens,
                },
                indent=2,
            )
        )
