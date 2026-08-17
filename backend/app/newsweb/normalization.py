from __future__ import annotations

import re


def normalize_weekly_body(text: str) -> str:
    """Normalize documented Otello wording/decimal variants before strict parsing.

    This does not change financial values. It only maps issuer wording variants onto the
    strict parser's canonical phrases and converts decimal comma in average prices.
    """
    clean = " ".join(text.split())
    replacements = (
        (
            "announcing a share buyback program",
            "announcing the initiation of the share buyback program",
        ),
        (
            "announcing the continuation of the share buyback program",
            "announcing the initiation of the share buyback program",
        ),
        (
            "Since the initiation of this continuation of the share buyback program",
            "Since the initiation of this share buyback program",
        ),
        (
            "Since the initiation of this continuation of the buyback program",
            "Since the initiation of this share buyback program",
        ),
        (
            "Since the initiation of the share buyback program",
            "Since the initiation of this share buyback program",
        ),
        (
            "maximum number of shares that can be purchased under this continuation of the buyback program is",
            "maximum number of shares that can be purchased under this buyback program is",
        ),
        (
            "maximum number of shares that can be purchased is",
            "maximum number of shares that can be purchased under this buyback program is",
        ),
    )
    for old, new in replacements:
        clean = clean.replace(old, new)

    clean = re.sub(
        r"(average price of NOK\s+)(\d+),(\d{1,4})(?=\s)",
        lambda match: f"{match.group(1)}{match.group(2)}.{match.group(3)}",
        clean,
        flags=re.I,
    )
    return clean
