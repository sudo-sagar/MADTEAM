import os
import re
import sys
import json
import subprocess
from langchain_ollama import ChatOllama
from langchain_core.messages import SystemMessage, HumanMessage
from src.agents.test_validation import validate_tests
from src.db import append_event


# ═══════════════════════════════════════════════════════════════
# CONSTRAINT DETECTION GATE
# ═══════════════════════════════════════════════════════════════

CONSTRAINT_KEYWORDS = [
    "do not", "don't", "must not", "mustn't", "never",
    "forbidden", "forbid", "avoid",
    "must use", "must have", "must be", "must contain",
    "required", "require", "only use",
    "no print", "no use", "without using",
]


def _requirement_has_constraints(requirement: str) -> bool:
    """Cheap gate: does the requirement contain any constraint keywords?"""
    req = requirement.lower()
    return any(kw in req for kw in CONSTRAINT_KEYWORDS)


# ═══════════════════════════════════════════════════════════════
# MAIN AGENT
# ═══════════════════════════════════════════════════════════════

def qa_agent(state: dict) -> dict:
    run_id = state.get("run_id", "unknown")
    print("\n[QA] Running tests...")

    test_file = "workspace/tests/test_code.py"
    code_file = state.get("code_file", "")
    requirement = state.get("requirement", "")

    # ─── Step 1: Run pytest ───
    passed, test_result = run_pytest_with_coverage(test_file)

    # ─── Step 2: Invariant checks (only if pytest passed) ───
    force_regenerate_tests = False
    if passed:
        try:
            from src.agents.test_validation import validate_tests
            validity = validate_tests(test_file, code_file, state.get("language", "python"))

            if not validity["passed"]:
                print("QA: " + validity["reason"])
                append_event(run_id, {
                    "agent": "qa",
                    "status": "warning",
                    "message": "Tests invalid: " + validity["reason"],
                })
                passed = False
                # Any invariant failure means the TESTS are broken, not the code.
                # Force regeneration on the next iteration.
                force_regenerate_tests = True
                test_result = "TESTS FAILED:\n" + validity["reason"]
                if "inconsistencies" in validity["details"]:
                    test_result += "\n\nHallucinated values detected:\n"
                    for inc in validity["details"]["inconsistencies"][:5]:
                        test_result += "  - call: " + inc["call"] + "\n"
                        test_result += "    expected: " + str(inc["expected"]) + "\n"
                        test_result += "    actual: " + str(inc["actual"]) + "\n"
                    test_result += "\nRegenerate the tests. Compute expected values inline. Never hardcode hashes."
            else:
                print("QA: All tests passed + all three invariants held")
        except Exception as e:
            import traceback
            print("QA: Invariant check crashed: " + str(e))
            traceback.print_exc()
            append_event(run_id, {
                "agent": "qa",
                "status": "warning",
                "message": "Invariant check crashed: " + str(e),
            })

    # ─── Step 3: Spec compliance (only if still passing) ───
    if passed and _requirement_has_constraints(requirement):
        spec_violations = check_spec_compliance(requirement, code_file)
        if spec_violations:
            passed = False
            test_result += "\n\nSPEC VIOLATIONS:\n" + "\n".join(
                "  - " + v for v in spec_violations
            )
    else:
        print("[QA] No explicit constraints detected — skipping spec check")

    # ─── Step 4: Success path ───
    if passed:
        print("QA: All tests passed!")
        static_analysis = analyze_code_quality(code_file)
        print("Static Analysis:\n" + static_analysis)

        return {
            **state,
            "test_results": "ALL TESTS PASSED",
            "is_ready": True,
            "messages": state.get("messages", []) + [{
                "role": "qa",
                "content": "All tests + invariants + spec checks passed",
            }],
        }

    # ─── Step 5: Failure path ───
    print("QA: Tests failed.")

    failing_tests = re.findall(r"(\S+::\S+)\s+FAILED", test_result)
    if not failing_tests:
        failing_tests = ["unknown"]
    stagnation_key = ",".join(sorted(failing_tests))
    prev_key = state.get("last_failure_key", "")
    same_failure = (stagnation_key == prev_key and stagnation_key != "unknown")

    print("[QA] Failing tests: " + str(failing_tests))
    print("[QA] Stagnant: " + str(same_failure))

    return {
          **state,
        "test_results": "TESTS FAILED:\n" + test_result,
        "is_ready": False,
        "iteration": state.get("iteration", 0) + 1,
        "regenerate_tests": force_regenerate_tests or same_failure,
        "last_failure_key": stagnation_key,
        "messages": state.get("messages", []) + [{
            "role": "qa",
            "content": "Tests failed (" + str(len(failing_tests)) + " tests)"
                       + (" [stagnant]" if same_failure else ""),
        }],
    }
