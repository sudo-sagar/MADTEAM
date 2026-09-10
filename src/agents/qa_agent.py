from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from src.tools.file_tools import read_file, run_pytest

def qa_agent(state: dict) -> dict:
    """QA Agent: Runs tests and validates code"""
    print("\n🔍 [QA] Running tests...")
    
    # Run the actual pytest
    test_result = run_pytest.invoke({"test_file": "workspace/tests/test_code.py"})
    
    # Check if code is production-ready
    if "ALL TESTS PASSED" in test_result:
        print("✅ QA: All tests passed! Code is production-ready.")
        return {**state, "test_results": test_result, "is_ready": True}
    else:
        print("❌ QA: Tests failed! Sending back to Coder with feedback...")
        return {
            **state,
            "test_results": test_result,
            "is_ready": False,
            "iteration": state.get("iteration", 0) + 1
        }
