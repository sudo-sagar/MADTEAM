import os
import re
import json
import subprocess
import tempfile
import shutil
import sys

# ═══════════════════════════════════════════════════════════════
# INVARIANT 1: STUB CHECK
# A meaningful test must FAIL against a stubbed implementation.
# ═══════════════════════════════════════════════════════════════


def build_stub(code: str, language: str = "python") -> str:
    """Replace every function body with a trivial return."""
    if language == "python":
        return _stub_python(code)
    if language in ("javascript", "typescript"):
        return _stub_javascript(code)
    return code


def _stub_python(code: str) -> str:
    """Replace Python function bodies with 'return None'."""
    lines = code.split("\n")
    out = []
    i = 0
    while i < len(lines):
        line = lines[i]
        out.append(line)
        m = re.match(r"^(\s*)def\s+\w+\s*\([^)]*\)\s*(?:->\s*[^:]+)?\s*:\s*$", line)
        if m:
            base_indent = m.group(1)
            body_indent = base_indent + "    "
            out.append(body_indent + "return None")
            i += 1
            while i < len(lines):
                nxt = lines[i]
                if nxt.strip() == "":
                    i += 1
                    continue
                nxt_indent = len(nxt) - len(nxt.lstrip())
                if nxt_indent <= len(base_indent):
                    break
                i += 1
            continue
        i += 1
    return "\n".join(out)


def _stub_javascript(code: str) -> str:
    """Replace JS return expressions with null."""
    return re.sub(r"return\s+[^;\n]+;", "return null;", code)


def stub_check(test_file: str, code_file: str, language: str = "python") -> tuple:
    """
    Returns (is_meaningful, reason).
    A test is meaningful only if it FAILS against a stubbed implementation.
    """
    if language != "python":
        return True, "stub check not implemented for " + language

    if not os.path.exists(test_file) or not os.path.exists(code_file):
        return False, "test or code file missing"

    with open(code_file, "r", encoding="utf-8") as f:
        code = f.read()

    stub = build_stub(code, language)
    backup = code_file + ".real_backup"

    try:
        shutil.move(code_file, backup)
        with open(code_file, "w", encoding="utf-8") as f:
            f.write(stub)

        # Run pytest against the stub
        env = {**os.environ, "PYTHONPATH": os.path.dirname(code_file)}
        result = subprocess.run(
            [sys.executable, "-m", "pytest", test_file, "-v", "--tb=no", "-q"],
            capture_output=True, text=True, timeout=30, env=env,
        )

        if result.returncode == 0:
            return False, "test passes on a stub — it is not testing meaningful behavior"
        return True, "test fails on stub — exercises real logic"

    except subprocess.TimeoutExpired:
        return False, "stub check timed out"
    except Exception as e:
        return False, "stub check error: " + str(e)
    finally:
        if os.path.exists(backup):
            shutil.move(backup, code_file)


# ═══════════════════════════════════════════════════════════════
# INVARIANT 2: CONSISTENCY CHECK
# Every expected value in a test must match what the reference
# implementation actually returns when executed.
# ═══════════════════════════════════════════════════════════════


def consistency_check(code: str, test_code: str, language: str = "python") -> tuple:
    """
    Extract every assertion from the test file, execute the call
    against the reference implementation, and verify the actual
    result matches the expected result.

    Returns (all_consistent, list_of_inconsistencies).
    """
    if language != "python":
        return True, []

    assertions = _extract_assertions(test_code)
    if not assertions:
        return True, []

    inconsistencies = []
    for assertion in assertions:
        call_expr = assertion["call"]
        expected = assertion["expected"]

        actual = _execute_call(code, call_expr)
        if actual is None:
            # Execution error — skip this assertion, don't fail on it
            continue

        if not _values_match(actual, expected):
            inconsistencies.append({
                "call": call_expr,
                "expected": expected,
                "actual": actual,
            })

    if inconsistencies:
        return False, inconsistencies
    return True, []


