"""Values that remember where they came from.

Every source (crm.json today, extracted documents later) produces a list of
FieldValue candidates. Several sources may offer a value for the same field;
resolve() keeps them all and picks one, so the choice is explainable later.
"""
from collections import defaultdict
from dataclasses import asdict, dataclass
from typing import Optional


@dataclass(frozen=True)
class FieldValue:
    key: str        # schema key, e.g. "ein"
    value: object   # the value (normalized once validated)
    source: str     # e.g. "crm.json"; later "articles_of_organization.pdf"
    locator: str    # where inside the source, e.g. "tax.ein"; later "page 2"
    raw: object = None  # the value exactly as found, before normalization
    confidence: Optional[float] = None  # LLM-extracted values only
    method: str = ""    # lookup (structured data) | regex | llm


# Within one source, how a value was obtained decides between candidates:
# a regex match reads digits exactly; an LLM re-types them.
METHOD_RANK = {"lookup": 0, "regex": 1, "llm": 2}


def resolve(candidates, source_priority=None):
    """Pick one FieldValue per key.

    candidates: FieldValues from all sources. source_priority: source names,
    most trusted first; by default, sources rank in the order they first
    appear in candidates. Ties within a source go by METHOD_RANK.
    Returns ({key: chosen}, {key: [all candidates]}).
    """
    by_key = defaultdict(list)
    for fv in candidates:
        by_key[fv.key].append(fv)

    order = list(source_priority or dict.fromkeys(fv.source for fv in candidates))
    rank = {source: i for i, source in enumerate(order)}

    chosen = {
        key: min(options, key=lambda fv: (rank.get(fv.source, len(rank)),
                                          METHOD_RANK.get(fv.method, len(METHOD_RANK))))
        for key, options in by_key.items()
    }
    return chosen, dict(by_key)


def to_report(accepted, issues):
    """JSON-friendly provenance record for one filled form."""
    return {
        "fields": {key: asdict(fv) for key, fv in accepted.items()},
        "issues": [asdict(i) for i in issues],
    }
