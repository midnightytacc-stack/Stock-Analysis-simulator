"""
NSE company search for the Portfolio page: a cached, pre-processed stock universe and
ranked suggestions. Pure pandas/RapidFuzz (no Streamlit, no network), so it is unit-testable
and cheap enough to run on every keystroke.

Data
----
`data/nse_symbols.csv` is read once per process (re-read automatically if the file changes).
Headers are normalised first because the real file has leading spaces (" SERIES",
" DATE OF LISTING"). Rows with a blank/malformed symbol or name are skipped. Nothing here
raises: a missing or unreadable file yields an empty universe carrying a readable `error`.

Series: EQ (regular equity) and BE (trade-for-trade equity) are preferred; other series
(e.g. BZ) stay searchable but rank after them. Nothing is excluded outright, so a new series
code in a future file doesn't silently hide companies.

Ranking (best tier first; every company appears once, at its best tier)
-----------------------------------------------------------------------
1 exact ticker   2 exact company name   3 ticker prefix   4 company-name prefix
5 partial (every typed word starts a word of the name, or a substring match)
6 similar spelling (RapidFuzz, only when tiers 1-5 leave room)
Inside a tier: names that the app's existing ALIASES map points at come first, then series
(EQ < BE < others), then alphabetical.
"""
from __future__ import annotations

import functools
import re
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
from rapidfuzz import fuzz, process

try:  # reuse the app's existing symbol knowledge; search must still work if helpers can't import
    from utils.helpers import ALIASES, CSV_PATH
except Exception:  # pragma: no cover - exercised only when helpers itself is broken
    ALIASES = {}
    CSV_PATH = Path(__file__).resolve().parent.parent / "data" / "nse_symbols.csv"

EXCHANGE_SUFFIX = ".NS"
DEFAULT_LIMIT = 8
MAX_QUERY_LENGTH = 60

EXACT_TICKER, EXACT_NAME, TICKER_PREFIX, NAME_PREFIX, PARTIAL, SIMILAR = 1, 2, 3, 4, 5, 6
TIER_LABELS = {
    EXACT_TICKER: "Exact ticker", EXACT_NAME: "Exact name", TICKER_PREFIX: "Ticker prefix",
    NAME_PREFIX: "Name prefix", PARTIAL: "Partial match", SIMILAR: "Similar spelling",
}

_SERIES_RANK = {"EQ": 0, "BE": 1}
_SYMBOL_RE = re.compile(r"[A-Z0-9&\-]{1,20}")
_PUNCT_RE = re.compile(r"[^a-z0-9 ]+")
_CORPORATE_SUFFIXES = {"limited", "ltd", "pvt", "private", "company", "co", "corporation", "corp", "inc"}
_FUZZY_MIN_LENGTH = 4
_FUZZY_CUTOFF = 84


# ---------------------------------------------------------------------------
# Text normalisation (word-based: unlike helpers.clean_text it never edits inside words)
# ---------------------------------------------------------------------------
def normalise(text: object) -> str:
    """Lower-case, '&' -> 'and', punctuation -> space, single spaces."""
    t = str(text).lower().replace("&", " and ")
    return " ".join(_PUNCT_RE.sub(" ", t).split())


def core_name(normalised: str) -> str:
    """Drop trailing corporate words: 'tata power company limited' -> 'tata power'."""
    words = normalised.split()
    while len(words) > 1 and words[-1] in _CORPORATE_SUFFIXES:
        words.pop()
    return " ".join(words)


def _compact(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Company:
    symbol: str   # "INFY"
    name: str     # "Infosys Limited"
    series: str   # "EQ"

    @property
    def ticker(self) -> str:
        return f"{self.symbol}{EXCHANGE_SUFFIX}"

    @property
    def label(self) -> str:
        return f"{self.name} — {self.symbol}"


@dataclass(frozen=True)
class _Row:
    company: Company
    sym_l: str
    sym_compact: str
    name_norm: str
    name_core: str
    name_compact: str
    words: tuple[str, ...]
    aliases: frozenset[str]
    series_rank: int


@dataclass(frozen=True)
class Universe:
    rows: tuple[_Row, ...] = ()
    error: str | None = None
    skipped_rows: int = 0
    stale_aliases: tuple[str, ...] = ()   # ALIASES entries whose symbol is not in the file
    by_symbol: dict = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.rows)

    @property
    def ok(self) -> bool:
        return bool(self.rows)

    def get(self, ticker_or_symbol: object) -> Company | None:
        """Validate a symbol/ticker ('INFY', 'infy.ns') against the loaded universe."""
        sym = str(ticker_or_symbol or "").strip().upper()
        if sym.endswith(EXCHANGE_SUFFIX):
            sym = sym[: -len(EXCHANGE_SUFFIX)]
        return self.by_symbol.get(sym)