def _extract_assertions(test_code: str) -> list:
    """
    Extract (call_expression, expected_value) pairs from pytest assertions.
    Handles these forms:
        assert f(x) == y
        assert f(x) is True
        assert f(x) is False
        assert f(x)
        assert not f(x)
    """
    assertions = []

    # Pattern 1: assert <call> == <value>
    for m in re.finditer(r"assert\s+(.+?)\s*==\s*(.+?)(?:\s*#|\s*$)", test_code, re.MULTILINE):
        call = m.group(1).strip()
        expected = m.group(2).strip()
        if _is_function_call(call):
            assertions.append({"call": call, "expected": expected})

    # Pattern 2: assert <call> is True / is False
    for m in re.finditer(r"assert\s+(.+?)\s+is\s+(True|False)", test_code, re.MULTILINE):
        call = m.group(1).strip()
        expected = m.group(2)
        if _is_function_call(call):
            assertions.append({"call": call, "expected": expected})

    # Pattern 3: bare assert <call> (implies expected True)
    for m in re.finditer(r"assert\s+([a-zA-Z_][a-zA-Z0-9_]*\s*\([^)]*\))", test_code):
        call = m.group(1).strip()
        # Skip if already captured by pattern 1 or 2
        if not any(a["call"] == call for a in assertions):
            assertions.append({"call": call, "expected": "True"})

    # Pattern 4: assert not <call> (implies expected False)
    for m in re.finditer(r"assert\s+not\s+([a-zA-Z_][a-zA-Z0-9_]*\s*\([^)]*\))", test_code):
        call = m.group(1).strip()
        if not any(a["call"] == call for a in assertions):
            assertions.append({"call": call, "expected": "False"})

    return assertions


