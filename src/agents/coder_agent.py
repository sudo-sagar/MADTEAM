#from langchain_openai import ChatOpenAI
import re
from langchain_ollama import ChatOllama
from langchain_core.messages import SystemMessage, HumanMessage
from src.tools.file_tools import write_file, read_file

def coder_agent(state: dict) -> dict:
    """Coder Agent: Writes code and self-corrects based on QA feedback"""
    
    print("\n💻 [Coder] Writing code...")
    
    # Determine if this is a fix iteration or initial write
    is_fix = state.get("test_results") and "TESTS FAILED" in state.get("test_results", "")
    
    if is_fix:
        print("🔄 [Coder] Self-correcting based on QA feedback...")
        error_context = state.get("test_results", "")
        code_file = state.get("code_file", "")
        existing_code = read_file.invoke({"filepath": code_file}) if code_file else ""
    else:
        error_context = ""
        existing_code = ""
    
    #llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.3)
    llm = ChatOllama(model="llama3.2:3b", temperature=0)
    
    # Build the prompt
    if is_fix:
        messages = [
            SystemMessage(content="""You are a Senior Software Engineer. Write clean, production-ready Python code that follows best practices. Include docstrings and type hints.

            CRITICAL RULES:
            1. Follow the requirement EXACTLY. If it says "return False for invalid input",return False — do NOT raise exceptions.
            2. Never raise exceptions unless the requirement explicitly asks for it.
            3. Do NOT add `if __name__ == '__main__'` blocks or example usage.
            4. Write ONLY the function(s) the requirement asks for.
            5. No print statements unless the requirement asks for output."""),
            
            HumanMessage(content=f"""
            ORIGINAL REQUIREMENT: {state['requirement']}
            
            PLAN: {state['task_plan']}
            
            CURRENT CODE:
            {existing_code}
            
            TEST FAILURES:
            {error_context}
            
            Please fix the code to pass all tests. Return the complete corrected code.
            """)
        ]
    else:
        messages = [
            SystemMessage(content="""You are a Senior Software Engineer.
            Write clean, production-ready Python code that follows best practices.
            Include docstrings, type hints, and error handling.
            Write the complete implementation."""),
            
            HumanMessage(content=f"""
            REQUIREMENT: {state['requirement']}
            
            IMPLEMENTATION PLAN:
            {state['task_plan']}
            
            Write the complete Python implementation in a single file.
            Include all necessary imports and error handling.
            """)
        ]
    
    response = llm.invoke(messages)
    code_content = response.content
    
    # Extract code from markdown if present
    if "```python" in code_content:
        code_content = code_content.split("```python")[1].split("```")[0].strip()
    elif "```" in code_content:
        code_content = code_content.split("```")[1].split("```")[0].strip()
    
    # Write the file
    filepath = "workspace/code/solution.py"
    write_file.invoke({"filepath": filepath, "content": code_content})
    
    # Also generate tests if this is the first iteration
    if not is_fix:
        test_code = generate_tests(llm, state['requirement'], code_content)
        write_file.invoke({"filepath": "workspace/tests/test_code.py", "content": test_code})
    
    return {
        **state,
        "code_file": filepath,
        "messages": state.get("messages", []) + [{
            "role": "coder",
            "content": f"Wrote code to {filepath}" + (" (self-corrected)" if is_fix else "")
        }]
    }

def generate_tests(llm, requirement: str, code: str) -> str:
    """Generate comprehensive test suite"""
    print("🧪 [Coder] Generating tests...")
    
    messages = [
        SystemMessage(content="""You are a QA Engineer. Generate comprehensive pytest test cases that cover:
        - Happy path (valid emails return True)
        - Invalid emails return False (NOT exceptions)
        - Empty string returns False
        - None returns False
        - Non-string types return False
        - Boundary cases

        CRITICAL:
        - Tests must import from `solution` — NOT `your_module`.
        - Test contract: validate_email returns bool. Never expect exceptions.
        - Do NOT use `pytest.raises` for invalid input.
        - Return ONLY test code, no explanations.""")
        
        HumanMessage(content=f"""
        REQUIREMENT: {requirement}
        
        CODE TO TEST:
        {code}
        
        Generate complete pytest test file.
        """)
    ]
    
    response = llm.invoke(messages)
    test_code = response.content
    
    # Extract from markdown
    if "```python" in test_code:
        test_code = test_code.split("```python")[1].split("```")[0].strip()
    elif "```" in test_code:
        test_code = test_code.split("```")[1].split("```")[0].strip()

    # Remove any import lines the LLM snuck in — we replace them with the correct one.
    lines = test_code.splitlines()
    cleaned_lines = []
    for line in lines:
        stripped = line.strip()
        # Drop lines that try to import the function from a guessed module
        if re.match(r"^(from|import)\s+\S+", stripped) and "import" in stripped:
            # Keep stdlib imports the tests might legitimately need
            if any(
                keep in stripped
                for keep in ("import pytest", "import re", "import sys", "import os")
            ):
                cleaned_lines.append(line)
            else:
                continue
        else:
            cleaned_lines.append(line)
    test_code = "\n".join(cleaned_lines).strip()

    # Force the correct import header
    header = (
        "import sys, os\n"
        "sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'code'))\n"
        "from solution import validate_email\n\n"
    )

    return header + test_code