"""Minimal renderer for the subset of Go text/template used by prompts.py:
{{.Var}} substitution and non-nested {{if .Var}}...{{end}} blocks."""
from __future__ import annotations

import re
from typing import Mapping

_IF_RE = re.compile(r"\{\{if \.(\w+)\}\}(.*?)\{\{end\}\}", re.S)
_VAR_RE = re.compile(r"\{\{\.(\w+)\}\}")


def render(template: str, data: Mapping[str, str]) -> str:
    out = _IF_RE.sub(lambda m: m.group(2) if data.get(m.group(1)) else "", template)
    return _VAR_RE.sub(lambda m: str(data.get(m.group(1), "")), out)
