#from langchain_openai import ChatOpenAI
import re
from langchain_ollama import ChatOllama
from langchain_core.messages import SystemMessage, HumanMessage
from src.tools.file_tools import write_file, read_file
from src.db import append_event
from typing import Any, Dict
import os
CODE_FILE = "workspace/code/solution.py"
TEST_FILE = "workspace/tests/test_code.py"


# ═══════════════════════════════════════════════════════════════
# STATIC SYSTEM PROMPTS
# These never change per requirement. They encode universal
# engineering rules that apply to every code generation task.
# ═══════════════════════════════════════════════════════════════


BEHAVIOR_EXTRACTION_PROMPT = """You are a requirements analyst.

Your job: list the concrete input/output behaviors of the function.

FORMAT — every line MUST follow this exact template:
N. Given <specific input>, <function>(<args>) returns <specific output>.

RULES:
1. Use REAL values, not placeholders. Write "secret" and "wrong", not "value" and "other".
2. Every line must include the function name and its actual arguments.
3. Every line must state the exact expected return value.
4. If the requirement says "return True if X, False otherwise", write exactly two lines:
   one where X is true, one where X is false.
5. Do NOT add any behaviors the requirement doesn't state.
   No nulls, no exceptions, no empty strings, unless the requirement literally says them.
6. Output ONLY the numbered list. No preamble, no explanation, no headers.
Now list behaviors for this requirement:"""


INITIAL_CODER_SYSTEM = """You are a Senior Software Engineer writing production Python code.

RULES (always apply):
1. Write clean, correct, well-documented Python.
2. Include docstrings, type hints, and defensive error handling.
3. Preserve EVERY explicit constraint from the requirement.
   - If the requirement forbids something, do NOT use it.
   - If the requirement mandates something, use it.
4. Do NOT add an if __name__ == '__main__' block unless asked.
5. Do NOT add top-level print() statements or demo code.
6. Return ONLY the Python code. No markdown fences. No explanation.
7. Do NOT add timing or performance code (time.time(), timeout checks,
   elapsed-time comparisons) unless the requirement literally asks for it.
8. Do NOT place test functions, print() demos, or `if __name__` blocks
   in the solution file. Tests belong in the test file only.
9. Do NOT raise exceptions unless the requirement explicitly allows them.
   A function that "returns True/False" never raises.
10. Do NOT import modules you do not use. Unused imports are a code smell.
11. The solution file must contain ONLY:
   - Import statements
   - Function definitions
   - Class definitions
   - Constant assignments (UPPER_CASE = value)
12. NEVER include at the top level of the solution file:
   - `assert` statements
   - `print()` statements  
   - Demo/example code
   - Any executable code outside a function
13. If the requirement needs to demonstrate usage, use a docstring example,
   NOT executable code.
14. The solution file must be importable without side effects.
    `python -c "from solution import check_password"` must run silently."""


FIX_CODER_SYSTEM = """You are a Senior Software Engineer performing surgical fixes on existing code.

RULES (always apply):
1. MODIFY the existing code. Do NOT rewrite it from scratch.
2. Start from CURRENT CODE and change ONLY what the failure reports require.
3. Preserve every working function, class, and import.
4. Apply every provided patch (test failures, visual, security, performance).
5. REMOVE any of the following if present (they are never required unless the
   requirement literally asks for them):
   - `if __name__ == '__main__'` blocks
   - Top-level `print()` statements or demo code
   - Timing code (`time.time()` comparisons, `timeout` checks)
   - Unused imports (including `time`, `os`, `sys` when unused)
   - Defensive `try/except` blocks that swallow exceptions silently
6. Do NOT add code that handles scenarios the requirement does not mention:
   - No timeout handling unless the requirement says "timeout"
   - No None checks unless the requirement says "None"
   - No type checks unless the requirement says "type"
7. Return ONLY the complete corrected Python file. No markdown fences.
8. Do NOT add timing or performance code (time.time(), timeout checks,
   elapsed-time comparisons) unless the requirement literally asks for it.
9. Do NOT place test functions, print() demos, or `if __name__` blocks
   in the solution file. Tests belong in the test file only.
10. Do NOT raise exceptions unless the requirement explicitly allows them.
   A function that "returns True/False" never raises.
11. Do NOT import modules you do not use. Unused imports are a code smell.
12. The solution file must contain ONLY:
   - Import statements
   - Function definitions
   - Class definitions
   - Constant assignments (UPPER_CASE = value)
13. NEVER include at the top level of the solution file:
   - `assert` statements
   - `print()` statements  
   - Demo/example code
   - Any executable code outside a function
14. If the requirement needs to demonstrate usage, use a docstring example,
   NOT executable code.
15. The solution file must be importable without side effects.
    `python -c "from solution import check_password"` must run silently."""


