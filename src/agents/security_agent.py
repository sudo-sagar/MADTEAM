import os
import re
import json
import subprocess
from pathlib import Path
from langchain_ollama import ChatOllama

from langchain_core.messages import SystemMessage, HumanMessage
#from src.llm import get_llm
from src.db import append_event

SECURITY_DIR = "workspace/security"
os.makedirs(SECURITY_DIR, exist_ok=True)

BLOCK_ON_HIGH = True
MAX_MEDIUM_ISSUES = 3


def security_agent(state: dict) -> dict:
    """Security Agent: runs Bandit + secrets scan; auto-patches HIGH issues."""
    run_id = state.get("run_id", "unknown")
    code_file = state.get("code_file", "")

    print("\n[Security] Running vulnerability scan...")
    append_event(run_id, {
        "agent": "security",
        "status": "running",
        "message": "Running vulnerability scan",
    })

    if not code_file or not os.path.exists(code_file):
        append_event(run_id, {
            "agent": "security",
            "status": "done",
            "message": "Skipped — no code file to scan",
        })
        return {**state, "security_result": "skipped"}

    # ─── 1. Bandit ───
    bandit_result = run_bandit(code_file)
    append_event(run_id, {
        "agent": "security",
        "status": "info",
        "message": f"Bandit: {bandit_result['severity_counts']}",
    })

    # ─── 2. Secrets scan ───
    secrets_result = scan_secrets(code_file)
    if secrets_result:
        append_event(run_id, {
            "agent": "security",
            "status": "warning",
            "message": f"Secrets scan: {len(secrets_result)} potential secrets",
        })

    # ─── 3. Aggregate ───
    high_issues = bandit_result.get("high_issues", [])
    medium_count = bandit_result["severity_counts"].get("MEDIUM", 0)
    secret_count = len(secrets_result)

    critical = (
        (BLOCK_ON_HIGH and len(high_issues) > 0)
        or medium_count > MAX_MEDIUM_ISSUES
        or secret_count > 0
    )

    report = {
        "bandit": bandit_result,
        "secrets": secrets_result,
        "critical": critical,
    }

    # Save report
    report_path = os.path.join(SECURITY_DIR, f"{run_id}.json")
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, default=str)

    # ─── 4. Clean or self-heal ───
    if not critical:
        print(f"Security: CLEAN ({medium_count} MEDIUM, {secret_count} secrets)")
        append_event(run_id, {
            "agent": "security",
            "status": "done",
            "message": f"CLEAN — 0 HIGH, {medium_count} MEDIUM, {secret_count} secrets",
        })
        return {**state, "security_result": "clean"}

    # Build the issue list for the LLM
    issues_for_llm = []
    for h in high_issues:
        issues_for_llm.append({
            "kind": "bandit_high",
            "id": h.get("test_id"),
            "description": h.get("issue_text"),
            "line": h.get("line_number"),
            "code": h.get("code"),
        })
    for s in secrets_result:
        issues_for_llm.append({
            "kind": "hardcoded_secret",
            "type": s["type"],
            "line": s["line_number"],
            "code": s["code"],
        })
    if medium_count > MAX_MEDIUM_ISSUES:
        issues_for_llm.append({
            "kind": "bandit_medium_count",
            "count": medium_count,
        })

    print(f"Security: {len(issues_for_llm)} issue(s) found — generating patch")
    append_event(run_id, {
        "agent": "security",
        "status": "warning",
        "message": f"{len(issues_for_llm)} issue(s) found — generating patch",
    })

    patch = generate_security_patch(state, code_file, issues_for_llm)

    return {
        **state,
        "security_result": f"{len(issues_for_llm)} issues",
        "security_patch": patch,
        "security_report": report,
        "is_ready": False,
        "messages": state.get("messages", []) + [{
            "role": "security",
            "content": f"Found {len(issues_for_llm)} security issues. Patch generated.",
        }],
    }


