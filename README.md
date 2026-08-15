# AA CorpScore

A credit score for corp members. Alliance Auth 5.x plugin that computes a
FICO-style **300-850 score** per member from their fleet participation,
activity, audit compliance, Discord engagement, and SRP history. Full Credit
Karma meme: score cards, monthly statements, hard inquiries, score simulator,
tier badges, and achievements.

## Why

It's a meme. But also a genuinely useful engagement dashboard: leadership sees
at a glance who's active and who's drifting, members get a fun feedback loop
for showing up to fleets, and the "hard inquiry" gag keeps leadership honest
about snooping on individual breakdowns.

## Score model

**300-850 scale**, blended from weighted components (defaults, all editable in
admin):

| Component | Default weight | Source |
|-----------|---------------|--------|
| Alliance FATs | 30% | [AA-FatImporter](https://github.com/evecarboot/AA-FatImporter) import data |
| Corp FATs | 25% | [AFAT](https://github.com/allianceauth/afat) live fleet data |
| Activity / tenure | 15% | Django auth last-login + date-joined |
| CorpTools audit | 10% | [CorpTools](https://github.com/pvyParts/allianceauth-corp-tools) / MembersAudit freshness |
| Discord | 10% | aa-discordbot + CorpScore activity_tracker cog (see below) |
| SRP discipline | 10% | allianceauth-srp request history |
| PvP (zKillboard) | 0% (off) | [zKillboard](https://zkillboard.com) Statistics API - kills, losses, ISK efficiency |
| Member Status | 0% (off) | [aa-memberstatus](https://github.com/evecarboot/aa-memberstatus) inactivity/LOA status |
| Industry Pool | 0% (off) | [aa-industrypool](https://github.com/evecarboot/aa-industrypool) completed industry jobs |

The PvP component is **off by default**. Enable it in admin (CorpScore settings
-> zKillboard PvP integration) and set `weight_pvp` above 0 for it to affect
scores. When enabled, the adapter queries the zKillboard Statistics API per
character (cached for 24h) and blends two sub-metrics:

- **Activity** (70% of the PvP sub-score): kills + losses within the decay
  window. Shows the member is actually PvPing. Soft cap at 50 engagements.
- **Efficiency** (30%): ISK destroyed / (ISK destroyed + ISK lost). The meme
  "credit utilisation" factor - losing more ISK than you kill is like maxing
  out your credit card.

### Discord activity tracking

aa-discordbot doesn't natively track message counts, voice time, or last-seen
timestamps. CorpScore ships a lightweight cog that does. To enable it, add the
cog to your aa-discordbot config in `local.py`:

```python
DISCORD_BOT_COGS = [
    ...default cogs...,
    "aa_corpscore.cogs.activity_tracker",
]
```

The cog listens to `on_message` and `on_voice_state_update` events and writes
daily per-user activity rows (message count, voice minutes, last seen) to the
`DiscordActivityDaily` table. Message counts are buffered in memory and flushed
to the DB every 5 minutes to avoid a write per message. The discord adapter
then reads from this table to compute the score.

If the cog is not installed, the discord adapter falls back to a neutral
baseline (40/100) for users who have Discord linked but no activity data, and
0/100 for users who haven't linked Discord at all. So the component won't
break scores if the cog isn't enabled - it just won't have real data.

The adapter blends three sub-metrics:
- **Messages** (50%): total messages in the decay window, soft cap at 500.
- **Voice** (30%): total voice minutes in the window, soft cap at 300.
- **Recency** (20%): days since last seen, full marks within 1 day, decays
  to 0 over the decay window.

Each adapter normalises its raw input to 0-100. The service blends by weight,
maps to 300-850, applies the hard-inquiry penalty, and persists a snapshot.

### Member Status integration (optional)

If [aa-memberstatus](https://github.com/evecarboot/aa-memberstatus) is installed,
CorpScore can use the member's inactivity status as a score component:

- **Active** (no inactivity pings): 90/100
- **On leave of absence** (approved LOA): 60/100 (no penalty for planned breaks)
- **Inactivity warning**: 45/100
- **Marked inactive**: 20/100

Off by default. Set `weight_memberstatus` > 0 in admin to enable.

### Industry Pool integration (optional)

If [aa-industrypool](https://github.com/evecarboot/aa-industrypool) is installed,
CorpScore can count completed/delivered industry jobs as a score component.
Members who contribute to corp manufacturing, reactions, invention, and research
get a score boost. Soft cap: 10 completed jobs in the decay window = 100/100.

Off by default. Set `weight_industrypool` > 0 in admin to enable.

### Reactive score updates

CorpScore listens to signals from external plugins and triggers an async score
recompute via Celery when data changes, instead of waiting for the nightly beat:

- **AA-FatImporter**: new import -> recompute all affected users
- **AFAT**: new FAT recorded -> recompute that user
- **CorpTools**: character audit refresh -> recompute that user
- **MemberStatus**: inactivity ping -> recompute that user
- **IndustryPool**: job delivered/completed -> recompute the builder

If Celery isn't running, the nightly beat catches up. Signals are guarded so
missing plugins don't cause errors.

### Discord slash commands (optional)

CorpScore ships a slash command cog for aa-discordbot. Install it by adding to
your `local.py`:

```python
DISCORD_BOT_COGS = [
    ...default cogs...,
    "aa_corpscore.cogs.corpscore_commands",
]
```

Available slash commands:

| Command | Description | Permission |
|---------|-------------|------------|
| `/corpscore me` | Check your own CorpScore (ephemeral) | `basic_access` |
| `/corpscore member <user>` | Hard-pull another member's score | `view_breakdown` |
| `/corpscore board` | Top 10 leaderboard | `view_leaderboard` |

The `/corpscore member` command logs a hard inquiry on the target's report
(meme accuracy: checking someone else's credit score is a hard pull).

### REST API for external integrations

CorpScore exposes a REST endpoint for integrations that query score data via
HTTP instead of Python imports:

```
GET /aa-corpscore/api/shipfinance/<user_id>/?base_rate=10&base_insurance=5
```

Returns JSON with the member's adjusted finance terms (same data as the
`get_finance_terms()` Python function). Requires the `api_access` permission
or superuser. Intended for server-to-server calls (e.g. aa-shipfinance making
an internal HTTP request).

### Tiers

| Score | Tier |
|-------|------|
| 300-579 | Subprime Capsuleer |
| 580-669 | Fair Weather Pilot |
| 670-739 | Prime Member |
| 740-799 | Elite Capsuleer |
| 800-850 | Black Card / Concord-Verified |

Cutoffs are configurable in admin.

## Features

**Member-facing**
- **Score card** - big number, tier badge, score history sparkline, "factors
  affecting your score" bars, achievements, hard-inquiry log.
- **Monthly statement** - meme itemised list of score deltas ("+15 pts from 3
  alliance fleets", "-8 pts from missed corp FAT minimum"). Filterable by
  30/90/365 days.
- **Score simulator** - drag sliders on each component to see a projected
  score. Soft pull, doesn't affect the real score.

**Leadership-facing**
- **Corp leaderboard** - ranked members with tier badges + score distribution
  histogram.
- **Member breakdown** - a "hard pull" on another member's full component
  breakdown. Logged on their report and (optionally) penalises their score.
  Requires the `view_breakdown` permission.
- **Admin dashboard** - settings summary, available/missing adapters, manual
  recompute trigger.

**Automation**
- Nightly Celery beat recompute (02:00) of every member's score.
- Optional group gating: auto-add elite members to an "Elite" group, subprime
  members to a "needs fleets" group.
- Hard-inquiry penalty: each leadership breakdown view in the last 30 days
  subtracts N points (capped). Meme-accurate.

**Achievements** (auto-awarded)
- On Time Every Time, Strategic Operator, Loyal Customer, Audit-Ready, Vocal
  Customer, Black Card Holder, Hard Inquiry Victim.

**ShipFinance integration** (optional, off by default)
- When [aa-shipfinance](https://github.com/evecarboot/aa-shipfinance) is
  installed and the integration is enabled, a member's CorpScore tier affects
  their ship financing terms - just like real-life credit scores affecting
  loan terms.
- Subprime members pay higher interest rates and insurance premiums.
- Black Card members get discounts on both.
- Members below a configurable minimum score can be denied finance or rentals
  entirely.
- Admin configures per-tier interest rate adjustments, insurance premium
  adjustments, and minimum score thresholds in Django admin.

## Requirements

- Python 3.10+
- Alliance Auth 5.2+ (below 6)
- Optional but recommended: AA-FatImporter, AFAT, CorpTools/MembersAudit,
  aa-discordbot, allianceauth-sRP. Missing plugins are detected at runtime and
  their components are skipped (weight treated as zero).

## Installation

```bash
pip install git+https://github.com/<your-user>/aa-corpscore.git
```

Add to your Alliance Auth `local.py`:

```python
INSTALLED_APPS += [
    "aa_corpscore",
]

# Optional: additional permissions setup is automatic via the General meta model.
```

Run migrations and collect static:

```bash
python manage.py migrate
python manage.py collectstatic --noinput
```

Restart Alliance Auth so menu hooks and the Celery beat schedule register.

## Configuration

Open Django admin -> **CorpScore settings** (singleton row named `main`):

- **Component weights** - must sum to 100. Set a weight to 0 to disable a
  component.
- **Decay windows** - days over which each component's activity counts full
  before decaying.
- **Tier cutoffs** - lower bound (inclusive) for each tier band.
- **Group gating** - enable and pick elite/subprime groups.
- **Hard inquiries** - enable logging, set per-pull penalty, window, and cap.
- **ShipFinance integration** - enable, set minimum score thresholds for
  finance/rentals, and per-tier interest rate and insurance premium
  adjustments.

## ShipFinance integration

When [aa-shipfinance](https://github.com/evecarboot/aa-shipfinance) is
installed alongside CorpScore, the member's CorpScore tier affects their ship
financing terms. Credit score affects finance, just like IRL.

### Admin configuration

In Django admin -> CorpScore settings -> ShipFinance integration section:

- `shipfinance_enabled` - master on/off switch (default off).
- `shipfinance_min_score_finance` - minimum score to finance ships (0 = no min).
- `shipfinance_min_score_rent` - minimum score to rent ships (0 = no min).
- Per-tier interest rate adjustments (percentage points added to base rate):
  - Subprime: +5% (default), Fair: +2%, Prime: 0%, Elite: -1.5%, Black Card: -3%
- Per-tier insurance premium adjustments (percentage points added to base):
  - Subprime: +3% (default), Fair: +1%, Prime: 0%, Elite: -0.5%, Black Card: -1%

### Public API for ShipFinance

CorpScore exposes a public API in `aa_corpscore.shipfinance` that ShipFinance
calls. All functions degrade gracefully if the integration is disabled or no
score exists - they return base rates and eligible=True, so ShipFinance works
standalone without CorpScore.

```python
from aa_corpscore.shipfinance import (
    shipfinance_available,
    can_finance,
    can_rent,
    get_finance_terms,
    get_rate_adjustment,
    get_insurance_adjustment,
)

# Check if integration is on
if shipfinance_available():
    # Check eligibility before showing finance offers
    eligible, reason = can_finance(user)
    if not eligible:
        messages.error(request, reason)
        return redirect(...)

    # Get adjusted terms for the offer display
    terms = get_finance_terms(
        user,
        base_interest_rate=offer.interest_rate,      # from ShipFinance config
        base_insurance_premium=offer.insurance_rate,  # from ShipFinance config
    )
    # terms.adjusted_interest_rate    -> Decimal, use this instead of base
    # terms.adjusted_insurance_premium -> Decimal, use this instead of base
    # terms.rate_adjustment           -> Decimal, show "CorpScore discount: -3%"
    # terms.tier_label                -> str, show "Black Card / Concord-Verified"

# For rentals:
allowed, reason = can_rent(user)
```

The `FinanceTerms` dataclass returned by `get_finance_terms`:

| Field | Type | Description |
|-------|------|-------------|
| `eligible` | bool | Whether the member can finance |
| `ineligible_reason` | str | Why not (empty if eligible) |
| `score` | int | The member's current CorpScore |
| `tier` | str | Tier key (subprime, fair, prime, elite, blackcard) |
| `tier_label` | str | Human-readable tier name |
| `base_interest_rate` | Decimal | The rate ShipFinance passed in |
| `adjusted_interest_rate` | Decimal | Base + tier adjustment, clamped to 0 |
| `rate_adjustment` | Decimal | The delta (positive = premium, negative = discount) |
| `base_insurance_premium` | Decimal | The premium ShipFinance passed in |
| `adjusted_insurance_premium` | Decimal | Base + tier adjustment, clamped to 0 |
| `insurance_adjustment` | Decimal | The delta |

### ShipFinance side

On the ShipFinance side, you'll need to call CorpScore's API when creating or
displaying finance offers. The integration point is wherever ShipFinance
calculates the interest rate and insurance premium for a member - call
`get_finance_terms()` there and use the adjusted rates.

## Routes

| Page | Route | Permission |
|------|-------|------------|
| My CorpScore | `/corpscore/` | `basic_access` |
| Corp Leaderboard | `/corpscore/leaderboard/` | `view_leaderboard` |
| My Statement | `/corpscore/statement/` | `basic_access` |
| Score Simulator | `/corpscore/what-if/` | `basic_access` |
| Admin Dashboard | `/corpscore/admin/` | `manage_settings` |
| Member Breakdown | `/corpscore/member/<id>/` | `view_breakdown` |
| Score History API | `/corpscore/api/history/` | `basic_access` |

## How scoring works

1. The Celery beat task (or a manual trigger from admin) calls
   `recompute_all_users()`.
2. For each user, `compute_score_for_user()` runs every available adapter.
3. Each adapter returns a `ComponentResult` with a raw value, a 0-100
   normalised score, and a human note.
4. The service blends by weight, maps 0-100 -> 300-850, subtracts the
   hard-inquiry penalty, and writes a `ScoreSnapshot` + per-component
   `ScoreComponentSnapshot` rows.
5. Achievements are evaluated and awarded. Group gating is applied.

Snapshots are append-only - the history graph and sparkline read the trailing
set. Never updated in place.

## Adapters

Each component is backed by an adapter in `aa_corpscore/adapters/`. Adapters
detect their source plugin at runtime via `available()`. If the plugin isn't
installed, the adapter is skipped. To add a new component:

1. Subclass `BaseAdapter`, set `component`, implement `available()` and
   `collect(user, settings) -> ComponentResult`.
2. Register it in `adapters/__init__.py` `ADAPTERS`.
3. Add a weight field to `ScoreSettings` and a key to `DEFAULT_WEIGHTS`.

## Development

```bash
pip install -e ".[test]"
python -m pytest
```

Tests run against a minimal Django settings module (`tests/django_settings.py`)
that doesn't require Alliance Auth to be fully configured - they exercise the
pure scoring logic (tier resolution, score mapping, what-if blending).

## License

MIT. See `pyproject.toml`.