TEST_GENERATOR_SYSTEM = """You are a QA Engineer writing pytest tests for the provided code.

The tests must verify the CODE DOES WHAT THE REQUIREMENT ASKS — nothing more, nothing less.


CRITICAL: Any expected value in your tests MUST be computable inline.
- For hashes: use hashlib.md5(b"...").hexdigest() or hashlib.sha256(b"...").hexdigest()
- For UUIDs: use uuid.uuid4() or uuid.UUID(...) 
- For timestamps: use datetime.datetime.now() or datetime.datetime.fromisoformat(...)
- For random values: use random.seed(N) then random.random()
NEVER write a 32-character hex string, a UUID, or a timestamp as a literal.
If the QA validator detects a literal that doesn't match what the code returns,
your tests will be rejected and regenerated.


RULES (always apply):
1. Read the requirement carefully. List the behaviors it describes.
   Write exactly one test per described behavior. Do not invent extra tests.
2. Tests MUST pass if the code is correct. If they cannot pass, do not write them.
3. NEVER hardcode values you cannot compute yourself:
   - Hashes: compute inline with hashlib.
   - Dates/times: compute inline with datetime.
   - UUIDs: generate inline with uuid.
4. NEVER invent contracts the requirement does not state:
   - If the requirement does not say "raises TypeError", do NOT test for it.
   - If the requirement does not say "times out", do NOT test for it.
   - If the requirement does not say "validates length", do NOT test for it.
5. NEVER write two tests with the same input expecting different outcomes.
   If two tests use the same arguments, they must agree on the expected result.
6. Import from the code module: from solution import function_name.
7. Return ONLY the test code. No markdown fences. No explanation."""

def extract_behaviors(llm, requirement: str) -> str:
    #Extract required behaviors before writing tests.
    messages = [
        SystemMessage(content=BEHAVIOR_EXTRACTION_PROMPT),
        HumanMessage(content=requirement),
    ]
    return llm.invoke(messages).content.strip()
def _filter_behaviors(behaviors: str, requirement: str) -> str:
    """
    Reject behaviors that mention words NOT in the requirement.
    Returns filtered behaviors.
    """
    req_lower = requirement.lower()

    # Words that, if present in a behavior but NOT in the requirement, indicate invention
    forbidden_if_absent = ["none", "null", "empty", "exception", "raise",
                           "type", "typeerror", "valueerror", "timeout"]

    lines = behaviors.split("\n")
    kept = []
    dropped = []

    for line in lines:
        line_stripped = line.strip()
        if not line_stripped:
            continue
        # Keep the header
        if not line_stripped[0].isdigit():
            kept.append(line)
            continue

        line_lower = line_stripped.lower()
        invented = False
        for word in forbidden_if_absent:
            if word in line_lower and word not in req_lower:
                invented = True
                dropped.append(f"{line_stripped}  [invented: {word}]")
                break

        if not invented:
            kept.append(line)

    if dropped:
        print(f"[Coder] Dropped {len(dropped)} invented behaviors:")
        for d in dropped:
            print(f"    {d}")

    return "\n".join(kept)

# ═══════════════════════════════════════════════════════════════
# MAIN AGENT
# ═══════════════════════════════════════════════════════════════

