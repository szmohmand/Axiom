"""Read-only real-browser acceptance for AXIOM mobile and desktop.

Starts the actual application/server with synthetic demo feeds and disabled
paper automation. This is a presentation/integration check, NOT a live feed
or probability/backtest claim.
"""
from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile
import time

import requests
from playwright.sync_api import sync_playwright


def run():
    port = 8765
    root = Path(__file__).resolve().parents[1]
    env = {**os.environ, "DEMO_MODE": "1", "AUTO_PAPER": "0",
           "BOT_ADMIN_TOKEN": "", "POLL_SECONDS": "5",
           "DATA_PATH": str(Path(tempfile.mkdtemp()) / "axiom-ui-acceptance.sqlite3")}
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1",
         "--port", str(port), "--workers", "1", "--log-level", "error"],
        cwd=root, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
    )
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(80):
            if proc.poll() is not None:
                raise AssertionError("Uvicorn stopped before acceptance")
            try:
                h = requests.get(base + "/health", timeout=2)
                if h.status_code == 200:
                    break
            except requests.RequestException:
                pass
            time.sleep(.5)
        else:
            raise AssertionError("No healthy real FastAPI server within startup deadline")

        state = requests.get(base + "/api/state", timeout=3).json()
        assert state["status"] == "DEMO" and state["ok"] is True
        assert state["model"]["available"] and len(state["engines"]) == 4
        assert state["orderbook"]["available"] and state["orderbook"]["is_full_aggregated_depth"]
        assert state["execution_intelligence"]["order_placed"] is False
        assert state["depth_opportunity"]["read_only"] is True

        results = []
        with sync_playwright() as play:
            browser = play.chromium.launch(headless=True)
            try:
                for name, width, height in (("iphone", 390, 844), ("desktop", 1280, 800)):
                    context = browser.new_context(viewport={"width": width, "height": height},
                                                  device_scale_factor=2 if name=="iphone" else 1,
                                                  is_mobile=(name=="iphone"),
                                                  has_touch=(name=="iphone"))
                    page = context.new_page()
                    script_errors=[]
                    page.on("pageerror",lambda err: script_errors.append(str(err)))
                    page.goto(base+"/", wait_until="networkidle",timeout=30000)
                    page.wait_for_function(
                        "() => document.querySelector('#marketTicker').textContent.trim().startsWith('DEMO-')",
                        timeout=15000
                    )
                    page.wait_for_function(
                        "() => /^\\d+$/.test(document.querySelector('#bookYesLevels').textContent.trim())",
                        timeout=15000
                    )
                    assert "No real orders are placed" in page.locator("body").inner_text()
                    for selector in ("#bookStatus", "#bookBidRows tr", "#bookAskRows tr",
                                     "#depthSide", "#execAction", "#scalpSide", "#forecastSide",
                                     "#engineRows tr", "#chart", "#paperYes", "#paperNo"):
                        assert page.locator(selector).count()>0, selector
                    assert page.locator("#paperYes").is_disabled()
                    assert page.locator("#paperNo").is_disabled()
                    data = page.evaluate("""() => ({
                      bodyWidth:document.body.scrollWidth,
                      viewport:window.innerWidth,
                      yes:document.querySelector('#bookYesLevels').textContent.trim(),
                      no:document.querySelector('#bookNoLevels').textContent.trim(),
                      status:document.querySelector('#status').textContent.trim(),
                      market:document.querySelector('#marketTicker').textContent.trim(),
                      action:document.querySelector('#execAction').textContent.trim(),
                      forecast:document.querySelector('#forecastSide').textContent.trim()
                    })""")
                    assert int(data["yes"])>0 and int(data["no"])>0, data
                    assert data["bodyWidth"]<=data["viewport"]+2, "Unexpected horizontal page overflow"
                    assert data["status"]=="DEMO", data
                    assert data["action"] in ("WAIT","ENTER"),data
                    assert not script_errors, "Dashboard JavaScript error(s): " + repr(script_errors)
                    screenshot=str(Path.cwd()/f"axiom-{name}-ui-acceptance.png")
                    page.screenshot(path=screenshot,full_page=True)
                    results.append({"screen":name,**data,"js_errors":script_errors,
                                    "paper_buttons_disabled":True,"screenshot":screenshot})
                    context.close()
            finally:
                browser.close()
        print(json.dumps({"verdict":"PASS","mode":"synthetic_demo","browser_results":results,
                          "real_orders":False},indent=2),flush=True)
    finally:
        proc.terminate()
        try:
            proc.communicate(timeout=6)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate(timeout=3)


if __name__ == "__main__":
    run()
