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

## Showcase safety knobs (env vars or Secrets)
| Name | Default | Meaning |
|---|---|---|
| MAX_QUERIES_PER_SESSION | 15 | AI questions per visitor session (protects your Gemini quota) |
| QUERY_COOLDOWN_SECONDS | 3 | Minimum gap between questions |
| ISOLATE_SESSIONS | 1 | Each visitor gets private memory + portfolio |

Charts and the portfolio table don't use Gemini, so they stay unlimited.
