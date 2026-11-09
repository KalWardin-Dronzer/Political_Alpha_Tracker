"""
Did listed companies' share prices react when their electoral bond purchases became known?

Three events. Day 0 is the first trading session that could react to each:

- verdict, 15 February 2024: the Supreme Court struck the scheme down and
  ordered SBI to disclose the bond data. The judgment was reported during
  trading (LiveLaw, 11:04 IST).
- names, 15 March 2024: the Election Commission published the buyers' names
  on the evening of 14 March, after the close.
- parties, 22 March 2024: it published the bond numbers that link each buyer to
  the party that encashed the bond, on the evening of 21 March.

DESIGN
------
Every buyer shares the same event dates, so their returns move together and a
cross-sectional t-test would overstate significance. The test therefore uses one
portfolio (Brown & Warner, 1980; Kolari & Pynnonen, 2010 discuss the problem):

1. Each connected company with complete prices is paired with a non-connected
   company from the same sector (from the whole universe when it has no sector
   label) whose average daily traded value over the estimation window is
   closest, each control used once.
2. D_t is the equal-weighted daily return of the buyers minus that of their
   controls, which removes the market and sector moves they share.
3. The estimation window is trading days -250 to -11 before the first event.
   The abnormal return is AR_t = D_t - mean(D); a window of L days has
   CAR = sum(AR) and standard error sd(D) * sqrt(L), sd(D) from the
   estimation window.
4. Each estimate carries its minimum detectable effect, 2.80 standard errors
   (5% two-sided, 80% power).

A market-adjusted version, buyers against all non-connected companies with
complete prices, is reported as a check on the matching.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import stats

from src.data.companies import company_key

MDE_Z = 1.96 + 0.8416


@dataclass(frozen=True)
class Event:
    key: str
    day0: str
    label: str


EVENTS = (
    Event("verdict", "2024-02-15", "Supreme Court strikes the scheme down"),
    Event("names", "2024-03-15", "buyers' names published"),
    Event("parties", "2024-03-22", "bond numbers link buyers to parties"),
)
ESTIMATION = (-250, -11)      # trading days relative to the first event
WINDOWS = {"[-5,-1]": (-5, -1), "[0,+1]": (0, 1), "[0,+5]": (0, 5)}
PRIMARY_EVENT, PRIMARY_WINDOW = "names", "[0,+1]"


def _positions(index: pd.DatetimeIndex) -> dict[str, int]:
    pos = {}
    for e in EVENTS:
        day = pd.Timestamp(e.day0)
        if day not in index:
            raise ValueError(f"{e.day0} ({e.key}) is not a trading day in the price panel")
        pos[e.key] = index.get_loc(day)
    return pos


class EventStudy:
    """
        study = EventStudy(close, volume, companies, connected)
        result = study.run()

    `close` and `volume` are the price panel (dates x NSE symbols), `companies`
    the universe and `connected` the set of connected company keys.
    """

    def __init__(self, close: pd.DataFrame, volume: pd.DataFrame, companies: pd.DataFrame, connected: set[str]):
        self.close = close.sort_index()
        self.close.index = pd.to_datetime(self.close.index)
        self.volume = volume.reindex(index=self.close.index, columns=self.close.columns)
        keyed = companies.assign(key=companies.apply(company_key, axis=1))
        keyed = keyed[keyed["nse_symbol"].isin(self.close.columns)]
        self.sector = dict(zip(keyed["nse_symbol"], keyed["sector"]))
        self.buyers = sorted(set(keyed.loc[keyed["key"].isin(connected), "nse_symbol"]))
        self.others = sorted(set(keyed.loc[~keyed["key"].isin(connected), "nse_symbol"]))
        self.pos = _positions(self.close.index)
        first, last = min(self.pos.values()), max(self.pos.values())
        self.start = first + ESTIMATION[0]
        self.end = last + max(w[1] for w in WINDOWS.values())
        self.est = slice(first + ESTIMATION[0], first + ESTIMATION[1] + 1)

    def eligible(self) -> list[str]:
        """Symbols with a return on every day from the estimation window to the last event window."""
        rets = self.close.pct_change(fill_method=None).iloc[self.start:self.end + 1]
        return list(rets.columns[rets.notna().all()])

    def adv(self) -> pd.Series:
        """Average daily traded value over the estimation window, Rs crore."""
        value = (self.close * self.volume).iloc[self.est]
        return value.mean() / 1e7

    def match(self) -> list[tuple[str, str]]:
        """(buyer, control) pairs: same sector, closest log traded value, each control used once."""
        ok = set(self.eligible())
        adv = self.adv()
        pool = [s for s in self.others if s in ok and adv.get(s, 0) > 0]
        pairs = []
        for buyer in sorted((b for b in self.buyers if b in ok and adv.get(b, 0) > 0), key=lambda b: -adv[b]):
            sector = self.sector.get(buyer, "")
            candidates = [s for s in pool if self.sector.get(s, "") == sector] if sector else pool
            if not candidates:
                continue
            control = min(candidates, key=lambda s: (abs(np.log(adv[s]) - np.log(adv[buyer])), s))
            pool.remove(control)
            pairs.append((buyer, control))
        return pairs

    def run(self, market_adjusted: bool = False) -> dict:
        rets = self.close.pct_change(fill_method=None)
        if market_adjusted:
            ok = set(self.eligible())
            buyers = [b for b in self.buyers if b in ok]
            controls = [s for s in self.others if s in ok]
            n_pairs = len(buyers)
        else:
            pairs = self.match()
            buyers, controls = [b for b, _ in pairs], [c for _, c in pairs]
            n_pairs = len(pairs)
        diff = rets[buyers].mean(axis=1) - rets[controls].mean(axis=1)
        est = diff.iloc[self.est]
        mu, sigma, df = float(est.mean()), float(est.std(ddof=1)), len(est) - 1
        abnormal = diff - mu

        rows = []
        for e in EVENTS:
            for name, (a, b) in WINDOWS.items():
                window = abnormal.iloc[self.pos[e.key] + a: self.pos[e.key] + b + 1]
                car, se = float(window.sum()), sigma * np.sqrt(len(window))
                t = car / se
                rows.append({"event": e.key, "window": name, "car": car, "se": se, "t": t,
                             "p": float(2 * stats.t.sf(abs(t), df)), "mde": MDE_Z * se,
                             "lo": car - stats.t.ppf(0.975, df) * se, "hi": car + stats.t.ppf(0.975, df) * se})
        return {"n_buyers": len(buyers), "n_controls": len(controls), "n_pairs": n_pairs,
                "sigma": sigma, "mu": mu, "estimation_days": len(est),
                "results": pd.DataFrame(rows), "abnormal": abnormal}

    def drift(self, event: str = PRIMARY_EVENT, before: int = 10, last_week: int = 5) -> dict:
        """What the matched portfolio did before an event: a description, not a test.

        - how many pairs have a buyer that traded more than its control over the
          estimation window;
        - the cumulative abnormal return from day -`before` to day -1, and the
          days on which it lies outside the 95% band drawn in the README figure;
        - that cumulative abnormal return for the pairs whose buyer traded more
          and for the rest, each against its own estimation-window mean;
        - over days -`last_week` to -1, the average return of the most traded
          tenth and of the least traded half of all stocks with complete prices.
        """
        rets = self.close.pct_change(fill_method=None)
        adv = self.adv()
        pairs = self.match()
        at = self.pos[event]

        def abnormal(group):
            diff = rets[[b for b, _ in group]].mean(axis=1) - rets[[c for _, c in group]].mean(axis=1)
            est = diff.iloc[self.est]
            return diff - est.mean(), float(est.std(ddof=1)), len(est) - 1

        whole, sigma, df = abnormal(pairs)
        days = list(range(-before, 0))
        path = pd.Series(whole.iloc[at - before: at].cumsum().to_numpy(), index=days)
        band = stats.t.ppf(0.975, df) * sigma * np.sqrt(np.arange(1, before + 1))
        peak_day = int(path.abs().idxmax())

        larger = [(b, c) for b, c in pairs if adv[b] > adv[c]]
        rest = [(b, c) for b, c in pairs if adv[b] <= adv[c]]

        def car(group):
            return float(abnormal(group)[0].iloc[at - before: at].sum()) if group else float("nan")

        traded = adv.reindex(self.eligible()).dropna()
        traded = traded[traded > 0]
        rank = traded.rank(method="first", ascending=False)
        week = (1 + rets.iloc[at - last_week: at][traded.index]).prod() - 1
        return {"event": event, "before": before, "last_week": last_week,
                "n_pairs": len(pairs), "n_larger": len(larger), "n_rest": len(rest),
                "path": path, "band": band,
                "outside": [d for d, p, b in zip(days, path, band) if abs(p) > b],
                "peak_day": peak_day, "peak": float(path[peak_day]),
                "car_larger": car(larger), "car_rest": car(rest),
                "n_market": len(traded),
                "top_tenth": float(week[rank <= len(traded) / 10].mean()),
                "bottom_half": float(week[rank > len(traded) / 2].mean())}