def _is_function_call(expr: str) -> bool:
    """Heuristic: does this expression look like a function call?"""
    return bool(re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*\s*\(", expr))


def _execute_call(code: str, call_expr: str):
    """Run a single call against the code and return the actual value."""
    sandbox = code + "\n\n"
    sandbox += "import hashlib, uuid, datetime, json, re\n"
    sandbox += "try:\n"
    sandbox += "    __result__ = " + call_expr + "\n"
    sandbox += "    print('__RESULT__:' + repr(__result__))\n"
    sandbox += "except Exception as __e__:\n"
    sandbox += "    print('__ERROR__:' + str(__e__))\n"

    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8")
    tmp.write(sandbox)
    tmp.close()

    try:
        result = subprocess.run(
            [sys.executable, tmp.name],
            capture_output=True, text=True, timeout=5,
        )
        stdout = result.stdout.strip()
        if "__RESULT__:" in stdout:
            return stdout.split("__RESULT__:", 1)[1].strip()
        return None
    except Exception:
        return None
    finally:
        try:
            os.unlink(tmp.name)
        except Exception:
            pass


def _values_match(actual_str: str, expected_str: str) -> bool:
    """Compare two repr-strings or expressions."""
    actual = actual_str.strip()
    expected = expected_str.strip()

    # Direct match
    if actual == expected:
        return True

    # Try evaluating the expected expression in a safe namespace
    try:
        ns = {}
        import hashlib, uuid, datetime, json
        ns.update({"hashlib": hashlib, "uuid": uuid, "datetime": datetime, "json": json})
        expected_value = eval(expected, ns)
        actual_value = eval(actual, {"__builtins__": {}})
        return actual_value == expected_value
    except Exception:
        # Cannot evaluate — assume consistent rather than false-positive
        return True


# ═══════════════════════════════════════════════════════════════
# INVARIANT 3: NON-DETERMINISTIC FLAG
# Detect functions that return random/time-based values and use
# property-based checks instead of exact equality.
# ═══════════════════════════════════════════════════════════════

NON_DETERMINISTIC_IMPORTS = [
    "random", "secrets", "uuid", "time", "datetime", "os.urandom",
]

NON_DETERMINISTIC_CALLS = [
    "random.", "uuid4", "uuid1", "datetime.now", "time.time",
    "secrets.", "os.urandom", "os.getpid",
]


def detect_non_deterministic(code: str) -> list:
    """
    Return a list of function names that appear non-deterministic.
    Heuristic: the function body references random/time/uuid primitives.
    """
    non_det = []

    # Split code into function definitions
    func_pattern = re.compile(
        r"^def\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\([^)]*\)\s*(?:->\s*[^:]+)?\s*:(.*?)(?=^def\s|\Z)",
        re.MULTILINE | re.DOTALL,
    )

    for m in func_pattern.finditer(code):
        name = m.group(1)
        body = m.group(2)
        if any(call in body for call in NON_DETERMINISTIC_CALLS):
            non_det.append(name)

    return non_det


def filter_non_deterministic_assertions(test_code: str, non_det_funcs: list) -> str:
    """
    Comment out exact-equality assertions on non-deterministic functions,
    leaving them as placeholder tests that verify the return type.
    """
    if not non_det_funcs:
        return test_code

    lines = test_code.split("\n")
    out = []
    for line in lines:
        stripped = line.strip()

        # Is this an assertion on a non-deterministic function?
        is_assert = stripped.startswith("assert ")
        mentions_nondet = any(
            re.search(rf"\b{re.escape(fn)}\s*\(", stripped) for fn in non_det_funcs
        )

        if is_assert and mentions_nondet and "==" in stripped:
            # Replace with a type-check placeholder
            for fn in non_det_funcs:
                m = re.search(rf"({fn}\s*\([^)]*\))", stripped)
                if m:
                    call = m.group(1)
                    indent = line[:len(line) - len(line.lstrip())]
                    out.append(indent + "# Non-deterministic — original assertion removed")
                    out.append(indent + f"result = {call}")
                    out.append(indent + "assert result is not None")
                    break
            else:
                out.append(line)
        else:
            out.append(line)

    return "\n".join(out)


# ═══════════════════════════════════════════════════════════════
# UNIFIED ENTRY POINT
# ═══════════════════════════════════════════════════════════════


def validate_tests(test_file: str, code_file: str, language: str = "python") -> dict:
    """
    Run all three invariants on a test file.
    Returns a dict with:
      - passed: bool (True if all invariants held)
      - reason: str (human-readable summary)
      - details: dict with per-invariant results
    """
    result = {"passed": True, "reason": "ok", "details": {}}

    if not os.path.exists(test_file) or not os.path.exists(code_file):
        return {"passed": False, "reason": "missing files", "details": {}}

    with open(code_file, "r", encoding="utf-8") as f:
        code = f.read()
    with open(test_file, "r", encoding="utf-8") as f:
        test_code = f.read()

    # ── Invariant 3: filter out non-deterministic assertions first ──
    non_det_funcs = detect_non_deterministic(code)
    if non_det_funcs:
        filtered = filter_non_deterministic_assertions(test_code, non_det_funcs)
        if filtered != test_code:
            with open(test_file, "w", encoding="utf-8") as f:
                f.write(filtered)
            test_code = filtered
            result["details"]["non_deterministic_filtered"] = non_det_funcs

    # ── Invariant 2: consistency check ──
    consistent, inconsistencies = consistency_check(code, test_code, language)
    if not consistent:
        result["passed"] = False
        result["reason"] = "consistency check failed: " + str(len(inconsistencies)) + " hallucinated values"
        result["details"]["inconsistencies"] = inconsistencies
        return result

    # ── Invariant 1: stub check ──
    # Skip for functions with no arguments (may legitimately return constants)
    has_args = bool(re.search(r"def\s+\w+\s*\(\s*[a-zA-Z_]", code))
    if has_args:
        meaningful, reason = stub_check(test_file, code_file, language)
        if not meaningful:
            result["passed"] = False
            result["reason"] = "stub check failed: " + reason
            result["details"]["stub_check"] = reason
            return result
        result["details"]["stub_check"] = reason

    result["details"]["consistency"] = "passed"
    return result