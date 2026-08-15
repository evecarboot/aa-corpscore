"""Data-source adapters for CorpScore.

Each adapter pulls raw inputs for one score component from a specific plugin
(AA-FatImporter, AFAT, CorpTools, Discord, etc.). Adapters are detected at
runtime: if the source plugin isn't installed, the adapter reports `available()`
as False and the scoring service skips it (treating its weight as zero).
"""

from aa_corpscore.adapters.activity import ActivityAdapter
from aa_corpscore.adapters.alliance_fat import AllianceFatAdapter
from aa_corpscore.adapters.corp_fat import CorpFatAdapter
from aa_corpscore.adapters.corptools import CorpToolsAdapter
from aa_corpscore.adapters.discord import DiscordAdapter
from aa_corpscore.adapters.industrypool import IndustryPoolAdapter
from aa_corpscore.adapters.memberstatus import MemberStatusAdapter
from aa_corpscore.adapters.pvp import PvpAdapter
from aa_corpscore.adapters.srp import SrpAdapter

# Ordered registry. Order only matters for deterministic event logging.
ADAPTERS = {
    "alliance_fat": AllianceFatAdapter,
    "corp_fat": CorpFatAdapter,
    "activity": ActivityAdapter,
    "corptools": CorpToolsAdapter,
    "discord": DiscordAdapter,
    "srp": SrpAdapter,
    "pvp": PvpAdapter,
    "memberstatus": MemberStatusAdapter,
    "industrypool": IndustryPoolAdapter,
}


def get_adapter(component):
    """Return an adapter instance for a component key, or None if unknown."""
    cls = ADAPTERS.get(component)
    return cls() if cls else None


def available_components():
    """Return the list of component keys whose adapters report available()."""
    out = []
    for key, cls in ADAPTERS.items():
        adapter = cls()
        try:
            if adapter.available():
                out.append(key)
        except Exception:
            continue
    return out
