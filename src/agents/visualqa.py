import os
from PIL import Image, ImageChops, ImageDraw
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
from langchain_ollama import ChatOllama
from langchain_core.messages import SystemMessage, HumanMessage
from src.db import append_event
from src.agents.visualrender import render_artifact

SCREENSHOT_DIR = "workspace/screenshots"
BASELINE_DIR = "workspace/baselines"
DIFF_DIR = "workspace/diffs"

for d in (SCREENSHOT_DIR, BASELINE_DIR, DIFF_DIR):
    os.makedirs(d, exist_ok=True)

PIXEL_DIFF_THRESHOLD = 2.0
MAX_ALLOWED_DIFF_PCT = 5.0


def visual_qa_agent(state):
    run_id = state.get("run_id", "unknown")
    requirement = state.get("requirement", "")
    code_file = state.get("code_file", "")
    test_results = state.get("test_results", "")

    req = requirement.lower()
    is_web = any(k in req for k in [
        "page", "dashboard", "html", "css", "button",
        "form", "layout", "render", "screen", "ui",
    ])

    if is_web:
        url = state.get("app_url") or os.getenv("APP_URL", "http://localhost:8000")
        source = "live_web"
        print("[Visual QA] Web requirement — screenshotting " + url)
    else:
        html_path = render_artifact(run_id, requirement, code_file, test_results)
        if not html_path:
            append_event(run_id, {
                "agent": "visual_qa",
                "status": "done",
                "message": "Could not render artifact — skipped",
            })
            return {**state, "visual_qa_result": "render_failed"}
        url = "file:///" + os.path.abspath(html_path).replace("\\", "/")
        source = "rendered"
        print("[Visual QA] Rendered artifact — screenshotting " + url)

    append_event(run_id, {
        "agent": "visual_qa",
        "status": "running",
        "message": "Capturing " + source + " artifact",
    })

    current_path = os.path.join(SCREENSHOT_DIR, run_id + ".png")
    baseline_path = os.path.join(BASELINE_DIR, "baseline_" + source + ".png")

    err = capture_screenshot(url, current_path)
    if err:
        append_event(run_id, {
            "agent": "visual_qa",
            "status": "error",
            "message": "Capture failed: " + err,
        })
        return {**state, "visual_qa_result": "error: " + err, "is_ready": False}

    if not os.path.exists(baseline_path):
        Image.open(current_path).save(baseline_path)
        append_event(run_id, {
            "agent": "visual_qa",
            "status": "done",
            "message": "Baseline created for " + source,
        })
        return {**state, "visual_qa_result": "baseline_created", "visual_source": source}

    diff = compare_images(baseline_path, current_path)
    diff_pct = diff["percentage"]

    if diff.get("diff_image"):
        diff["diff_image"].save(os.path.join(DIFF_DIR, run_id + "_diff.png"))

    append_event(run_id, {
        "agent": "visual_qa",
        "status": "info",
        "message": "Pixel difference: " + str(round(diff_pct, 2)) + "%",
    })

    if diff_pct < PIXEL_DIFF_THRESHOLD:
        append_event(run_id, {
            "agent": "visual_qa",
            "status": "done",
            "message": "Artifact matches baseline (" + str(round(diff_pct, 2)) + "%)",
        })
        return {
            **state,
            "visual_qa_result": "passed",
            "visual_diff_pct": diff_pct,
            "visual_source": source,
        }

    if diff_pct > MAX_ALLOWED_DIFF_PCT:
        analysis = analyze_visual_diff(baseline_path, current_path, state)
        append_event(run_id, {
            "agent": "visual_qa",
            "status": "warning",
            "message": "REGRESSION: " + str(round(diff_pct, 2)) + "% — " + analysis[:150],
        })
        return {
            **state,
            "visual_qa_result": "regression: " + str(round(diff_pct, 2)) + "%",
            "visual_analysis": analysis,
            "visual_diff_pct": diff_pct,
            "visual_source": source,
            "is_ready": False,
        }

    return {
        **state,
        "visual_qa_result": "minor_drift",
        "visual_diff_pct": diff_pct,
        "visual_source": source,
    }


def capture_screenshot(url, out_path):
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            page.goto(url, wait_until="load", timeout=15000)
            page.wait_for_timeout(500)
            page.screenshot(path=out_path, full_page=True)
            browser.close()
        return None
    except PWTimeout:
        return "page load timeout"
    except Exception as e:
        return str(e)


def compare_images(baseline_path, current_path):
    baseline = Image.open(baseline_path).convert("RGB")
    current = Image.open(current_path).convert("RGB")

    if baseline.size != current.size:
        baseline = baseline.resize(current.size)

    diff = ImageChops.difference(baseline, current)
    bbox = diff.getbbox()
    if not bbox:
        return {"percentage": 0.0}

    gray = diff.convert("L")
    thresholded = gray.point(lambda p: 255 if p > 20 else 0)
    changed_pixels = sum(thresholded.point(lambda p: 1 if p > 0 else 0).getdata())
    total_pixels = baseline.size[0] * baseline.size[1]
    pct = (changed_pixels / total_pixels) * 100

    diff_vis = baseline.copy()
    draw = ImageDraw.Draw(diff_vis)
    draw.rectangle(bbox, outline="red", width=3)

    return {"percentage": pct, "diff_image": diff_vis, "bbox": bbox}


def analyze_visual_diff(baseline_path, current_path, state):
    try:
        llm = ChatOllama(model="llama3.2:3b", temperature=0.3, num_ctx=2048)
        req = state.get("requirement", "unknown")
        prompt = (
            "A visual regression was detected between a baseline artifact and "
            "the current artifact. Requirement: " + req + ". "
            "In 2-3 sentences, describe what likely changed."
        )
        messages = [
            SystemMessage(content="You are a Visual QA engineer analyzing UI changes."),
            HumanMessage(content=prompt),
        ]
        return llm.invoke(messages).content
    except Exception as e:
        return "Analysis failed: " + str(e)