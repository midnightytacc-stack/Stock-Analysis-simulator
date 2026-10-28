from google import genai
from google.genai import types

from config import GEMINI_API_KEY

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

from tools.portfolio_tool import (
    add_stock,
    remove_stock,
    view_portfolio,
    analyze_portfolio,
    clear_portfolio
)

from tools.comparison_tool import (
    compare_companies
)

from utils.helpers import (
    get_ticker,
    get_multiple_tickers
)

from utils.memory_manager import (
    get_recent_history,
    save_conversation,
    get_last_company
)

client = genai.Client(api_key=GEMINI_API_KEY)

SYSTEM_PROMPT = """
You are an AI Financial Research Assistant specializing in stock analysis.

You are provided with:

1. User query
2. Company information
3. Current market data
4. Financial ratios
5. Technical indicators
6. Latest company news
7. Previous conversation history

Instructions:

• Use ONLY the provided information.
• Never invent facts.
• Never provide guaranteed investment advice.
• If news is unrelated to the company, clearly state that.

Formatting Rules:

Start every response with:

==================================================
📈 STOCK ANALYSIS REPORT
==================================================

Then use these headings exactly:

🏢 Company Overview

📊 Market Performance

💰 Financial Analysis

📈 Technical Analysis

📰 Recent News

✅ Overall Summary

For market data, explain what the numbers indicate instead of simply repeating them.

For financial ratios, explain whether each metric appears strong, weak or neutral.

For technical indicators:
- Explain SMA trend.
- Explain RSI.
- Explain MACD.
- Explain Bollinger Bands.

Finish with a short summary (4-6 lines) explaining:

• Positive factors
• Risks
• Overall outlook

Keep the response concise, readable and professional.
"""

COMPARISON_PROMPT = """
You are a professional Financial Research Analyst.

Compare the two companies using ONLY the supplied information.

Never invent data.

Use this exact structure:

==================================================
📊 STOCK COMPARISON REPORT
==================================================

🏢 Company Overview

📈 Market Performance Comparison

💰 Financial Ratio Comparison

📊 Technical Indicator Comparison

📰 News Comparison

✅ Strengths of Company 1

✅ Strengths of Company 2

⚠ Risks

🏁 Final Verdict

Do not recommend buying or selling.

Instead explain which company currently appears stronger based on the provided data.
"""

FOLLOW_UP_WORDS = [
    "it",
    "its",
    "this stock",
    "that stock",
    "this company",
    "that company",
    "buy it",
    "sell it",
    "hold it"
]


def is_follow_up_query(user_query: str) -> bool:
    """
    Detect whether the user is referring to the
    previously discussed company.
    """
    query = user_query.lower()

    return any(word in query for word in FOLLOW_UP_WORDS)


def resolve_company(user_query: str):
    """
    If no company is found and the query looks like
    a follow-up question, use the previous company
    from conversation history.
    """
    ticker = get_ticker(user_query)

    if ticker:

        info = get_company_info(ticker)

        return {
            "ticker": ticker,
            "company": info.get("company_name", ticker)
        }

    if is_follow_up_query(user_query):

        previous = get_last_company()

        if previous:

            return previous

    return None


def collect_stock_data(company: dict):

    ticker = company["ticker"]

    company_info = get_company_info(ticker)

    market_data = get_market_data(ticker)

    financial_ratios = get_financial_ratios(ticker)

    technical_indicators = get_technical_indicators(ticker)

    company_name = company_info.get("company_name", ticker)

    news = get_company_news(company_name)

    return {
        "ticker": ticker,
        "company": company_name,
        "company_info": company_info,
        "market_data": market_data,
        "financial_ratios": financial_ratios,
        "technical_indicators": technical_indicators,
        "news": news
    }


def build_prompt(
    user_query: str,
    history: list,
    stock_data: dict
):
    return f"""
User Question

{user_query}

Previous Conversation

{history}

Available Stock Data

{stock_data}

Important:

If the user asks only one question (price, PE ratio, news etc.) answer only that question.
Otherwise generate the complete report using the required format.
"""

def generate_analysis(
    user_query: str,
    stock_data: dict
):
    """
    Generate AI analysis.
    """

    history = get_recent_history()

    prompt = build_prompt(
        user_query,
        history,
        stock_data
    )

    response = client.models.generate_content(
        model="gemini-3.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            temperature=0.4
        )
    )

    return response.text

def handle_portfolio_commands(user_query: str):

    query = user_query.lower()

    if "portfolio" not in query:
        return None

    if "show" in query or "view" in query:

        return view_portfolio()

    if "analyze" in query:

        return analyze_portfolio()

    if "clear" in query:

        return clear_portfolio()

    company = resolve_company(user_query)

    if company is None:
        return "Please specify a valid company."

    if "add" in query:

        return add_stock(company["ticker"])

    if "remove" in query:

        return remove_stock(company["ticker"])

    return None

def compare_stock_analysis(user_query: str):

    tickers = get_multiple_tickers(user_query)

    if len(tickers) != 2:

        return None

    comparison_data = compare_companies(
        tickers[0],
        tickers[1]
    )

    response = client.models.generate_content(
        model="gemini-3.5-flash",

        contents=f"""
User Query:

{user_query}

Comparison Data:

{comparison_data}
""",

        config=types.GenerateContentConfig(
            system_instruction=COMPARISON_PROMPT,
            temperature=0.4
        )
    )

    return response.text

def chat_with_agent(user_query: str):

    # ---------- Portfolio ----------

    portfolio_response = handle_portfolio_commands(user_query)

    if portfolio_response is not None:
        return portfolio_response

    # ---------- Comparison ----------

    comparison = compare_stock_analysis(user_query)

    if comparison is not None:
        return comparison

    # ---------- Single Stock Analysis ----------

    company = resolve_company(user_query)

    if company is None:
        return (
            "❌ I couldn't identify the company.\n\n"
            "Please try one of these examples:\n\n"
            "• Analyze Infosys\n"
            "• Compare Infosys and TCS\n"
            "• What is the current price of Reliance?\n"
            "• Add TCS to my portfolio\n"
            "• Show portfolio"
        )

    stock_data = collect_stock_data(company)

    analysis = generate_analysis(
        user_query=user_query,
        stock_data=stock_data
    )

    save_conversation(
        user_query=user_query,
        assistant_response=analysis,
        ticker=company["ticker"],
        company=company["company"]
    )

    return analysis