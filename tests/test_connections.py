"""
Tests for attributing electoral bonds to listed companies.

A false match invents a political connection; a missed one hides a real donor
among the controls. Both directions are tested, along with the aggregation
rule: an earlier version kept only the last bond seen per company, so a
company whose last bond was small looked unconnected however much it bought.
"""

import pandas as pd
from rapidfuzz import fuzz

from src.config import MATCH_THRESHOLD, MIN_BOND
from src.connections import connections, match_names, normalize

CRORE, LAKH = 10_000_000, 100_000


def companies(*rows):
    """A company table in the shape of data/companies.csv: (scrip, name, cin, sector)."""
    return pd.DataFrame([{"scrip_code": s, "nse_symbol": s, "name": n, "isin": "",
                          "cin": c, "sector": sec, "industry": ""} for s, n, c, sec in rows])


def bonds(*rows):
    """Bond purchases: (purchaser, amount, date)."""
    frame = pd.DataFrame(rows, columns=["purchaser", "amount", "date"])
    frame["date"] = pd.to_datetime(frame["date"])
    frame["year"] = frame["date"].dt.year
    return frame


UNIVERSE = companies(
    ("500001", "GTL Infrastructure Limited", "L00001MH1987PLC000001", "Telecommunication"),
    ("500002", "ABC Industries Limited", "L00002MH1990PLC000002", "Industrials"),
    ("500003", "JK Cement Limited", "L00003UP1994PLC000003", "Commodities"),
    ("500004", "Torrent Pharma", "L24230GJ1972PLC002126", "Healthcare"),
    ("500005", "Lupin Limited", "L24100MH1983PLC029442", "Healthcare"),
    ("500006", "Noname Traders Limited", "", ""),
)


class TestNameMatching:
    def test_leading_word_rule_rejects_lookalike_that_clears_the_score(self):
        """GSL and GTL Infrastructure are different companies that score above the threshold."""
        assert fuzz.token_sort_ratio(normalize("GSL INFRASTRUCTURE LIMITED"),
                                     normalize("GTL Infrastructure Limited")) >= MATCH_THRESHOLD
        matches, rejected = match_names(["GSL INFRASTRUCTURE LIMITED"], UNIVERSE)
        assert matches == {}
        assert rejected and rejected[0][0] == "GSL INFRASTRUCTURE LIMITED"

    def test_boilerplate_is_ignored(self):
        matches, _ = match_names(["ABC INDUSTRIES LTD"], UNIVERSE)
        assert matches == {"ABC INDUSTRIES LTD": "L00002MH1990PLC000002"}

    def test_spaced_initials_are_joined(self):
        """'J K CEMENT' failed the leading-word rule ('j' vs 'jk') before initials were joined."""
        assert normalize("J K CEMENT LTD.") == normalize("JK Cement Limited")
        matches, _ = match_names(["J K CEMENT LTD."], UNIVERSE)
        assert matches == {"J K CEMENT LTD.": "L00003UP1994PLC000003"}

    def test_weak_match_is_refused(self):
        matches, rejected = match_names(["VEDANTA RESOURCES"], companies(
            ("1", "Vedanta Limited", "L13209MH1965PLC291394", "")))
        assert matches == {} and rejected == []

    def test_company_without_cin_is_keyed_by_scrip_code(self):
        matches, _ = match_names(["NONAME TRADERS LTD"], UNIVERSE)
        assert matches == {"NONAME TRADERS LTD": "500006"}