def coder_agent(state: dict) -> dict:
    #Write code, apply fixes, and regenerate broken tests when needed.
    run_id = state.get("run_id", "unknown")

    # ---- Decide: initial write or self-correction? ----
    is_fix = bool(
        state.get("test_results", "").startswith("TESTS FAILED")
        or state.get("visual_analysis")
        or state.get("security_patch")
        or state.get("performance_patch")
    )

    if is_fix:
        print("[Coder] Self-correcting based on feedback...")
        append_event(run_id, {
            "agent": "coder",
            "status": "running",
            "message": "Applying fixes from prior failures",
        })
    else:
        print("\n[Coder] Writing initial code...")
        append_event(run_id, {
            "agent": "coder",
            "status": "running",
            "message": "Writing initial implementation",
        })

    # ---- Load existing code when fixing ----
    existing_code = ""
    if is_fix:
        try:
            with open(CODE_FILE, "r", encoding="utf-8") as f:
                existing_code = f.read()
        except Exception:
            existing_code = ""

    # ---- Build messages: STATIC system + DYNAMIC human ----
    llm = ChatOllama(model="llama3.2:3b", temperature=0.3, num_ctx=2048)

    if is_fix:
        messages = [
            SystemMessage(content=FIX_CODER_SYSTEM),
            HumanMessage(content=_build_fix_prompt(state, existing_code)),
        ]
    else:
        messages = [
            SystemMessage(content=INITIAL_CODER_SYSTEM),
            HumanMessage(content=_build_initial_prompt(state)),
        ]

    response = llm.invoke(messages)
    code_content = _strip_code_fences(response.content)

    # ---- Write code to disk ----
    os.makedirs(os.path.dirname(CODE_FILE), exist_ok=True)
    sanitized = _strip_toplevel_code(code_content)

    # Log how much we stripped
    if sanitized != code_content:
        print("[Coder] Stripped top-level executable code from solution.py")
    with open(CODE_FILE, "w", encoding="utf-8") as f:
        f.write(code_content)
    code_content = sanitized 
    # ---- Generate or regenerate tests ----
    iteration = state.get("iteration", 0)
    should_generate_tests = (
    (not is_fix)
    or state.get("regenerate_tests", False)
    or iteration == 3        # ← safety net: force regenerate on iteration 3
)

    if should_generate_tests:
        if state.get("regenerate_tests"):
            reason = "Regenerating broken test suite"
        else:
            reason = "Generating test suite"

        print(f"[Coder] {reason}...")
        append_event(run_id, {
            "agent": "coder",
            "status": "info",
            "message": reason,
        })

        test_code = _generate_tests(llm, state.get("requirement", ""), code_content)
        os.makedirs(os.path.dirname(TEST_FILE), exist_ok=True)
        with open(TEST_FILE, "w", encoding="utf-8") as f:
            f.write(test_code)

    # ---- Emit completion event ----
    append_event(run_id, {
        "agent": "coder",
        "status": "done",
        "message": "Code self-corrected" if is_fix else "Initial code written",
    })

    # ---- Return new state; clear consumed patches ----
    return {
        **state,
        "code_file": CODE_FILE,
        "regenerate_tests": False,
        "security_patch": "",
        "performance_patch": "",
        "visual_analysis": "",
        "messages": state.get("messages", []) + [{
            "role": "coder",
            "content": "Wrote " + CODE_FILE + (" (self-corrected)" if is_fix else ""),
        }],
    }


# ═══════════════════════════════════════════════════════════════
# DYNAMIC PROMPT BUILDERS
# These read from state. They change every iteration.
# ═══════════════════════════════════════════════════════════════

def _build_initial_prompt(state: dict) -> str:
    """HumanMessage for the initial code-writing call."""
    requirement = state.get("requirement", "")
    plan = state.get("task_plan", "(none provided)")
    return (
        "REQUIREMENT:\n"
        + requirement
        + "\n\nIMPLEMENTATION PLAN FROM PM:\n"
        + plan
        + "\n\nWrite the complete Python implementation in a single file."
    )


