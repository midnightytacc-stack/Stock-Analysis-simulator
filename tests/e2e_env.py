import sys, json
from e2e_common import *
URL = sys.argv[1]; APP = "/tmp/app_env_test"
def ask(pg, text):
    ci = pg.locator('[data-testid="stChatInput"] textarea'); ci.fill(text); ci.press("Enter")
with sync_playwright() as p:
    br = p.chromium.launch(); pg = new_page(br); open_app(pg, URL)
    # .env => ISOLATE_SESSIONS=0, MAX_QUERIES_PER_SESSION=3 (must be honoured now)
    nav(pg, "💼"); pg.wait_for_selector("text=Search NSE companies", timeout=20000)
    box = pg.get_by_label("Search NSE companies"); box.fill("Infosys"); box.press("Enter")
    pg.wait_for_selector("text=Matching companies"); pg.get_by_text("Infosys Limited — INFY", exact=True).first.click()
    pg.wait_for_selector(".sa-selected"); pg.get_by_role("button", name=re.compile("Add to Portfolio")).click()
    pg.wait_for_selector("text=Added Infosys Limited (INFY)", timeout=15000); pg.wait_for_timeout(1200)
    saved = json.load(open(f"{APP}/memory/portfolio.json"))
    check("N1 .env ISOLATE_SESSIONS=0 honoured: holding written to memory/portfolio.json", [h["ticker"] for h in saved] == ["INFY.NS"], str(saved))
    check("N1 no per-visitor session folder used", session_files() == {})
    pg.reload(); pg.wait_for_selector(".st-key-page", timeout=30000); nav(pg, "💼"); pg.wait_for_selector("text=Search NSE companies", timeout=20000); pg.wait_for_timeout(1500)
    sb = pg.locator('[data-testid="stSelectbox"]'); check("N2 holding still there after a full browser refresh", sb.count() == 1)
    for _ in range(3):
        sb.first.click(); pg.wait_for_timeout(700)
        if pg.get_by_role("option").count(): break
    check("N2 ...and listed for removal", any("INFY.NS" in o.inner_text() for o in pg.get_by_role("option").all()))
    pg.keyboard.press("Escape")

    nav(pg, "💬"); pg.wait_for_timeout(1000)
    check("N3 .env MAX_QUERIES_PER_SESSION=3 honoured: meter shown", "questions left this session: 3/3" in pg.inner_text("body"))
    for i in range(1, 4):
        ask(pg, "Analyze Infosys"); pg.wait_for_function(f"document.body.innerText.includes('Reply number {i}.')", timeout=40000); pg.wait_for_timeout(500)
    ask(pg, "Analyze Infosys"); pg.wait_for_selector("text=limits each session to 3 AI questions", timeout=15000)
    check("N3 optional cap enforced with a clear message", True)
    probs = console_problems(pg); check("X3 no console errors", not probs, str(probs[:3]))
    br.close()
sys.exit(summary())
