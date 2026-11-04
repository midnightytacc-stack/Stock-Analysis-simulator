import sys, json, hashlib
from e2e_common import *

URL = sys.argv[1]
SHARED = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "memory", "portfolio.json")
sha = lambda p: hashlib.sha256(open(p, "rb").read()).hexdigest()

def pf_search_and_pick(pg, text, label):
    box = pg.get_by_label("Search NSE companies"); box.fill(text); box.press("Enter")
    pg.wait_for_selector("text=Matching companies", timeout=15000)
    pg.get_by_text(label, exact=True).first.click(); pg.wait_for_selector(".sa-selected", timeout=10000); pg.wait_for_timeout(500)

def holdings_file():
    f = session_files(); assert len(f) >= 1; return json.loads(list(f.values())[-1])

def remove_options(pg):
    for _ in range(3):      # the first click can only focus the widget; retry until the list opens
        pg.locator('[data-testid="stSelectbox"]').first.click(); pg.wait_for_timeout(700)
        opts = [o.inner_text() for o in pg.get_by_role("option").all()]
        if opts: break
    pg.keyboard.press("Escape"); return opts

with sync_playwright() as p:
    br = p.chromium.launch()
    shared_before = sha(SHARED)
    pg = new_page(br); open_app(pg, URL)

    # ------------------------------------------------------------ PORTFOLIO
    nav(pg, "💼"); pg.wait_for_selector("text=Search NSE companies", timeout=20000)
    body = pg.inner_text("body")
    check("P1 no sample/demo portfolio UI", "sample" not in body.lower() and "load sample" not in body.lower())
    check("P1 empty-state guidance shown", "Your portfolio is empty" in body)

    pg.get_by_role("button", name=re.compile("Add to Portfolio")).click(); pg.wait_for_timeout(1200)
    check("P2 Add with nothing selected -> clear warning", "pick one of the suggestions" in pg.inner_text("body"))

    pf_search_and_pick(pg, "Infosys", "Infosys Limited — INFY")
    pg.get_by_role("button", name=re.compile("Add to Portfolio")).click()
    pg.wait_for_selector("text=Added Infosys Limited (INFY) to your portfolio", timeout=15000); pg.wait_for_timeout(1500)
    h = holdings_file()
    check("P3 valid holding persisted to the visitor's session file", [x["ticker"] for x in h] == ["INFY.NS"], str(h))
    check("P3 shared memory/portfolio.json untouched (no cross-visitor leak)", sha(SHARED) == shared_before)
    opts = remove_options(pg)
    check("P3 holding appears in the UI immediately (Remove list rebuilt from file)", any("INFY.NS" in o for o in opts), str(opts))
    grid = pg.locator('[data-testid="stDataFrame"]')
    check("P3 Holdings table rendered", grid.count() == 1)
    check("P3 search box cleared after add", pg.get_by_label("Search NSE companies").input_value() == "")

    # duplicate
    pf_search_and_pick(pg, "INFY", "Infosys Limited — INFY")
    check("P4 duplicate flagged on the selected card", "already in your portfolio" in pg.locator(".sa-selected").inner_text())
    pg.get_by_role("button", name=re.compile("Add to Portfolio")).click(); pg.wait_for_timeout(1500)
    check("P4 duplicate add refused with a message", "already in your portfolio — nothing was changed" in pg.inner_text("body"))
    check("P4 no duplicate row written", len(holdings_file()) == 1)

    # alias + second holding
    pg.get_by_role("button", name="Clear", exact=True).click(); pg.wait_for_timeout(500)
    pf_search_and_pick(pg, "tcs", "Tata Consultancy Services Limited — TCS")
    pg.get_by_role("button", name=re.compile("Add to Portfolio")).click()
    pg.wait_for_selector("text=Added Tata Consultancy Services Limited (TCS)", timeout=15000); pg.wait_for_timeout(1200)
    check("P5 second holding added", sorted(x["ticker"] for x in holdings_file()) == ["INFY.NS", "TCS.NS"])

    # remove
    pg.get_by_role("button", name=re.compile("Remove selected")).click(); pg.wait_for_timeout(1500)
    check("P6 Remove with nothing chosen -> warning", "Choose a holding to remove first" in pg.inner_text("body"))
    for _ in range(3):
        pg.locator('[data-testid="stSelectbox"]').first.click(); pg.wait_for_timeout(700)
        if pg.get_by_role("option", name=re.compile("INFY.NS")).count(): break
    pg.get_by_role("option", name=re.compile("INFY.NS")).click(); pg.wait_for_timeout(500)
    pg.get_by_role("button", name=re.compile("Remove selected")).click(); pg.wait_for_timeout(2000)
    check("P6 removal confirmed in UI", "has been removed from your portfolio" in pg.inner_text("body"))
    check("P6 file updated after removal", [x["ticker"] for x in holdings_file()] == ["TCS.NS"], str(holdings_file()))
    opts = remove_options(pg)
    check("P6 Remove list updated", not any("INFY" in o for o in opts) and any("TCS.NS" in o for o in opts), str(opts))
    pg.screenshot(path="/tmp/e2e_portfolio.png", full_page=True)

    # ------------------------------------------------------------ CHARTS
    nav(pg, "📉"); pg.wait_for_selector(".js-plotly-plot", timeout=30000); settle(pg)
    check("C1 Charts opens with a default company card", "Infosys" in pg.locator(".sa-selected").first.inner_text() or "INFY" in pg.locator(".sa-selected").first.inner_text())
    def charting_card(): return pg.locator(".sa-selected").first.inner_text()
    def pick_chart(text, label):
        box = pg.get_by_label("Company name or NSE symbol"); box.fill(text); box.press("Enter")
        pg.wait_for_selector("text=Matching companies", timeout=15000)
        pg.get_by_text(label, exact=True).first.click(); settle(pg, 2500)
    pick_chart("reliance", "Reliance Industries Limited — RELIANCE")
    check("C2 pick by company name -> card shows name+symbol+ticker", all(x in charting_card() for x in ("Reliance Industries Limited", "RELIANCE", "RELIANCE.NS")), charting_card())
    check("C2 chart + snapshot reloaded for RELIANCE.NS", "RELIANCE.NS" in pg.inner_text("body") and pg.locator(".js-plotly-plot").count() >= 1)
    check("C2 search box cleared after picking", pg.get_by_label("Company name or NSE symbol").input_value() == "")
    pick_chart("TCS", "Tata Consultancy Services Limited — TCS")
    check("C3 pick by NSE symbol -> TCS.NS", "TCS.NS" in charting_card() and "TCS.NS" in pg.inner_text("body"), charting_card())
    box = pg.get_by_label("Company name or NSE symbol"); box.fill("zzzzqqq"); box.press("Enter"); pg.wait_for_timeout(1500)
    check("C4 no match -> readable warning, selection kept", "No NSE company matches" in pg.inner_text("body") and "TCS.NS" in charting_card())
    box.fill("")  ; box.press("Enter"); pg.wait_for_timeout(800)

    # failing provider (WIPRO.NS raises in the stub)
    pick_chart("wipro", "Wipro Limited — WIPRO")
    body = pg.inner_text("body")
    check("C5 data-fetch failure -> error message + retry, no crash", "simulated Yahoo outage" in body and "Try again" in body and "Traceback" not in body)
    pick_chart("infosys", "Infosys Limited — INFY")
    check("C5 recovers on the next selection", pg.locator(".js-plotly-plot").count() >= 1 and "INFY.NS" in charting_card())

    # ---------------- ranges
    def xrange():
        return pg.evaluate("() => { const g = document.querySelector('.js-plotly-plot'); const r = g._fullLayout.xaxis.range; return [r[0], r[1]]; }")
    from datetime import datetime, timedelta
    def years_shown():
        a, b = xrange(); d = lambda x: datetime.fromisoformat(x.replace(' ', 'T')[:19]); return (d(b) - d(a)).days / 365.25
    def click_range(lbl):
        pg.locator("button", has_text=re.compile(rf"^\s*{lbl}\s*$")).first.click(); settle(pg, 3000)
    click_range("5Y"); y5 = years_shown()
    check("R1 5Y shows ~5 years", 4.5 < y5 < 5.4, f"{y5:.2f}y")
    t0 = time.time(); click_range("All Time"); y_all = years_shown(); dt = time.time() - t0
    check("R2 All Time shows data older than 5 years", y_all > 15, f"{y_all:.2f}y")
    check("R2 All Time explains what is shown", "All Time shows the full history" in pg.inner_text("body"), "")
    check("R2 indicator panels still drawn on the long series", pg.evaluate("() => document.querySelector('.js-plotly-plot').data.length") >= 6)
    check("R2 All Time renders in a reasonable time", dt < 20, f"{dt:.1f}s")
    click_range("3M"); y3 = years_shown()
    check("R3 3M still works after All Time", y3 < 0.4, f"{y3:.2f}y")
    click_range("All Time")
    pg.wait_for_function("document.querySelectorAll('.signal').length === 4", timeout=15000)
    check("R4 signal cards still present with All Time", pg.locator(".signal").count() == 4)
    pick_chart("zomato", "ETERNAL LIMITED — ETERNAL")      # alias + short history (1y in the stub)
    body = pg.inner_text("body")
    check("R5 short-history stock under All Time: no crash, shows what exists", pg.locator(".js-plotly-plot").count() >= 1 and "All Time shows the full history" in body and "Traceback" not in body, "")
    click_range("5Y")
    check("R5 5Y on a short-history stock explains the shorter data", "Only " in pg.inner_text("body") and "available for this stock" in pg.inner_text("body"))
    pg.screenshot(path="/tmp/e2e_charts.png", full_page=False)

    # period state survives leaving/returning
    nav(pg, "💼"); nav(pg, "📉"); settle(pg, 2500)
    check("C6 range + stock survive page switch", "ETERNAL" in charting_card() and pg.locator(".js-plotly-plot").count() >= 1)

    probs = console_problems(pg)
    check("X1 no browser console errors/warnings (portfolio+charts)", not probs, str(probs[:4]))

    # isolation: a second visitor does not see the first visitor's holding
    pg2 = new_page(br); open_app(pg2, URL); nav(pg2, "💼"); pg2.wait_for_selector("text=Search NSE companies", timeout=20000)
    check("I1 second visitor starts with an empty private portfolio", "Your portfolio is empty" in pg2.inner_text("body"))
    br.close()
sys.exit(summary())