def run_bandit(code_file: str) -> dict:
    """Run Bandit static analysis."""
    try:
        result = subprocess.run(
            ["bandit", "-f", "json", "-q", code_file],
            capture_output=True, text=True, timeout=30,
        )
        stdout = result.stdout.strip()
        if not stdout:
            return {
                "severity_counts": {"HIGH": 0, "MEDIUM": 0, "LOW": 0},
                "high_issues": [], "all_issues": [],
            }

        data = json.loads(stdout)
        results = data.get("results", [])

        by_severity = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
        high_issues = []
        for issue in results:
            sev = issue.get("issue_severity", "LOW").upper()
            by_severity[sev] = by_severity.get(sev, 0) + 1
            if sev == "HIGH":
                high_issues.append({
                    "test_id": issue.get("test_id"),
                    "issue_text": issue.get("issue_text"),
                    "line_number": issue.get("line_number"),
                    "code": (issue.get("code") or "").strip()[:200],
                })

        return {
            "severity_counts": by_severity,
            "high_issues": high_issues,
            "all_issues": results,
        }
    except json.JSONDecodeError:
        return {
            "severity_counts": {"HIGH": 0, "MEDIUM": 0, "LOW": 0},
            "high_issues": [],
            "error": "bandit output unparseable",
        }
    except Exception as e:
        return {
            "severity_counts": {"HIGH": 0, "MEDIUM": 0, "LOW": 0},
            "high_issues": [],
            "error": str(e),
        }


SECRET_PATTERNS = [
    (re.compile(r'(?i)(api[_-]?key|apikey)\s*[:=]\s*[\'"]([A-Za-z0-9_\-]{16,})[\'"]'), "API key"),
    (re.compile(r'(?i)(secret|password|passwd|pwd)\s*[:=]\s*[\'"]([^\'"]{6,})[\'"]'), "Hardcoded credential"),
    (re.compile(r'sk-[A-Za-z0-9]{20,}'), "OpenAI-style key"),
    (re.compile(r'AKIA[0-9A-Z]{16}'), "AWS access key"),
    (re.compile(r'ghp_[A-Za-z0-9]{36}'), "GitHub PAT"),
    (re.compile(r'-----BEGIN (RSA |EC )?PRIVATE KEY-----'), "Private key"),
]


def scan_secrets(code_file: str) -> list:
    """Find likely hardcoded secrets via regex patterns."""
    try:
        content = Path(code_file).read_text(encoding="utf-8")
    except Exception:
        return []

    findings = []
    for i, line in enumerate(content.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        for pattern, label in SECRET_PATTERNS:
            if pattern.search(line):
                findings.append({
                    "type": label,
                    "line_number": i,
                    "code": stripped[:120],
                })
    return findings


def generate_security_patch(state: dict, code_file: str, issues: list) -> str:
    """Ask the LLM to rewrite the code with all security issues fixed."""
    with open(code_file, "r", encoding="utf-8") as f:
        code = f.read()

    llm = ChatOllama(model="llama3.2:3b", temperature=0.3, num_ctx=2048)

    system_prompt = (
        "You are a Security Engineer with deep Python expertise.\n\n"
        "Your job: rewrite the code to fix EVERY security issue listed. Rules:\n"
        "1. Return ONLY the complete patched Python file — no markdown, no explanation.\n"
        "2. Preserve the original functionality exactly (tests must still pass).\n"
        "3. For hardcoded secrets: replace with os.environ.get('VAR_NAME').\n"
        "4. For subprocess with shell=True: use a list of args, no shell.\n"
        "5. For eval()/exec(): replace with safe alternatives (ast.literal_eval).\n"
        "6. For weak crypto: use hashlib.sha256 or stronger.\n"
        "7. Do NOT change public function signatures.\n"
        "8. Do NOT add an if __name__ == '__main__' block if the requirement forbids it."
    )

    user_prompt = (
        "ORIGINAL REQUIREMENT:\n"
        + state.get("requirement", "N/A")
        + "\n\nCURRENT CODE:\n```python\n"
        + code
        + "\n```\n\nSECURITY ISSUES TO FIX:\n"
        + json.dumps(issues, indent=2)
        + "\n\nReturn the complete patched Python file."
    )

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_prompt),
    ]

    response = llm.invoke(messages)
    patched = response.content

    if "```python" in patched:
        patched = patched.split("```python", 1)[1].split("```", 1)[0]
    elif "```" in patched:
        patched = patched.split("```", 1)[1].split("```", 1)[0]

    return patched.strip()