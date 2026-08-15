"""Alliance Auth hooks for AA CorpScore."""

from django.utils.translation import gettext_lazy as _

from allianceauth import hooks
from allianceauth.services.hooks import MenuItemHook, UrlHook

from aa_corpscore import urls


class CorpScoreMenuItem(MenuItemHook):
    """Your score card."""

    def __init__(self):
        MenuItemHook.__init__(
            self,
            _("My CorpScore"),
            "fas fa-credit-card fa-fw",
            "aa_corpscore:scorecard",
            navactive=["aa_corpscore:"],
            order=1100,
        )

    def render(self, request):
        if request.user.has_perm("aa_corpscore.basic_access"):
            return MenuItemHook.render(self, request)
        return ""


class LeaderboardMenuItem(MenuItemHook):
    """Corp leaderboard."""

    def __init__(self):
        MenuItemHook.__init__(
            self,
            _("Corp Leaderboard"),
            "fas fa-trophy fa-fw",
            "aa_corpscore:leaderboard",
            navactive=["aa_corpscore:"],
            order=1101,
        )

    def render(self, request):
        if request.user.has_perm("aa_corpscore.view_leaderboard"):
            return MenuItemHook.render(self, request)
        return ""


class StatementMenuItem(MenuItemHook):
    """Monthly statement meme."""

    def __init__(self):
        MenuItemHook.__init__(
            self,
            _("My Statement"),
            "fas fa-file-invoice-dollar fa-fw",
            "aa_corpscore:statement",
            navactive=["aa_corpscore:"],
            order=1102,
        )

    def render(self, request):
        if request.user.has_perm("aa_corpscore.basic_access"):
            return MenuItemHook.render(self, request)
        return ""


class WhatIfMenuItem(MenuItemHook):
    """Score simulator."""

    def __init__(self):
        MenuItemHook.__init__(
            self,
            _("Score Simulator"),
            "fas fa-sliders-h fa-fw",
            "aa_corpscore:whatif",
            navactive=["aa_corpscore:"],
            order=1103,
        )

    def render(self, request):
        if request.user.has_perm("aa_corpscore.basic_access"):
            return MenuItemHook.render(self, request)
        return ""


@hooks.register("menu_item_hook")
def register_scorecard_menu():
    return CorpScoreMenuItem()


@hooks.register("menu_item_hook")
def register_leaderboard_menu():
    return LeaderboardMenuItem()


@hooks.register("menu_item_hook")
def register_statement_menu():
    return StatementMenuItem()


@hooks.register("menu_item_hook")
def register_whatif_menu():
    return WhatIfMenuItem()


@hooks.register("url_hook")
def register_urls():
    return UrlHook(urls, "aa_corpscore", r"^corpscore/")
