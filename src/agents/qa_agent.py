import subprocess
import ast
import sys
#from langchain_openai import ChatOpenAI
from langchain_ollama import ChatOllama
from langchain_core.messages import SystemMessage, HumanMessage
from src.tools.file_tools import read_file, write_file

def qa_agent(state: dict) -> dict:
    """Self-Healing QA Agent: Tests code and auto-generates fixes"""
    print("\n🔍 [QA] Running comprehensive validation...")
    
    test_file = "workspace/tests/test_code.py"
    code_file = state.get("code_file", "")
    
    # Run the actual tests
    test_result = run_pytest_with_coverage(test_file)
    
    if "ALL TESTS PASSED" in test_result:
        print("✅ QA: All tests passed! Code is production-ready.")
        
        # Bonus: Run static analysis
        static_analysis = analyze_code_quality(code_file)
        print(f"📊 Static Analysis Results:\n{static_analysis}")
        
        return {
            **state,
            "test_results": test_result,
            "is_ready": True,
            "messages": state.get("messages", []) + [{
                "role": "qa",
                "content": "✅ All tests passed + static analysis complete"
            }]
        }
    else:
        print("❌ QA: Tests failed! Generating self-healing fixes...")
        
        # 🔥 SELF-HEALING: Generate a fix suggestion
        suggested_fix = generate_fix_suggestion(state, test_result, code_file)
        
        # Update the code with the suggested fix
        if suggested_fix:
            print("🔧 [QA] Applying self-healing fix...")
            write_file.invoke({"filepath": code_file, "content": suggested_fix})
            
            # Re-test with the fix
            print("🔄 [QA] Re-testing with fix...")
            re_test_result = run_pytest_with_coverage(test_file)
            
            if "ALL TESTS PASSED" in re_test_result:
                print("✅ QA: Self-healing succeeded!")
                return {
                    **state,
                    "test_results": re_test_result,
                    "is_ready": True,
                    "messages": state.get("messages", []) + [{
                        "role": "qa",
                        "content": "✅ Self-healed code successfully"
                    }]
                }
        
        return {
            **state,
            "test_results": test_result,
            "is_ready": False,
            "iteration": state.get("iteration", 0) + 1
        }

def run_pytest_with_coverage(test_file: str) -> str:
    """Run pytest with coverage reporting"""
    try:
        # Run tests with verbose output
        result = subprocess.run(
            ["pytest", test_file, "-v", "--tb=short"],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode == 0:
            return "✅ ALL TESTS PASSED"
        else:
            # Extract the most useful error messages
            output = result.stdout + result.stderr
            # Truncate to keep it manageable
            if len(output) > 2000:
                output = output[:2000] + "... (truncated)"
            return f"❌ TESTS FAILED:\n{output}"
    except subprocess.TimeoutExpired:
        return "⚠️ Tests timed out after 30 seconds"
    except Exception as e:
        return f"⚠️ Error running tests: {str(e)}"

def generate_fix_suggestion(state: dict, test_result: str, code_file: str) -> str:
    """Use LLM to generate a fix for the failing tests"""
    print("🧠 [QA] Analyzing failures and suggesting fixes...")
    
    code_content = read_file.invoke({"filepath": code_file})
    
    #llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.2)
    llm = ChatOllama(model="llama3.2:3b", temperature=0)
    
    messages = [
        SystemMessage(content="""You are a Code Fixer AI.
        Your ONLY job is to fix the exact error reported in the test failures.
        Rules:
        1. Only fix what's broken - don't rewrite working code
        2. Add proper error handling and edge cases
        3. Return the complete file with your fix applied
        4. Include imports and all necessary code"""),
        
        HumanMessage(content=f"""
        CODE:
        {code_content}
        
        TEST FAILURES:
        {test_result}
        
        REQUIREMENT:
        {state['requirement']}
        
        Please provide the complete fixed code.
        """)
    ]
    
    response = llm.invoke(messages)
    fixed_code = response.content
    
    # Extract from markdown
    if "```python" in fixed_code:
        fixed_code = fixed_code.split("```python")[1].split("```")[0].strip()
    elif "```" in fixed_code:
        fixed_code = fixed_code.split("```")[1].split("```")[0].strip()
    
    return fixed_code

def analyze_code_quality(code_file: str) -> str:
    """Basic static analysis without external tools"""
    print("📊 [QA] Running static analysis...")
    
    code = read_file.invoke({"filepath": code_file})
    
    analysis = []
    
    # Check for docstrings
    if "def " in code and '"""' not in code and "'''" not in code:
        analysis.append("⚠️ Missing docstrings in functions")
    
    # Check for type hints
    if "def " in code and ": " not in code.split("def ")[1].split("(")[0]:
        analysis.append("⚠️ Missing type hints")
    
    # Check for error handling
    if "try" not in code and "except" not in code:
        analysis.append("⚠️ No error handling detected")
    
    # Check for imports
    if "import " not in code and "from " not in code:
        analysis.append("⚠️ No imports found - may be incomplete")
    
    # Count lines
    lines = len(code.split('\n'))
    analysis.append(f"📏 Code size: {lines} lines")
    
    return "\n".join(analysis) if analysis else "✅ No issues detected in static analysis"