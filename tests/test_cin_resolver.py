"""
Tests for the name-to-CIN resolver.

The property under test is REFUSAL. A wrong CIN is far worse than a missing
one: it silently attaches another company's directors to the political graph
and manufactures a connection that does not exist, which is exactly the kind of
fake signal this project has already been burned by. So most of these tests
check that the resolver declines rather than guesses.

Search is mocked throughout — the suite must not depend on Zaubacorp.
"""

import pytest

from src.data.cin_resolver import CinResolver, CinMatch, normalize, CIN_RE


class StubResolver(CinResolver):
    """CinResolver with the network replaced by a canned result table."""

    def __init__(self, results: dict, **kw):
        super().__init__(delay=0.0, **kw)
        self.results = results
        self.queries = []

    def _search(self, name, timeout=25):
        self.queries.append(name)
        return self.results.get(name, [])


class TestNormalize:
    def test_strips_corporate_boilerplate(self):
        assert normalize("Britannia Industries Limited") == "britannia"
        assert normalize("Alkem Laboratories Ltd") == "alkem laboratories"

    def test_equates_ltd_and_limited(self):
        assert normalize("Jindal Saw Ltd") == normalize("Jindal Saw Limited")

    def test_handles_empty(self):
        assert normalize("") == ""
        assert normalize(None) == ""


class TestQueryVariants:
    def test_deletes_apostrophes_rather_than_spacing_them(self):
        """
        Measured: "Divi s Laboratories" returns 0 records on Zaubacorp while
        "Divis Laboratories" returns the right company. An apostrophe must
        vanish, not become a space.
        """
        v = CinResolver.query_variants("Divi's Laboratories Limited")
        assert any("Divis" in x for x in v)
        assert not any("Divi s" in x for x in v)

    def test_offers_a_variant_without_the_limited_suffix(self):
        """"Britannia Industries Limited" -> 0 records; "Britannia Industries" -> 1."""
        v = CinResolver.query_variants("Britannia Industries Limited")
        assert "Britannia Industries" in v

    def test_variants_run_from_specific_to_loose(self):
        v = CinResolver.query_variants("Hero MotoCorp Limited")
        assert v[0] == "Hero MotoCorp Limited"
        assert len(v[-1]) <= len(v[0])

    def test_no_duplicate_variants(self):
        v = CinResolver.query_variants("Alkem Laboratories")
        assert len(v) == len(set(x.lower() for x in v))

    def test_very_short_fragments_are_not_emitted(self):
        assert all(len(x) >= 3 for x in CinResolver.query_variants("AB Ltd"))


class TestRefusal:
    def test_returns_none_when_only_unlisted_companies_match(self):
        """
        The real AUROPHARMA case: Zaubacorp returned only
        'AUROBINDO PAHRMA PRIVATE LIMITED' (a typo'd private company). Guessing
        it would have attached the wrong directors.
        """
        r = StubResolver({"Aurobindo Pharma Limited": [
            ("U99999PY1986PTC000469", "AUROBINDO PAHRMA PRIVATE LIMITED")]})
        m = r.resolve("Aurobindo Pharma Limited")
        assert not m.resolved
        assert "listed" in m.reason.lower()

    def test_one_letter_acronym_difference_is_refused(self):
        """
        The GTLINFRA case, and the most dangerous one in this module.

        "gtl infrastructure" vs "gsl infrastructure" scores 94 on token_sort_ratio
        — ABOVE any threshold that still admits a genuine match like
        "divis laboratories" at 93. So a score threshold alone cannot separate
        them, and GTL Infrastructure and GSL Infrastructure are unrelated
        companies. Only the first-token guard catches this.

        In the live measurement this case was rejected purely because Zaubacorp
        happened to return U-prefix companies that the listed filter removed.
        Had any been L-prefix, the resolver would have attached GSL's directors
        to GTL and invented a political connection.
        """
        r = StubResolver({"GTL Infrastructure Limited": [
            ("L45209GJ2008PLC052891", "GSL INFRASTRUCTURE LIMITED"),
            ("L32204WB1993PLC060443", "ETL INFRASTRUCTURE FINANCE LIMITED"),
        ]})
        m = r.resolve("GTL Infrastructure Limited")
        assert not m.resolved, "accepted a one-letter-different acronym"
        assert "leading word" in m.reason

    def test_score_threshold_still_refuses_a_same_head_mismatch(self):
        """The threshold remains the second line of defence when heads agree."""
        r = StubResolver({"Jagsonpal Pharmaceuticals Limited": [
            ("L24239DL1978PLC009181", "JAGSONPAL FINANCE AND LEASING LIMITED"),
        ]})
        m = r.resolve("Jagsonpal Pharmaceuticals Limited")
        assert not m.resolved
        assert "threshold" in m.reason

    def test_apostrophe_name_still_matches_after_the_head_guard(self):
        """
        The guard must not break Divi's: normalize deletes the apostrophe so the
        leading token is "divis", matching the registered name.
        """
        r = StubResolver({"Divis Laboratories": [
            ("L24110TG1990PLC011854", "DIVIS LABORATORIES LIMITED")]})
        m = r.resolve("Divi's Laboratories Limited")
        assert m.resolved, f"apostrophe handling regressed: {m.reason}"
        assert m.cin == "L24110TG1990PLC011854"

    def test_returns_none_on_no_results_at_all(self):
        m = StubResolver({}).resolve("Nonexistent Trading Co Limited")
        assert not m.resolved
        assert "no search results" in m.reason

    def test_empty_name_is_refused_without_searching(self):
        r = StubResolver({})
        assert not r.resolve("").resolved
        assert r.queries == []


