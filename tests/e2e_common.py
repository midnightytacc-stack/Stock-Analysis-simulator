import re, sys, json, time, os, glob, hashlib
from playwright.sync_api import sync_playwright

RESULTS = []
def check(name, cond, detail=""):
    RESULTS.append((bool(cond), name, detail))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail and not cond else (f"  ({detail})" if detail else "")), flush=True)

def summary():
    bad = [r for r in RESULTS if not r[0]]
    print(f"\n{len(RESULTS)-len(bad)}/{len(RESULTS)} checks passed")
    return 1 if bad else 0

IGNORED_CONSOLE = ("ERR_NAME_NOT_RESOLVED", "fonts.googleapis", "fonts.gstatic")   # sandbox has no internet for Google Fonts

def new_page(browser, w=1300, h=800):
    ctx = browser.new_context(viewport={"width": w, "height": h})
    pg = ctx.new_page(); pg.console_msgs = []
    pg.on("console", lambda m: pg.console_msgs.append((m.type, m.text)) if m.type in ("error", "warning") else None)
    pg.on("pageerror", lambda e: pg.console_msgs.append(("pageerror", str(e))))
    return pg

def console_problems(pg):
    return [m for m in pg.console_msgs if not any(x in m[1] for x in IGNORED_CONSOLE)]

def open_app(pg, url):
    pg.goto(url); pg.wait_for_selector(".st-key-page", timeout=40000); pg.wait_for_timeout(800)

def nav(pg, emoji):
    pg.locator("button", has_text=re.compile(rf"^\s*{emoji}")).first.click(); pg.wait_for_timeout(1500)

def settle(pg, ms=1800):
    pg.wait_for_timeout(ms)
    try: pg.wait_for_selector("[data-testid=stStatusWidget]", state="detached", timeout=20000)
    except Exception: pass

def session_files():
    return {f: open(f).read() for f in glob.glob("/tmp/stock_assistant_sessions/*/portfolio.json")}