class TestConnections:
    def test_every_bond_counts_not_just_the_last(self):
        """Regression: the last bond here is Rs 1 lakh, but the company bought a Rs 1 crore one."""
        table = connections(
            bonds(("ABC INDUSTRIES LTD", CRORE, "2019-04-12"),
                  ("ABC INDUSTRIES LTD", LAKH, "2023-10-04")),
            UNIVERSE, {})
        row = table.loc["L00002MH1990PLC000002"]
        assert row["bonds"] == 2 and row["total"] == CRORE + LAKH
        assert row["largest"] == CRORE and bool(row["connected"])

    def test_small_buyer_is_not_connected(self):
        table = connections(bonds(("ABC INDUSTRIES LTD", LAKH, "2021-01-05")), UNIVERSE, {})
        assert LAKH < MIN_BOND
        assert not bool(table.loc["L00002MH1990PLC000002", "connected"])

    def test_donor_cin_attributes_names_the_strict_match_misses(self):
        name = "TORRENT PHARMACEUTICALS LIMITED"
        assert match_names([name], UNIVERSE)[0] == {}
        table = connections(bonds((name, CRORE, "2022-07-01")), UNIVERSE,
                            {name: "L24230GJ1972PLC002126"})
        assert bool(table.loc["L24230GJ1972PLC002126", "connected"])

    def test_donor_cin_for_an_unlisted_company_is_ignored(self):
        table = connections(bonds(("SOME PRIVATE LTD", CRORE, "2022-07-01")), UNIVERSE,
                            {"SOME PRIVATE LTD": "U99999MH2000PTC999999"})
        assert table.empty

    def test_bond_found_by_both_routes_counts_once(self):
        table = connections(bonds(("LUPIN LIMITED", CRORE, "2023-01-09")), UNIVERSE,
                            {"LUPIN LIMITED": "L24100MH1983PLC029442"})
        assert table.loc["L24100MH1983PLC029442", "bonds"] == 1
        assert table.loc["L24100MH1983PLC029442", "total"] == CRORE

    def test_share_classes_under_one_cin_are_one_company(self):
        universe = companies(("1", "Tata Motors Limited", "L28920MH1945PLC004520", "Auto"),
                             ("2", "Tata Motors Limited DVR", "L28920MH1945PLC004520", "Auto"))
        table = connections(bonds(("TATA MOTORS LIMITED", CRORE, "2020-01-02")), universe, {})
        assert list(table.index) == ["L28920MH1945PLC004520"]

    def test_unmatched_purchasers_are_left_out(self):
        table = connections(bonds(("SOMEONE ELSE ENTIRELY", CRORE, "2020-01-02")), UNIVERSE, {})
        assert table.empty


class TestMatchingFixes:
    def test_a_period_between_letters_is_a_space(self):
        """'DR.REDDY'S' became the single token 'drreddys' and failed the leading-word rule."""
        universe = companies(("500124", "Dr. Reddy's Laboratories Limited", "", "Healthcare"))
        assert normalize("DR.REDDY'S LABORATORIES LTD") == normalize("Dr. Reddy's Laboratories Limited")
        matches, _ = match_names(["DR.REDDY'S LABORATORIES LTD", "J.K.CEMENT LTD."], universe)
        assert matches == {"DR.REDDY'S LABORATORIES LTD": "500124"}

    def test_a_name_two_listed_companies_share_is_refused(self):
        """'DCM Shriram' and 'DCM Shriram Industries' both normalise to 'dcm shriram'; the
        old matcher silently gave the bonds to whichever came last."""
        universe = companies(("1", "DCM Shriram Limited", "L1", "Commodities"),
                             ("2", "DCM Shriram Industries Limited", "L2", "Commodities"))
        matches, rejected = match_names(["DCM SHRIRAM LIMITED"], universe)
        assert matches == {} and rejected[0][0] == "DCM SHRIRAM LIMITED"


def audit(*rows):
    """Audit decisions: (purchaser, decision, nse_symbol)."""
    return pd.DataFrame([(p, d, s, "", "") for p, d, s in rows],
                        columns=["purchaser", "decision", "nse_symbol", "relation", "source"])


class TestAudit:
    def test_same_company_is_attributed_at_both_levels(self):
        trail = audit(("ABC INDS FORMERLY XYZ", "same_company", "500002"))
        for level in ("entity", "group"):
            table = connections(bonds(("ABC INDS FORMERLY XYZ", CRORE, "2021-01-05")), UNIVERSE, {}, trail, level)
            assert bool(table.loc["L00002MH1990PLC000002", "connected"])

    def test_a_subsidiary_counts_at_group_level_only(self):
        trail = audit(("LUPIN SUBSIDIARY PVT LTD", "subsidiary", "500005"))
        purchases = bonds(("LUPIN SUBSIDIARY PVT LTD", CRORE, "2021-01-05"))
        assert connections(purchases, UNIVERSE, {}, trail, "entity").empty
        group = connections(purchases, UNIVERSE, {}, trail, "group")
        assert group.loc["L24100MH1983PLC029442", "via_subsidiary"] == CRORE

    def test_not_attributed_overrides_a_name_match(self):
        """The audit can veto a strict match that names the wrong company."""
        purchases = bonds(("ABC INDUSTRIES LTD", CRORE, "2021-01-05"))
        assert not connections(purchases, UNIVERSE, {}, audit(), "group").empty
        trail = audit(("ABC INDUSTRIES LTD", "not_attributed", ""))
        assert connections(purchases, UNIVERSE, {}, trail, "group").empty
