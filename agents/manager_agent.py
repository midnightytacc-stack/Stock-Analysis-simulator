import re
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

from tools.market_tool import (
    get_market_overview
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


MARKET_PROMPT = """
You are an Indian stock market research analyst.

Your task is to analyze the Indian stock market using the
market data provided to you.

Analyze the following areas:

1. Overall Market Performance
   - Nifty 50 and Sensex movements.
   - Daily percentage changes.
   - Overall market direction.

2. Sector Performance
   - Compare Banking, IT, Pharma and FMCG.
   - Identify the strongest and weakest sectors.
   - Only compare sectors with successfully retrieved data.

3. Market Volatility
   - Analyze India VIX.
   - Explain whether volatility is increasing or decreasing.
   - Avoid making unsupported predictions.

4. Overall Market Health
   - Classify the market as Bullish, Bearish, Mixed or Neutral.
   - Explain the factors supporting your assessment.
   - Highlight potential risks.

5. Final Summary
   - Give a concise assessment of current market conditions.
   - Explain what investors should watch.

IMPORTANT RULES:

- Use only the supplied market data.
- Never invent missing values or market movements.
- Clearly identify unavailable data.
- Use the latest trading date provided in the data.
- Do not describe delayed daily data as live data.
- Distinguish short-term market movements from long-term trends.
- Do not provide guaranteed predictions or personalized
  buy/sell recommendations.
- If insufficient benchmark data is available, clearly state
  that a reliable overall market assessment cannot be made.

Use clear headings, bullet points and professional language.
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

GREETINGS = {
    "hi",
    "hello",
    "hey",
    "hii",
    "hiii",
    "good morning",
    "good afternoon",
    "good evening",
    "howdy",
}

HELP_MESSAGES = {
    "help",
    "what can you do",
    "what can you do?",
    "how can you help",
    "how can you help me",
}


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
    query = user_query.lower().strip()

    portfolio_related = (
        "portfolio" in query
        or "holdings" in query
    )

    if not portfolio_related:
        return None

    # ---------- Clear Portfolio ----------
    if "clear" in query or "empty" in query:
        return clear_portfolio()

    # ---------- Analyze Portfolio ----------
    if "analyze" in query or "analyse" in query:
        return analyze_portfolio()

    # ---------- View Portfolio ----------
    view_phrases = [
        "show",
        "view",
        "list",
        "what is in",
        "what's in",
        "whats in",
        "display",
        "my holdings",
        "what do i have",
    ]

    if any(phrase in query for phrase in view_phrases):
        return view_portfolio()

    # ---------- Add or Remove Stock ----------
    company = resolve_company(user_query)

    if company is None:
        if "add" in query:
            return "Please specify a valid company to add to your portfolio."
        if "remove" in query or "delete" in query:
            return "Please specify a valid company to remove from your portfolio."

        return (
            "What would you like to do with your portfolio?\n\n"
            "• Show my portfolio\n"
            "• Analyze my portfolio\n"
            "• Add Wipro to my portfolio\n"
            "• Remove Wipro from my portfolio\n"
            "• Clear my portfolio"
        )

    if "add" in query:
        return add_stock(company["ticker"])

    if "remove" in query or "delete" in query:
        return remove_stock(company["ticker"])

    return (
        "What would you like to do with your portfolio?\n\n"
        "• Show my portfolio\n"
        "• Analyze my portfolio\n"
        "• Add a stock\n"
        "• Remove a stock"
    )



def is_market_query(user_query: str) -> bool:
    """
    Identify questions about the overall Indian stock market,
    benchmark indices, volatility and sector performance.
    """

    query = user_query.lower().strip()

    # Handle possessive forms of market
    query = re.sub(r"\bmarket['’]s\b", "market", query)

    query = " ".join(query.split())

    market_phrases = [
        "how is the market",
        "how's the market",
        "market health",
        "market today",
        "market overview",
        "market sentiment",
        "market performance",
        "market conditions",
        "market condition",
        "indian market",
        "market bullish",
        "market bearish",
        "nifty",
        "sensex",
        "india vix",
        "vix",
        "sector performance",
        "which sectors are performing",
        "strongest sectors",
        "weakest sectors",
    ]

    return any(
        phrase in query for phrase in market_phrases
    )


def analyze_market(user_query: str):
    """
    Fetch Indian market data and generate an AI-powered
    market intelligence report.
    """

    market_data = get_market_overview()

    if "error" in market_data:
        return (
            "Unable to generate the market report right now.\n\n"
            f"Details: {market_data['error']}"
        )

    response = client.models.generate_content(
        model="gemini-3.5-flash",
        contents=f"""
User Query:

{user_query}

Indian Market Data:

{market_data}
""",
        config=types.GenerateContentConfig(
            system_instruction=MARKET_PROMPT,
            temperature=0.3
        )
    )

    return response.text

def compare_stock_analysis(user_query: str):

    tickers = get_multiple_tickers(user_query)
    query = user_query.lower().strip()

    # Handle references to stocks already in the portfolio.
    comparison_phrases = [
        "compare them",
        "compare these",
        "compare both",
        "compare these stocks",
        "compare my portfolio",
        "compare portfolio",
    ]

    phrase_detected = any(
        phrase in query for phrase in comparison_phrases
    )

    if len(tickers) != 2 and phrase_detected:

        # Retrieve the portfolio using the existing portfolio tool.
        from tools.portfolio_tool import load_portfolio

        portfolio = load_portfolio()

        if len(portfolio) == 2:
            tickers = [
                stock["ticker"] for stock in portfolio
            ]

        elif len(portfolio) < 2:
            return (
                "Your portfolio needs at least two stocks to compare. "
                "Add two stocks or specify their names, for example: "
                "'Compare Wipro and TCS'."
            )

        else:
            return (
                f"You have {len(portfolio)} stocks in your portfolio. "
                "Please specify which two you want to compare, "
                "for example: 'Compare Wipro and TCS'."
            )

    # Require exactly two identified stocks.
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

    query = user_query.strip().lower()

    # ---------- Greetings ----------
    if query in GREETINGS:
        return (
            "Hey! 👋 I'm your AI Stock Research Assistant.\n\n"
            "I can help you:\n"
            "• Analyze NSE-listed companies\n"
            "• Check stock prices and financial ratios\n"
            "• Review technical indicators and company news\n"
            "• Compare two companies\n"
            "• Manage and analyze your portfolio\n\n"
            "Try asking: \"What is the price of Tata Steel today?\""
        )

    # ---------- Help ----------
    if query in HELP_MESSAGES:
        return (
            "Here's what I can help with:\n\n"
            "• Stock analysis — \"Analyze Infosys\"\n"
            "• Stock prices — \"What is Tata Steel's price today?\"\n"
            "• Financial ratios — \"What is its PE ratio?\"\n"
            "• Comparisons — \"Compare TCS and Infosys\"\n"
            "• Portfolio — \"Show my portfolio\""
        )

    # ---------- Portfolio ----------
    portfolio_response = handle_portfolio_commands(user_query)

    if portfolio_response is not None:
        return portfolio_response

    # ---------- Market Intelligence ----------
    if is_market_query(user_query):
        return analyze_market(user_query)  
    
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