def _qa_agent_impl(state: dict) -> dict:
    run_id = state.get("run_id", "unknown")
    print("\n[QA] Running tests...")

def analyze_code_quality(code_file: str) -> str:
    """Basic static analysis without external tools."""
    print("[QA] Running static analysis...")

    if not code_file or not os.path.exists(code_file):
        return "Code file not found"

    with open(code_file, "r", encoding="utf-8") as f:
        code = f.read()

    analysis = []

    if "def " in code and '"""' not in code and "'''" not in code:
        analysis.append("Missing docstrings in functions")

    funcs = re.findall(r"def \w+\([^)]*\)", code)
    typed = re.findall(r"def \w+\([^)]*:[^)]*\)\s*->", code)
    if funcs and len(typed) < len(funcs):
        analysis.append(f"Missing type hints on {len(funcs) - len(typed)} function(s)")

    if "try:" not in code and "isinstance" not in code and "if not " not in code:
        analysis.append("No defensive checks detected")

    if "import " not in code and "from " not in code:
        analysis.append("No imports found - may be incomplete")

    analysis.append(f"Code size: {len(code.splitlines())} lines")
    return "\n".join(analysis)

# ═══════════════════════════════════════════════════════════════
# PYTEST RUNNER
# ═══════════════════════════════════════════════════════════════

def run_pytest_with_coverage(test_file):
    """Run pytest and return (passed, output)."""
    if not os.path.exists(test_file):
        return False, "test file not found"

    env = {**os.environ, "PYTHONPATH": "workspace/code"}

    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", test_file, "-v", "--tb=short", "--no-header"],
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
        )
        if result.returncode == 0:
            return True, "ALL TESTS PASSED"
        output = (result.stdout + "\n" + result.stderr).strip()

        # ─── DEBUG ───
        print("=" * 60)
        print("RAW PYTEST OUTPUT:")
        print(output[:2000])
        print("=" * 60)

        if len(output) > 2000:
            output = "...(truncated)...\n" + output[-2000:]
        return False, output
    except subprocess.TimeoutExpired:
        return False, "Tests timed out after 30 seconds"
    except Exception as e:
        return False, f"Error running tests: {e}"
    # ─── Check that solution.py is importable (no top-level side effects) ───
    
    if passed:
        importable, import_err = _check_importable(code_file)
    if not importable:
        print("QA: solution.py is not importable — contains top-level code")
        print("   Error: " + import_err)
        passed = False
        test_result = (
            "TESTS FAILED:\n"
            "solution.py cannot be imported. It contains top-level executable code.\n"
            "REMOVE any asserts, prints, or demo code from the top level of solution.py.\n\n"
            "Import error:\n" + import_err
        )
        append_event(run_id, {
            "agent": "qa",
            "status": "warning",
            "message": "solution.py not importable — top-level code detected",
        })

# ═══════════════════════════════════════════════════════════════
# SPEC CONSTRAINT EXTRACTION
# ═══════════════════════════════════════════════════════════════

