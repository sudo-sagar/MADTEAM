import os
import subprocess
from langchain_core.tools import tool

@tool
def write_file(filepath: str, content: str) -> str:
    """Write code to a file. Creates directories if needed."""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)
    return f"✓ File written: {filepath}"

@tool
def run_pytest(test_file: str) -> str:
    """Run pytest on a test file and return real output."""
    try:
        result = subprocess.run(
            ["pytest", test_file, "-v"],
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.returncode == 0:
            return "✅ ALL TESTS PASSED"
        return f"❌ TESTS FAILED:\n{result.stdout}\n{result.stderr}"
    except Exception as e:
        return f"⚠️ Error running tests: {str(e)}"

@tool
def read_file(filepath: str) -> str:
    """Read contents of a file."""
    with open(filepath, 'r', encoding='utf-8') as f:
        return f.read()