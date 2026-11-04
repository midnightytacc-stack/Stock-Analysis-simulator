# Running & showcasing the web UI

## Run locally
```
pip install -r requirements.txt
streamlit run app.py
```
Keys come from `.env` (GEMINI_API_KEY, NEWS_API_KEY), same as the CLI.
Set `ISOLATE_SESSIONS=0` in `.env` to use your real `memory/*.json` files
instead of private per-visitor ones.

## Put it online (free): Streamlit Community Cloud
1. Push the project to a GitHub repo. `.env` is in `.gitignore` - never commit it.
2. Go to https://share.streamlit.io -> New app -> pick the repo, branch, main file `app.py`.
3. Advanced settings -> Secrets, paste:
   ```
   GEMINI_API_KEY = "your-new-key"
   NEWS_API_KEY   = "your-new-key"
   ```
4. Deploy. You get a public URL like `https://your-app.streamlit.app`.

## Showcase safety knobs (env vars, `.env` or Secrets)
| Name | Default | Meaning |
|---|---|---|
| MAX_QUERIES_PER_SESSION | 0 | Optional cap on AI questions per visitor session. `0` = the app sets no cap. Set e.g. `15` on a public deployment to protect your Gemini quota. |
| QUERY_COOLDOWN_SECONDS | 3 | Minimum gap between questions |
| ISOLATE_SESSIONS | 1 | Each visitor gets private memory + portfolio (a browser refresh starts a fresh private session). Set `0` to keep one persistent portfolio in `memory/portfolio.json`. |

The Assistant has no app-imposed question limit by default. Gemini's own rate limits and
quotas for your API key still apply (the free tier has per-minute and per-day limits); when one is
hit the app says which, and offers a **Try again** button. Charts and the portfolio table don't use
Gemini, so they are not affected.
