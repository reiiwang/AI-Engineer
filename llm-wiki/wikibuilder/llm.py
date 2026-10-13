"""OpenAI-compatible chat client with WeKnora's call semantics
(generateWithTemplateResult in wiki_ingest.go):

- bounded exponential-backoff retries for transient errors only
- system/user split for the page-modify prompt, business instructions
  appended for every other prompt
- page rewrites cut off at the token limit are resumed with the
  continuation prompt, and refused if still truncated
- markdown image URLs are masked to opaque tokens so the model cannot
  mangle them"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import prompts
from .config import LLMConfig
from .template import render

log = logging.getLogger(__name__)

MAX_CONTINUATIONS = 3
CONTINUATION_DONE = "(complete)"
_IMAGE_RE = re.compile(r"(!\[[^\]]*\]\()([^)\s]+)(\))")


class LLMError(RuntimeError):
    pass


def append_instructions(prompt: str, instructions: str, label: str) -> str:
    """types.AppendCustomPromptInstructions."""
    instructions = (instructions or "").strip()
    if not instructions:
        return prompt
    label = label or "custom"
    return (
        f"{prompt.strip()}\n\n<{label}_business_instructions>\n{instructions}\n"
        f"</{label}_business_instructions>\n"
        "Apply these business instructions only when they do not conflict with the "
        "system-owned output format, citation, safety, or factuality rules."
    )


def _mask_images(data: Dict[str, str]) -> Tuple[Dict[str, str], Dict[str, str]]:
    url_to_tok: Dict[str, str] = {}

    def sub(m: "re.Match[str]") -> str:
        url = m.group(2)
        if url not in url_to_tok:
            url_to_tok[url] = f"IMG_{len(url_to_tok) + 1:04d}"
        return m.group(1) + url_to_tok[url] + m.group(3)

    masked = {k: _IMAGE_RE.sub(sub, v) if isinstance(v, str) else v for k, v in data.items()}
    return masked, {tok: url for url, tok in url_to_tok.items()}


def _unmask_images(text: str, tok_to_url: Dict[str, str]) -> str:
    for tok, url in tok_to_url.items():
        text = text.replace(tok, url)
    return text


def clean_llm_json(s: str) -> str:
    """cleanLLMJSON + sanitizeJSONString: strip code fences and escape raw
    control characters inside JSON string literals."""
    s = s.strip()
    for prefix in ("```json", "```"):
        if s.startswith(prefix):
            s = s[len(prefix):]
            break
    if s.endswith("```"):
        s = s[:-3]
    s = s.strip()
    out = []
    in_str = escape = False
    for ch in s:
        if escape:
            out.append({"\n": "n", "\r": "r", "\t": "t"}.get(ch, ch))
            escape = False
            continue
        if ch == "\\":
            escape = True
        elif ch == '"':
            in_str = not in_str
        elif in_str and ch in "\n\r\t":
            out.append({"\n": "\\n", "\r": "\\r", "\t": "\\t"}[ch])
            continue
        out.append(ch)
    return "".join(out)


def parse_llm_json(raw: str) -> Any:
    s = clean_llm_json(raw)
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        # Tolerate a stray preamble/epilogue around the JSON object.
        start, end = s.find("{"), s.rfind("}")
        if start >= 0 and end > start:
            return json.loads(s[start:end + 1])
        raise


def split_summary_line(raw: str) -> Tuple[str, str]:
    """splitSummaryLine: returns (summary, body) from 'SUMMARY: ...' output."""
    raw = raw.strip()
    for prefix in ("SUMMARY:", "SUMMARY："):
        if raw.startswith(prefix):
            first, _, rest = raw.partition("\n")
            return first[len(prefix):].strip(), rest.strip()
    return "", raw


class LLM:
    def __init__(self, cfg: LLMConfig, log_path: Optional[Path] = None):
        from openai import OpenAI  # imported lazily so --dry-run works without it

        self.cfg = cfg
        self.client = OpenAI(base_url=cfg.base_url, api_key=cfg.resolve_api_key(),
                             timeout=cfg.timeout, max_retries=0)
        self.sem = threading.Semaphore(cfg.max_concurrency)
        self.log_path = log_path
        self._log_lock = threading.Lock()
        self.calls = 0

    # --- transport -----------------------------------------------------

    def _is_transient(self, err: Exception) -> bool:
        import openai

        # A 429 for an exhausted quota/balance will not recover by retrying.
        code = str(getattr(err, "code", "") or "")
        if code in ("insufficient_quota", "credit_balance_exhausted"):
            return False
        if isinstance(err, (openai.APITimeoutError, openai.APIConnectionError,
                            openai.RateLimitError, openai.InternalServerError)):
            return True
        status = getattr(err, "status_code", None)
        return status in (408, 409, 429) or (status is not None and status >= 500)

    def chat(self, messages: List[Dict[str, str]], purpose: str = "") -> Tuple[str, str]:
        last: Optional[Exception] = None
        for attempt in range(1, self.cfg.max_attempts + 1):
            params: Dict[str, Any] = {self.cfg.token_param: self.cfg.max_tokens}
            if self.cfg.temperature is not None:
                params["temperature"] = self.cfg.temperature
            try:
                with self.sem:
                    t0 = time.time()
                    resp = self.client.chat.completions.create(
                        model=self.cfg.model,
                        messages=messages,
                        extra_body=self.cfg.extra_body or None,
                        **params,
                    )
                choice = resp.choices[0]
                content = choice.message.content or ""
                finish = choice.finish_reason or ""
                self.calls += 1
                self._log(purpose, messages, content, finish, time.time() - t0)
                return content, finish
            except Exception as err:  # noqa: BLE001 - classified below
                last = err
                if not self._is_transient(err) or attempt == self.cfg.max_attempts:
                    break
                backoff = 2 ** attempt
                log.warning("LLM call failed (attempt %d/%d), retrying in %ds: %s",
                            attempt, self.cfg.max_attempts, backoff, err)
                time.sleep(backoff)
        raise LLMError(f"LLM call failed ({purpose}): {last}") from last

    def _log(self, purpose: str, messages: List[Dict[str, str]], content: str,
             finish: str, elapsed: float) -> None:
        if not self.log_path:
            return
        rec = {"purpose": purpose, "elapsed_s": round(elapsed, 2), "finish_reason": finish,
               "messages": messages, "response": content}
        with self._log_lock:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.log_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    # --- templated generation -----------------------------------------

    def generate(self, template: str, data: Dict[str, str], purpose: str,
                 instructions: str = "", scope: str = "") -> str:
        masked, tok_to_url = _mask_images(data)
        prompt = render(template, masked)
        is_page_modify = template is prompts.WIKI_PAGE_MODIFY_USER_PROMPT
        if is_page_modify:
            messages = [
                {"role": "system", "content": append_instructions(
                    prompts.WIKI_PAGE_MODIFY_SYSTEM_PROMPT, instructions, scope)},
                {"role": "user", "content": prompt},
            ]
        else:
            messages = [{"role": "user", "content": append_instructions(prompt, instructions, scope)}]

        parts: List[str] = []
        finish = ""
        for round_ in range(MAX_CONTINUATIONS + 1):
            content, finish = self.chat(messages, purpose)
            if round_ > 0 and content.strip().lower() == CONTINUATION_DONE:
                finish = "stop"
                break
            parts.append(content)
            if not is_page_modify or finish != "length" or round_ == MAX_CONTINUATIONS:
                break
            log.warning("%s hit the completion budget; requesting continuation %d/%d",
                        purpose, round_ + 1, MAX_CONTINUATIONS)
            messages = messages + [
                {"role": "assistant", "content": content},
                {"role": "user", "content": prompts.WIKI_PAGE_MODIFY_CONTINUATION_PROMPT},
            ]
        if is_page_modify and finish == "length":
            raise LLMError(f"{purpose}: page rewrite still truncated after {MAX_CONTINUATIONS} continuations")
        return _unmask_images("".join(parts), tok_to_url)

    def generate_json(self, template: str, data: Dict[str, str], purpose: str,
                      instructions: str = "", scope: str = "") -> Any:
        raw = self.generate(template, data, purpose, instructions, scope)
        try:
            return parse_llm_json(raw)
        except (json.JSONDecodeError, ValueError) as err:
            raise LLMError(f"{purpose}: could not parse JSON: {err}\nRaw: {raw[:500]}") from err
