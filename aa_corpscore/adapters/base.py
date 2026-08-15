"""Base adapter interface.

An adapter collects raw inputs for one score component and normalises them to
a 0-100 component score. The scoring service blends component scores into the
final 300-850 score.

Subclasses must implement:
- `available()` -> bool: True if the source plugin/data is installed and queryable.
- `collect(user, settings) -> ComponentResult`: gather raw data and compute the
  normalised score for this user.

`ComponentResult` is a small dataclass returned by `collect`.
"""

from dataclasses import dataclass, field


@dataclass
class ComponentResult:
    component: str
    raw_value: float = 0.0
    raw_unit: str = ""
    normalised: float = 0.0  # 0-100
    note: str = ""
    # Optional sub-events that explain the score (used for the meme statement).
    events: list = field(default_factory=list)


class BaseAdapter:
    """Base class for all score-component adapters."""

    #: Component key, must match a key in adapters.ADAPTERS and models.DEFAULT_WEIGHTS.
    component = "base"

    def available(self) -> bool:
        """Return True if the source plugin is installed and queryable."""
        raise NotImplementedError

    def collect(self, user, settings) -> ComponentResult:
        """Gather raw data for `user` and return a ComponentResult."""
        raise NotImplementedError
