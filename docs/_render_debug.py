"""Diagnostic: launch the render template in playwright and dump console + errors."""
from pathlib import Path
from playwright.sync_api import sync_playwright

TEMPLATE = Path(r"C:/Users/777kr/.claude/skills/excalidraw-diagram/references/render_template.html").as_uri()

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.on("console", lambda msg: print(f"[console.{msg.type}] {msg.text}"))
    page.on("pageerror", lambda err: print(f"[pageerror] {err}"))
    page.on("requestfailed", lambda req: print(f"[requestfailed] {req.url} :: {req.failure}"))
    page.goto(TEMPLATE)
    try:
        page.wait_for_function("window.__moduleReady === true", timeout=45000)
        print("module ready OK")
    except Exception as e:
        print(f"TIMEOUT: {e}")
        print("moduleReady:", page.evaluate("typeof window.__moduleReady"))
    browser.close()
