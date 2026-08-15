"""App configuration for AA CorpScore."""

from django.apps import AppConfig

from aa_corpscore import __version__


class AaCorpScoreConfig(AppConfig):
    """App config."""

    name = "aa_corpscore"
    label = "aa_corpscore"
    verbose_name = f"AA CorpScore v{__version__}"

    def ready(self):
        # Register AA menu items and URL hooks. Guarded so the app stays importable
        # in test environments without allianceauth installed.
        try:
            import aa_corpscore.auth_hooks  # noqa: F401
        except ImportError:
            pass

        # Register Celery beat schedule for nightly score recompute.
        try:
            from celery.schedules import crontab
            from django.conf import settings

            beat_schedule = getattr(settings, "CELERYBEAT_SCHEDULE", None)
            if beat_schedule is None:
                beat_schedule = {}
                settings.CELERYBEAT_SCHEDULE = beat_schedule

            beat_schedule.setdefault(
                "aa_corpscore_recompute_scores",
                {
                    "task": "aa_corpscore.tasks.recompute_all_scores",
                    "schedule": crontab(minute=0, hour=2),
                },
            )
        except Exception:
            pass