EXTRACTION_PROMPT = """You are a requirements analyst. Extract machine-checkable constraints from a coding requirement.

Output ONLY a JSON array. Each constraint is an object with:
- type: "forbid_pattern" | "require_pattern" | "forbid_import" | "require_import" | "require_call"
- pattern: (for *_pattern) a Python regex matching the code
- module: (for *_import) the module name
- name: (for require_call) the function/class name
- reason: human-readable explanation

Rules — READ CAREFULLY:
1. Only extract constraints EXPLICITLY stated in the requirement text.
2. Do NOT infer, assume, or add domain knowledge.
3. Domain knowledge is FORBIDDEN. Do NOT add "passwords must be 8 chars" unless
   the requirement literally says that. Do NOT add "must not use X" unless
   the requirement literally says that.
4. If the requirement only says "write a function that does Y", the correct
   output is [] — UNLESS it also states a prohibition or mandate.
5. Before emitting each constraint, ask: "Is the exact wording of this
   constraint present in the requirement?" If no, do NOT emit it.
6. A requirement's main verb ("write", "create", "implement") is NOT a constraint.
   Only prohibition ("do not X") or mandate ("must use Y") phrases are constraints.
Now extract constraints from this requirement:
"""


def extract_constraints(requirement: str) -> list:
    """Use LLM to extract machine-checkable constraints from a requirement."""
    llm = ChatOllama(model="llama3.2:3b", temperature=0.3, num_ctx=2048)

    messages = [
        SystemMessage(content=EXTRACTION_PROMPT),
        HumanMessage(content=requirement),
    ]

    response = llm.invoke(messages)
    raw = response.content.strip()

    if "```json" in raw:
        raw = raw.split("```json", 1)[1].split("```", 1)[0].strip()
    elif "```" in raw:
        raw = raw.split("```", 1)[1].split("```", 1)[0].strip()

    start = raw.find("[")
    end = raw.rfind("]")
    if start == -1 or end == -1:
        return []

    try:
        constraints = json.loads(raw[start:end + 1])
        if not isinstance(constraints, list):
            return []
        return constraints
    except json.JSONDecodeError:
        return []


def check_spec_compliance(requirement: str, code_file: str) -> list:
    """Check the code against constraints dynamically extracted from the requirement."""
    if not code_file or not os.path.exists(code_file):
        return ["code file missing"]

    with open(code_file, "r", encoding="utf-8") as f:
        code = f.read()

    constraints = extract_constraints(requirement)
    print(f"[QA] Extracted {len(constraints)} constraints: {constraints}")

    violations = []
    for c in constraints:
        ctype = c.get("type", "")
        reason = c.get("reason", "constraint violated")

        if ctype == "forbid_pattern":
            try:
                if re.search(c["pattern"], code, re.MULTILINE):
                    violations.append(reason)
            except re.error:
                pass

        elif ctype == "require_pattern":
            try:
                if not re.search(c["pattern"], code, re.MULTILINE):
                    violations.append(reason)
            except re.error:
                pass

        elif ctype == "forbid_import":
            module = c.get("module", "")
            if module and re.search(rf"^\s*(import|from)\s+{re.escape(module)}\b", code, re.MULTILINE):
                violations.append(reason)

        elif ctype == "require_import":
            module = c.get("module", "")
            if module and not re.search(rf"^\s*(import|from)\s+{re.escape(module)}\b", code, re.MULTILINE):
                violations.append(reason)

        elif ctype == "require_call":
            name = c.get("name", "")
            if name and not re.search(rf"\b{re.escape(name)}\s*\(", code):
                violations.append(reason)

    return violations

def _check_importable(code_file: str) -> tuple:
    """Return (is_importable, error_message)."""
    import subprocess as sp
    env = {**os.environ, "PYTHONPATH": os.path.dirname(code_file)}
    try:
        result = sp.run(
            [sys.executable, "-c", "import solution"],
            capture_output=True, text=True, timeout=10,
            cwd=os.path.dirname(code_file),
            env=env,
        )
        if result.returncode == 0:
            return True, ""
        err = (result.stdout + "\n" + result.stderr).strip()
        return False, err[-500:]
    except Exception as e:
        return False, str(e)