@dataclass(frozen=True)
class Match:
    company: Company
    tier: int

    @property
    def reason(self) -> str:
        return TIER_LABELS[self.tier]


@dataclass(frozen=True)
class SearchResult:
    query: str
    matches: tuple[Match, ...] = ()
    total: int = 0                 # matches found before the display limit was applied
    message: str | None = None     # guidance for an empty query / no result / unusable data

    @property
    def companies(self) -> list[Company]:
        return [m.company for m in self.matches]


# ---------------------------------------------------------------------------
# Loading (cached; never raises)
# ---------------------------------------------------------------------------
def _empty(error: str) -> Universe:
    return Universe(error=error)


@functools.lru_cache(maxsize=4)
def _load_cached(path: str, mtime_ns: int, size: int) -> Universe:  # noqa: ARG001 (keys the cache)
    try:
        df = pd.read_csv(path, dtype=str, keep_default_na=False, encoding_errors="replace")
    except Exception as exc:
        return _empty(f"The company list could not be read ({type(exc).__name__}).")

    df.columns = [str(c).strip().upper() for c in df.columns]
    missing = [c for c in ("SYMBOL", "NAME OF COMPANY") if c not in df.columns]
    if missing:
        return _empty("The company list is missing required column(s): " + ", ".join(missing) + ".")
    series_values = df["SERIES"] if "SERIES" in df.columns else ["EQ"] * len(df)

    best: dict[str, tuple[int, Company]] = {}
    skipped = 0
    for symbol, name, series in zip(df["SYMBOL"], df["NAME OF COMPANY"], series_values):
        symbol = str(symbol).strip().upper()
        name = " ".join(str(name).split())
        series = str(series).strip().upper() or "EQ"
        if not name or not _SYMBOL_RE.fullmatch(symbol):
            skipped += 1
            continue
        rank = _SERIES_RANK.get(series, 2)
        if symbol not in best or rank < best[symbol][0]:      # duplicate symbol: keep the better series
            best[symbol] = (rank, Company(symbol, name, series))

    alias_keys: dict[str, set[str]] = {}
    stale: list[str] = []
    for alias, ticker in ALIASES.items():
        symbol = str(ticker).upper().removesuffix(EXCHANGE_SUFFIX)
        if symbol in best:
            alias_keys.setdefault(symbol, set()).add(normalise(alias))
        else:
            stale.append(alias)

    rows = []
    for symbol, (rank, company) in best.items():
        name_norm = normalise(company.name)
        rows.append(_Row(
            company=company, sym_l=symbol.lower(), sym_compact=_compact(symbol.lower()),
            name_norm=name_norm, name_core=core_name(name_norm),
            name_compact=_compact(core_name(name_norm)), words=tuple(name_norm.split()),
            aliases=frozenset(alias_keys.get(symbol, ())), series_rank=rank,
        ))
    if not rows:
        return _empty("The company list contains no usable rows.")
    return Universe(rows=tuple(rows), skipped_rows=skipped, stale_aliases=tuple(stale),
                    by_symbol={r.company.symbol: r.company for r in rows})


def load_universe(path: str | Path | None = None) -> Universe:
    """The preprocessed company universe. Cached per process; reloads if the file changes."""
    target = Path(path) if path is not None else Path(CSV_PATH)
    try:
        stat = target.stat()
    except OSError:
        return _empty(f"The company list ({target.name}) was not found.")
    return _load_cached(str(target), stat.st_mtime_ns, stat.st_size)


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------
def _words_start_distinct(tokens: list[str], words: tuple[str, ...]) -> bool:
    """Each typed token must be the start of its own (different) word of the name."""
    free = list(words)
    for token in tokens:
        hit = next((i for i, w in enumerate(free) if w.startswith(token)), None)
        if hit is None:
            return False
        free.pop(hit)
    return bool(tokens)


