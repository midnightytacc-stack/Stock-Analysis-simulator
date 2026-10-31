"""
Adding a *selected* company to the portfolio. A thin, Streamlit-free layer over the existing
`tools.portfolio_tool` API (load_portfolio / add_stock); it does no storage of its own and
takes the API object as a parameter so it can be tested without touching real files.
"""
from __future__ import annotations

from dataclasses import dataclass

from utils.stock_search import Universe


@dataclass(frozen=True)
class AddOutcome:
    level: str      # "success" | "warning" | "error"  (matches st.success / st.warning / st.error)
    message: str
    added: bool = False


def holding_tickers(api) -> set[str]:
    """Upper-cased tickers currently saved in the portfolio."""
    return {str(h.get("ticker", "")).strip().upper() for h in api.load_portfolio() if isinstance(h, dict)}


def add_selected(symbol: str | None, universe: Universe, api) -> AddOutcome:
    """
    Validate the user's explicit selection, refuse duplicates, then save via `api.add_stock`.
    Nothing is written unless every check passes, and the write is verified afterwards.
    """
    symbol = str(symbol).strip() if symbol else ""
    if not symbol:
        return AddOutcome("warning", "Search for a company and pick one of the suggestions before adding it.")
    if not universe.ok:
        return AddOutcome("error", f"{universe.error or 'The company list is unavailable.'} Nothing was added.")
    company = universe.get(symbol)
    if company is None:
        return AddOutcome("error", f"“{symbol}” isn't in the NSE company list, so it wasn't added.")

    try:
        if company.ticker in holding_tickers(api):
            return AddOutcome(
                "warning", f"{company.name} ({company.symbol}) is already in your portfolio — nothing was changed.")
        api.add_stock(company.ticker, company.name)
        saved = company.ticker in holding_tickers(api)
    except Exception as exc:  # unreadable/unwritable portfolio file etc.
        return AddOutcome("error", f"Couldn't update your portfolio ({type(exc).__name__}). Nothing was added.")

    if not saved:
        return AddOutcome("error", "The portfolio didn't save. Please try again.")
    return AddOutcome("success", f"Added {company.name} ({company.symbol}) to your portfolio.", added=True)
