import os
import html
import subprocess
import tempfile
import re


RENDER_DIR = "workspace/rendered"
os.makedirs(RENDER_DIR, exist_ok=True)


def render_artifact(run_id, requirement, code_file, test_results):
    """Render an HTML visual representation of the deliverable."""
    code = ""
    if code_file and os.path.exists(code_file):
        with open(code_file, "r", encoding="utf-8") as f:
            code = f.read()

    kind = _detect_kind(requirement, code)

    if kind == "web":
        return ""

    if kind == "function":
        content = _render_function_card(requirement, code, test_results)
    elif kind == "api":
        content = _render_api_card(requirement, code, test_results)
    else:
        content = _render_generic_card(requirement, code, test_results)

    out_path = os.path.join(RENDER_DIR, run_id + ".html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(content)
    return out_path


def _detect_kind(requirement, code):
    req = requirement.lower()
    if any(k in req for k in ["page", "dashboard", "html", "css", "button",
                              "form", "layout", "render", "screen", "ui"]):
        return "web"
    if any(k in req for k in ["api", "endpoint", "http", "rest", "route"]):
        return "api"
    if "def " in code:
        return "function"
    return "generic"


def _render_function_card(requirement, code, test_results):
    funcs = re.findall(r"def\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\([^)]*\)\s*(?:->\s*[^:]+)?", code)
    sig_summary = "\n".join(funcs) if funcs else "(no functions found)"
    sample = _run_sample(code)

    return _html_wrap("Function Artifact", (
        "<h1>Function Deliverable</h1>"
        "<div class='section'><h2>Requirement</h2><pre>" + html.escape(requirement) + "</pre></div>"
        "<div class='section'><h2>Functions Defined</h2><pre>" + html.escape(sig_summary) + "</pre></div>"
        "<div class='section'><h2>Code</h2><pre class='code'>" + html.escape(code) + "</pre></div>"
        "<div class='section'><h2>Test Results</h2><pre>" + html.escape(test_results[:1500]) + "</pre></div>"
        "<div class='section'><h2>Sample Run</h2><pre>" + html.escape(sample) + "</pre></div>"
    ))


def _render_api_card(requirement, code, test_results):
    routes = re.findall(r"@\w+\.(get|post|put|delete)\s*\(\s*[\"']([^\"']+)[\"']", code)
    routes_summary = "\n".join(m.upper() + " " + p for m, p in routes) if routes else "(no routes found)"

    return _html_wrap("API Artifact", (
        "<h1>API Deliverable</h1>"
        "<div class='section'><h2>Requirement</h2><pre>" + html.escape(requirement) + "</pre></div>"
        "<div class='section'><h2>Routes</h2><pre>" + html.escape(routes_summary) + "</pre></div>"
        "<div class='section'><h2>Code</h2><pre class='code'>" + html.escape(code) + "</pre></div>"
        "<div class='section'><h2>Test Results</h2><pre>" + html.escape(test_results[:1500]) + "</pre></div>"
    ))


def _render_generic_card(requirement, code, test_results):
    return _html_wrap("Deliverable", (
        "<h1>Deliverable</h1>"
        "<div class='section'><h2>Requirement</h2><pre>" + html.escape(requirement) + "</pre></div>"
        "<div class='section'><h2>Code</h2><pre class='code'>" + html.escape(code) + "</pre></div>"
        "<div class='section'><h2>Tests</h2><pre>" + html.escape(test_results[:1500]) + "</pre></div>"
    ))


def _run_sample(code):
    m = re.search(r"def\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\(([^)]*)\)", code)
    if not m:
        return "(no function to run)"

    func_name = m.group(1)
    args = m.group(2).strip()

    sample_args = []
    for arg in args.split(","):
        arg = arg.strip()
        if not arg or arg.startswith("self"):
            continue
        if ":" in arg:
            typ = arg.split(":", 1)[1].split("=")[0].strip()
            if "int" in typ:
                sample_args.append("5")
            elif "list" in typ:
                sample_args.append("[1, 2, 3]")
            elif "dict" in typ:
                sample_args.append("{}")
            else:
                sample_args.append('"test"')
        else:
            sample_args.append('"test"')

    call = func_name + "(" + ", ".join(sample_args) + ")"

    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False)
    tmp.write(code + "\n\n")
    tmp.write("try:\n")
    tmp.write("    print('>>> " + call + "')\n")
    tmp.write("    print(repr(" + call + "))\n")
    tmp.write("except Exception as e:\n")
    tmp.write("    print('Error:', e)\n")
    tmp.close()

    try:
        result = subprocess.run(["python", tmp.name], capture_output=True, text=True, timeout=5)
        return result.stdout.strip() or result.stderr.strip() or "(no output)"
    except Exception as e:
        return "(could not run: " + str(e) + ")"
    finally:
        try:
            os.unlink(tmp.name)
        except Exception:
            pass


def _html_wrap(title, body):
    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'><title>"
        + html.escape(title)
        + "</title><style>"
        + "body{font-family:-apple-system,system-ui,sans-serif;background:#0f172a;color:#e2e8f0;padding:40px;max-width:1100px;margin:0 auto;}"
        + "h1{color:#38bdf8;border-bottom:2px solid #1e293b;padding-bottom:12px;}"
        + "h2{color:#7dd3fc;font-size:16px;margin-top:24px;}"
        + "pre{background:#1e293b;padding:16px;border-radius:8px;overflow-x:auto;font-size:13px;white-space:pre-wrap;word-wrap:break-word;}"
        + "pre.code{border-left:4px solid #10b981;}"
        + ".section{margin:20px 0;}"
        + "</style></head><body>"
        + body
        + "</body></html>"
    )