class TestResolution:
    def test_exact_match_resolves(self):
        r = StubResolver({"Alkem Laboratories Limited": [
            ("L00305MH1973PLC174201", "ALKEM LABORATORIES LIMITED")]})
        m = r.resolve("Alkem Laboratories Limited")
        assert m.cin == "L00305MH1973PLC174201"
        assert m.score >= 88
        assert CIN_RE.match(m.cin)

    def test_prefers_the_listed_company_over_a_private_namesake(self):
        r = StubResolver({"Acme Steel Limited": [
            ("U27100MH2001PTC123456", "ACME STEEL PRIVATE LIMITED"),
            ("L27100MH1995PLC098765", "ACME STEEL LIMITED"),
        ]})
        m = r.resolve("Acme Steel Limited")
        assert m.cin.startswith("L")
        assert m.cin == "L27100MH1995PLC098765"

    def test_falls_through_to_a_looser_variant_when_the_exact_query_is_empty(self):
        """Mirrors Britannia: the full name finds nothing, the shorter one works."""
        r = StubResolver({
            "Britannia Industries": [("L15412WB1918PLC002964", "BRITANNIA INDUSTRIES LIMITED")],
        })
        m = r.resolve("Britannia Industries Limited")
        assert m.resolved
        assert m.cin == "L15412WB1918PLC002964"
        # It must have tried the full name first.
        assert r.queries[0] == "Britannia Industries Limited"

    def test_html_escaped_candidate_names_are_unescaped(self):
        """
        Zaubacorp returns "DIVI&#39;S LABORATORIES LIMITED". Unescaped, that
        normalizes to "divi 39 s laboratories" whose leading token is "divi",
        and the first-token guard rejects a correct match. This caught a live
        regression.
        """
        r = StubResolver({"Divis Laboratories Limited": [
            ("L24110TG1990PLC011854", "DIVI&#39;S LABORATORIES LIMITED")]})
        m = r.resolve("Divi's Laboratories Limited")
        assert m.resolved, f"HTML entity broke the match: {m.reason}"
        assert m.cin == "L24110TG1990PLC011854"

    def test_listed_only_can_be_disabled(self):
        r = StubResolver({"Some Private Firm Limited": [
            ("U27100MH2001PTC123456", "SOME PRIVATE FIRM LIMITED")]}, listed_only=False)
        m = r.resolve("Some Private Firm Limited")
        assert m.resolved and m.cin.startswith("U")

    def test_batch_returns_one_result_per_input(self):
        r = StubResolver({"A Limited": [("L11111MH2000PLC000001", "A LIMITED")]})
        out = r.resolve_batch(["A Limited", "Unknown Co Limited"])
        assert len(out) == 2
        assert out[0].resolved and not out[1].resolved