def _build_fix_prompt(state: dict, existing_code: str) -> str:
    """HumanMessage for the self-correction call."""
    parts = []
    parts.append("ORIGINAL REQUIREMENT:\n" + state.get("requirement", ""))
    parts.append("\nCURRENT CODE:\n" + existing_code)

    test_results = state.get("test_results", "")
    if test_results.startswith("TESTS FAILED"):
        parts.append("\nTEST FAILURES:\n" + test_results)

    visual_analysis = state.get("visual_analysis", "")
    if visual_analysis:
        parts.append("\nVISUAL REGRESSION ANALYSIS:\n" + visual_analysis)

    security_patch = state.get("security_patch", "")
    if security_patch:
        parts.append("\nSECURITY PATCH TO APPLY:\n" + security_patch)

    performance_patch = state.get("performance_patch", "")
    if performance_patch:
        parts.append("\nPERFORMANCE PATCH TO APPLY:\n" + performance_patch)

    if state.get("regenerate_tests"):
        parts.append(
            "\nNOTE: The previous test suite was broken and will be regenerated. "
            "Focus on making the code correct and clean. Do NOT add demo or main-block code."
        )

    parts.append("\nReturn the complete corrected Python file.")
    return "\n".join(parts)


def _strip_code_fences(text: str) -> str:
    """Remove markdown code fences from LLM output."""
    text = text.strip()
    if "```python" in text:
        return text.split("```python", 1)[1].split("```", 1)[0].strip()
    if "```" in text:
        return text.split("```", 1)[1].split("```", 1)[0].strip()
    return text

def _ensure_test_imports(test_code: str, code: str) -> str:
    """
    Guarantee the test file imports every public function from `solution`.
    """

    # Extract all public function names from the code
    func_names = re.findall(r"^def\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\(", code, re.MULTILINE)

    if not func_names:
        return test_code

    # Build the import statement
    import_line = "from solution import " + ", ".join(func_names)

    # If the import is already present, don't duplicate it
    for name in func_names:
        if re.search(rf"from solution import [^\n]*\b{re.escape(name)}\b", test_code):
            return test_code
        if re.search(rf"^import solution\b", test_code, re.MULTILINE):
            return test_code

    # Find the last import line, insert after it
    lines = test_code.split("\n")
    last_import_idx = -1
    for i, line in enumerate(lines):
        if re.match(r"\s*(import|from)\s+", line):
            last_import_idx = i

    if last_import_idx >= 0:
        lines.insert(last_import_idx + 1, import_line)
    else:
        lines.insert(0, import_line)

    return "\n".join(lines)

def _validate_tests(test_code: str, code: str) -> tuple[bool, str]:
    """Return (is_valid, reason)."""
    import re

    # Extract expected function names from the code
    func_names = re.findall(r"^def\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\(", code, re.MULTILINE)

    # Check 1: the test file must import at least one function
    for name in func_names:
        if f"import {name}" in test_code or f"import {name}," in test_code:
            break
    else:
        if "import solution" not in test_code:
            return False, "test file does not import the target function"

    # Check 2: the test file must not use .hexdigest() on a bool-returning function
    # (this catches the bug we saw where tests treat check_password as a hasher)
    if ".hexdigest()" in test_code:
        # Extract return type of target functions
        for name in func_names:
            if re.search(rf"def\s+{name}\s*\([^)]*\)\s*->\s*bool", code):
                # This function returns bool; tests must not call .hexdigest() on it
                if re.search(rf"{name}\s*\([^)]*\)\s*\.hexdigest", test_code):
                    return False, f"test calls .hexdigest() on {name}, which returns bool"

    # Check 3: the test file must reference the target function
    if func_names and not any(name in test_code for name in func_names):
        return False, "test file does not reference any target function"

    return True, "ok"

# ═══════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════

def _strip_test_redefinitions(test_code: str, names: list) -> str:
    """Remove any def/class from the test file that shadows an import from solution."""
    import re
    for name in names:
        pattern = rf"^def\s+{re.escape(name)}\s*\([^)]*\)\s*(?:->\s*[^:]+)?\s*:.*?(?=^def\s|^class\s|\Z)"
        test_code = re.sub(pattern, "", test_code, flags=re.MULTILINE | re.DOTALL)
        pattern = rf"^class\s+{re.escape(name)}\s*[\(:]?.*?(?=^def\s|^class\s|\Z)"
        test_code = re.sub(pattern, "", test_code, flags=re.MULTILINE | re.DOTALL)
    return test_code.strip()


