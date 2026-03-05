from __future__ import annotations

import re

_PREFIXES = [
    r"^sold:\s*",
    r"^order\s*#?\s*",
    r"^vinted\s+order\s*",
    r"^etsy\s+order\s*",
    r"^ebay\s+item\s+sold\s*",
]
_NOISE_TOKENS = {"re:", "fwd:", "[external]"}


class QueryNormalizer:
    def normalize(self, subject: str) -> str:
        value = subject.strip().lower()
        for pat in _PREFIXES:
            value = re.sub(pat, "", value, flags=re.IGNORECASE).strip()
        words = [w for w in value.split() if w not in _NOISE_TOKENS]
        value = " ".join(words)
        value = re.sub(r"\s+", " ", value).strip()
        return value
