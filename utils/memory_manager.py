import json
import os
from datetime import datetime

MEMORY_FILE = "memory/history.json"


def initialize_memory():

    os.makedirs("memory", exist_ok=True)

    if not os.path.exists(MEMORY_FILE):
        with open(MEMORY_FILE, "w", encoding="utf-8") as file:
            json.dump([], file, indent=4)


def load_history():
    """
    Load all saved conversations.
    """

    initialize_memory()

    try:

        with open(MEMORY_FILE, "r", encoding="utf-8") as file:

            content = file.read().strip()

            if not content:
                return []

            return json.loads(content)

    except json.JSONDecodeError:
        return []


def save_conversation(
    user_query,
    assistant_response,
    ticker=None,
    company=None
):

    history = load_history()

    history.append(
        {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "ticker": ticker,
            "company": company,
            "user_query": user_query,
            "assistant_response": assistant_response,
        }
    )

    with open(MEMORY_FILE, "w", encoding="utf-8") as file:
        json.dump(history, file, indent=4)


def get_recent_history(limit=5):

    history = load_history()

    return history[-limit:]


def get_last_company():
    """
    Return the last company discussed.
    """

    history = load_history()

    if not history:
        return None

    for conversation in reversed(history):

        ticker = conversation.get("ticker")
        company = conversation.get("company")

        if ticker and company:

            return {
                "ticker": ticker,
                "company": company
            }

    return None


def clear_history():

    with open(MEMORY_FILE, "w", encoding="utf-8") as file:
        json.dump([], file, indent=4)