def _generate_tests(llm, requirement: str, code: str) -> str:
    import re as _re

    behaviors = extract_behaviors(llm, requirement)
    behaviors = _filter_behaviors(behaviors, requirement)

    # ─── FIX 1: Cap behaviors at 4 to prevent model overload ───
    behavior_lines = [b for b in behaviors.split("\n") if b.strip()]
    if len(behavior_lines) > 4:
        behavior_lines = behavior_lines[:4]
        behaviors = "\n".join(behavior_lines)
        print(f"[Coder] Capped behaviors to 4")

    print(f"[Coder] Required behaviors:\n{behaviors}")

    # Extract all function/class names defined in the code
    func_names = _re.findall(r"^def\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\(", code, _re.MULTILINE)
    class_names = _re.findall(r"^class\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*[\(:]", code, _re.MULTILINE)
    all_names = func_names + class_names

    test_code = ""

    for attempt in range(2):
        messages = [
            SystemMessage(content=TEST_GENERATOR_SYSTEM),
            HumanMessage(content=(
                "REQUIREMENT:\n" + requirement
                + "\n\nREQUIRED BEHAVIORS (test ONLY these):\n" + behaviors
                + "\n\nCODE TO TEST:\n" + code
                + "\n\nWrite ONE pytest function per required behavior. "
                + "\n\nCRITICAL: The test file MUST start with an import line:"
                + "\n    from solution import " + ", ".join(all_names)
                + "\nDo NOT redefine any function or class in the test file. "
                + "Import it from solution."
            )),
        ]
        response = llm.invoke(messages)
        test_code = _strip_code_fences(response.content)

        # ─── FIX 2: Strip any redefinitions BEFORE fixing imports ───
        test_code = _strip_test_redefinitions(test_code, all_names)

        # Now fix imports
        test_code = _ensure_test_imports(test_code, code)

        valid, reason = _validate_tests(test_code, code)
        if valid:
            print(f"[Coder] Test suite accepted (attempt {attempt+1})")
            return test_code
        print(f"[Coder] Generated test rejected (attempt {attempt+1}): {reason}")

    # ─── FIX 3: Fallback — force-strip and force-import ───
    print("[Coder] Forcing import into rejected test file...")
    test_code = _strip_test_redefinitions(test_code, all_names)
    if all_names:
        import_line = "from solution import " + ", ".join(all_names)
        if import_line not in test_code:
            test_code = import_line + "\n" + test_code

    return test_code

def _strip_toplevel_code(code: str) -> str:
    """
    Remove top-level executable code from a Python file.
    Keeps imports, function defs, class defs, and constant assignments.
    Strips top-level asserts, print(), and any other statements.
    """
    import ast
    try:
        tree = ast.parse(code)
    except SyntaxError:
        # File has a syntax error — return as-is, let pytest report it
        return code

    # Rebuild the file, keeping only safe top-level nodes
    SAFE_NODES = (
        ast.Import,
        ast.ImportFrom,
        ast.FunctionDef,
        ast.AsyncFunctionDef,
        ast.ClassDef,
    )

    kept_nodes = []
    for node in tree.body:
        if isinstance(node, SAFE_NODES):
            kept_nodes.append(node)
        elif isinstance(node, ast.Assign):
            # Keep assignments only if the target is ALL-CAPS (a constant)
            targets = node.targets
            if all(
                isinstance(t, ast.Name) and t.id.isupper()
                for t in targets
            ):
                kept_nodes.append(node)
        elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            # Keep module docstring
            if isinstance(node.value.value, str):
                kept_nodes.append(node)
        # Everything else is stripped

    # Rebuild source
    new_tree = ast.Module(body=kept_nodes, type_ignores=[])
    ast.fix_missing_locations(new_tree)

    try:
        return ast.unparse(new_tree)
    except Exception:
        # Fallback to source segment if unparse fails
        return code    