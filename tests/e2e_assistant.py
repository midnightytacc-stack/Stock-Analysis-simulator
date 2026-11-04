import sys
from e2e_common import *
URL = sys.argv[1]

def ask(pg, text):
    ci = pg.locator('[data-testid="stChatInput"] textarea'); ci.fill(text); ci.press("Enter")

def wait_reply(pg, n, timeout=40000):
    pg.wait_for_function(f"document.body.innerText.includes('Reply number {n}.')", timeout=timeout); pg.wait_for_timeout(400)

def nav_rect(pg):
    return pg.evaluate("() => { const r = document.querySelector('.st-key-page').getBoundingClientRect(); return {top: r.top, bottom: r.bottom, h: innerHeight}; }")

with sync_playwright() as p:
    br = p.chromium.launch(); pg = new_page(br, 1300, 800); open_app(pg, URL)
    check("A0 no question meter / cap by default", "questions left" not in pg.inner_text("body"))

    # --- several long assistant responses, multi-turn
    N = 20
    for i in range(1, N + 1):
        ask(pg, "Analyze Infosys" if i % 2 else "its P/E ratio")
        wait_reply(pg, i); pg.wait_for_timeout(3300 if False else 350)   # cooldown is set to 0.3s for the test run
        if i == 4:
            pg.mouse.wheel(0, 100000); pg.wait_for_timeout(600)
            r = nav_rect(pg)
            check("S1 after 4 long replies the nav is still on screen (sticky below the header)", 55 <= r["top"] <= 120, str(r))
            check("S1 page really is scrolled (so the test is meaningful)", pg.evaluate("() => document.querySelector('.stMain').scrollTop") > 500)
    body = pg.inner_text("body")
    check(f"Q1 {N} questions answered in one session (old cap was 15)", f"Reply number {N}." in body and "Demo limit" not in body and "limits each session" not in body)
    check("Q1 no question meter appears", "questions left" not in body)
    pg.mouse.wheel(0, 100000); pg.wait_for_timeout(800)
    r = nav_rect(pg)
    check(f"S2 after {N} turns, scrolled to the bottom: nav still visible", 55 <= r["top"] <= 120, str(r))
    ci = pg.locator('[data-testid="stChatInput"]'); cb = ci.bounding_box()
    check("S3 chat input stays visible and usable at the bottom", cb is not None and cb["y"] + cb["height"] <= 800 + 1 and cb["y"] > 600, str(cb))
    # nav must not overlap/hide the first rows of content or the header
    pg.screenshot(path="/tmp/e2e_sticky_bottom.png")
    # nav works from deep in the conversation
    nav(pg, "📉"); pg.wait_for_selector(".js-plotly-plot", timeout=30000)
    check("S4 Charts reachable from the scrolled conversation without scrolling up", pg.locator(".js-plotly-plot").count() >= 1)
    nav(pg, "💬"); pg.wait_for_timeout(1500)
    check("S4 Back to Assistant keeps the conversation", f"Reply number {N}." in pg.inner_text("body"))
    check("S5 exactly one navigation control (no duplicates)", pg.locator(".st-key-page").count() == 1)

    # --- provider errors: real google.genai ClientError objects from the stub
    open("/tmp/genai_fail_minute", "w").close()
    ask(pg, "Analyze Infosys"); pg.wait_for_selector("text=per-minute", timeout=30000)
    body = pg.inner_text("body")
    check("E1 429 per-minute: says it is the Gemini key, not this app; gives wait time", "not a limit set by this app" in body and "35 seconds" in body)
    check("E1 Try again button offered", pg.get_by_role("button", name=re.compile("Try again")).count() == 1)
    pg.get_by_role("button", name=re.compile("Try again")).click(); wait_reply(pg, N + 1)
    body = pg.inner_text("body")
    check("E2 retry re-asks the question and succeeds; error removed", f"Reply number {N+1}." in body and "per-minute" not in body)
    open("/tmp/genai_fail_day", "w").close()
    time.sleep(0.5); ask(pg, "Analyze Infosys"); pg.wait_for_selector("text=daily", timeout=30000)
    check("E3 429 daily quota explained as provider-side", "daily" in pg.inner_text("body") and "not a limit set by this app" in pg.inner_text("body"))
    pg.get_by_role("button", name=re.compile("Try again")).click(); wait_reply(pg, N + 2)
    open("/tmp/genai_fail_key", "w").close()
    time.sleep(0.5); ask(pg, "Analyze Infosys"); pg.wait_for_selector("text=rejected the API key", timeout=30000)
    check("E4 bad key: explained, no retry button (retry cannot help)", pg.get_by_role("button", name=re.compile("Try again")).count() == 0)

    probs = console_problems(pg)
    check("X2 no browser console errors (assistant)", not probs, str(probs[:4]))
    br.close()
sys.exit(summary())
