import requests 
from config import NEWS_API_KEY


def _fetch_news(company: str) -> dict:

    url = "https://newsapi.org/v2/everything"

    params = {
        "q": f'"{company}"',
        "language": "en",
        "sortBy": "publishedAt",
        "pageSize": 5,
        "apiKey": NEWS_API_KEY
    }

    response = requests.get(
        url,
        params=params,
        timeout=10
    )

    response.raise_for_status()

    return response.json()


def get_company_news(company: str) -> list | dict:

    try:

        data = _fetch_news(company)

        if data.get("status") != "ok":
            return {
                "error": data.get("message", "Failed to fetch news.")
            }

        articles = data.get("articles", [])

        news = []

        for article in articles:

            news.append({
                "title": article.get("title"),
                "description": article.get("description"),
                "source": article.get("source", {}).get("name"),
                "published_at": article.get("publishedAt"),
                "url": article.get("url")
            })

        return news

    except Exception as e:

        return {
            "error": f"Failed to fetch company news: {str(e)}"
        }