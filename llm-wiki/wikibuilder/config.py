"""Build configuration, loaded from a YAML file (see config.yaml)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml


@dataclass
class LLMConfig:
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4o-mini"
    # The key is read from this environment variable; `api_key` in the YAML
    # takes precedence but should only be used for local, non-committed files.
    api_key_env: str = "OPENAI_API_KEY"
    api_key: str = ""
    # None -> not sent (some models, e.g. OpenAI reasoning models, only accept the default)
    temperature: Optional[float] = 0.3
    max_tokens: int = 8192
    # Name the token limit is sent under: "max_tokens" (vLLM, Ollama, older
    # OpenAI models) or "max_completion_tokens" (newer OpenAI models).
    token_param: str = "max_tokens"
    timeout: float = 300.0
    max_attempts: int = 3
    # Upper bound on concurrent requests across the whole build.
    max_concurrency: int = 8
    # Passed through to chat.completions.create, e.g. to disable thinking on
    # vLLM/Qwen: {"chat_template_kwargs": {"enable_thinking": false}}
    extra_body: Dict[str, Any] = field(default_factory=dict)

    def resolve_api_key(self) -> str:
        return self.api_key or os.environ.get(self.api_key_env, "") or "EMPTY"


@dataclass
class Config:
    raw_dir: Path
    wiki_dir: Path
    state_dir: Path
    include: List[str] = field(default_factory=lambda: ["**/*.md"])
    language: str = "English"
    # focused | standard | exhaustive (WeKnora WikiConfig.ExtractionGranularity)
    granularity: str = "standard"
    # Business instructions appended to extraction / page-writing prompts.
    extraction_instructions: str = ""
    content_instructions: str = ""
    chunk_size: int = 1000
    max_content_chars: int = 32768
    docs_per_batch: int = 5
    map_parallel: int = 4
    reduce_parallel: int = 8
    log_llm_calls: bool = True
    # Options for the output format module (wikibuilder/wiki_format.py).
    format: Dict[str, Any] = field(default_factory=dict)
    llm: LLMConfig = field(default_factory=LLMConfig)


def load_dotenv(path: Path) -> List[str]:
    """Load KEY=VALUE lines from a .env file into os.environ, overriding
    variables already set in the shell. Returns the names that were set."""
    if not path.is_file():
        return []
    names = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.removeprefix("export ").partition("=")
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key:
            os.environ[key] = value
            names.append(key)
    return names


def load_config(path: Path) -> Config:
    path = Path(path).resolve()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    base = path.parent
    load_dotenv(base / ".env")

    def _path(key: str, default: str) -> Path:
        p = Path(data.pop(key, default)).expanduser()
        return p if p.is_absolute() else (base / p).resolve()

    llm = LLMConfig(**(data.pop("llm", None) or {}))
    return Config(
        raw_dir=_path("raw_dir", "raw"),
        wiki_dir=_path("wiki_dir", "wiki"),
        state_dir=_path("state_dir", ".wiki_state"),
        llm=llm,
        **data,
    )
