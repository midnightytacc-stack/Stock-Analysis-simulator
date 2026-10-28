from tools.stock_tool import (
    get_company_info,
    get_market_data,
    get_financial_ratios
)

from tools.technical_tool import (
    get_technical_indicators
)

from tools.news_tool import (
    get_company_news
)

def collect_company_data(ticker: str) -> dict:
    company_info = get_company_info(ticker)

    company_name = company_info.get("company_name", ticker)

    return {
        "ticker": ticker,
        "company_info": company_info,
        "market_data": get_market_data(ticker),
        "financial_ratios": get_financial_ratios(ticker),
        "technical_indicators": get_technical_indicators(ticker),
        "news": get_company_news(company_name)
    }

def compare_companies(
    ticker_1: str,
    ticker_2: str
):
    
    return {
        "company_1": collect_company_data(ticker_1),
        "company_2": collect_company_data(ticker_2)
    }