def _tier(row: _Row, q_sym: str, q_compact: str, q_name: str, q_core: str) -> int | None:
    if q_sym == row.sym_l or (q_compact and q_compact == row.sym_compact):
        return EXACT_TICKER
    if q_name in (row.name_norm, row.name_core) or q_core in (row.name_norm, row.name_core) \
            or q_name in row.aliases or q_core in row.aliases:
        return EXACT_NAME
    if row.sym_l.startswith(q_sym) or (q_compact and row.sym_compact.startswith(q_compact)):
        return TICKER_PREFIX
    if q_name and (row.name_norm.startswith(q_name) or (q_core and row.name_core.startswith(q_core))
                   or any(a.startswith(q_name) for a in row.aliases)):
        return NAME_PREFIX
    if len(q_name) >= 2 and _words_start_distinct(q_name.split(), row.words):
        return PARTIAL
    if (len(q_name) >= 3 and q_name in row.name_norm) or (len(q_sym) >= 3 and q_sym in row.sym_l):
        return PARTIAL
    return None


def _similar(q_core: str, pool: list[_Row], limit: int) -> list[tuple[_Row, float]]:
    """Typo-tolerant candidates: per-word for one typed word, whole-name for several."""
    if " " in q_core:
        hits = process.extract(q_core, [r.name_core for r in pool], scorer=fuzz.WRatio,
                               score_cutoff=_FUZZY_CUTOFF, limit=limit)
        return [(pool[idx], score) for _name, score, idx in hits]
    best: dict[int, float] = {}
    for idx, row in enumerate(pool):
        # a word of the name ('relaince' ~ 'reliance') or the name run together ('tatasteal' ~ 'tata steel')
        candidates = [w for w in row.words if len(w) >= _FUZZY_MIN_LENGTH - 1] + [row.name_compact]
        score = max(fuzz.ratio(q_core, c) for c in candidates) if candidates else 0
        if score >= _FUZZY_CUTOFF:
            best[idx] = score
    top = sorted(best.items(), key=lambda kv: (-kv[1], pool[kv[0]].name_norm))[:limit]
    return [(pool[idx], score) for idx, score in top]


def search(query: object, universe: Universe | None = None, limit: int = DEFAULT_LIMIT) -> SearchResult:
    """Ranked company suggestions for what the user has typed so far."""
    universe = universe if universe is not None else load_universe()
    raw = " ".join(str(query or "").split())[:MAX_QUERY_LENGTH]
    if not universe.ok:
        return SearchResult(raw, message=(universe.error or "The company list is unavailable.")
                            + " Company search is disabled until it is fixed.")
    if not raw:
        return SearchResult(raw, message="Type a company name or ticker symbol, e.g. “Infosys” or “INFY”.")

    q_sym = re.sub(r"\.(ns|bo)$", "", raw.lower())
    q_compact = _compact(q_sym)
    q_name = normalise(raw)
    q_core = core_name(q_name)
    if not q_compact:   # punctuation only
        return SearchResult(raw, message=f"No NSE company matches “{raw}”. Try a company name or ticker symbol.")

    found: dict[str, tuple[tuple, Match]] = {}
    for row in universe.rows:
        tier = _tier(row, q_sym, q_compact, q_name, q_core)
        if tier is None:
            continue
        via_alias = 0 if (q_name in row.aliases or any(a.startswith(q_name) for a in row.aliases)) else 1
        key = (tier, via_alias, row.series_rank, row.name_norm, row.company.symbol)
        found[row.company.symbol] = (key, Match(row.company, tier))

    if len(found) < limit and len(q_name) >= _FUZZY_MIN_LENGTH:     # typo tolerance, only if there's room
        pool = [r for r in universe.rows if r.company.symbol not in found]
        for row, score in _similar(q_core, pool, limit):
            key = (SIMILAR, -score, row.series_rank, row.name_norm, row.company.symbol)
            found[row.company.symbol] = (key, Match(row.company, SIMILAR))

    ranked = [m for _, m in sorted(found.values(), key=lambda kv: kv[0])]
    if not ranked:
        return SearchResult(raw, message=(
            f"No NSE company matches “{raw}”. Check the spelling, or try the ticker symbol."))
    return SearchResult(raw, matches=tuple(ranked[:limit]), total=len(ranked))
