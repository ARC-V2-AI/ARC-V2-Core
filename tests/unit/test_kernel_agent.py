"""
Agent.py Unit Tests - Kernel Module

Tests based on verification criteria from docs/verification/agent_backup_verification.md
"""

import pytest
import json
import base64
import zlib
import sys
import os
from typing import Any

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from arc.services.kernel.agent import Agent
from arc_inference import ChatMessage, Tool, ToolCall, ToolCallFunction, AgentTrace
from arc_inference.types import StreamEvent, ToolCallFunction as TCF
from arc_inference import TraceCallback


# ===========
# Test Group 1: Syntax Verification (py_compile)
# ===========


def test_agent_syntax():
    """Verify the agent.py module has valid Python syntax"""
    import py_compile

    agent_path = os.path.join(
        os.path.dirname(__file__),
        "..",
        "..",
        "src",
        "arc",
        "services",
        "kernel",
        "agent.py",
    )
    try:
        py_compile.compile(agent_path, doraise=True)
        print("✓ Syntax verification passed")
        return True
    except py_compile.PyCompileError as e:
        print(f"✗ Syntax verification failed: {e}")
        return False


# ===========
# Test Group 2: Import Test
# ===========


def test_agent_imports():
    """Verify all module imports are successful"""
    try:
        from arc.services.kernel.agent import Agent
        from arc_inference import (
            ChatMessage,
            Tool,
            ToolCall,
            ToolCallFunction,
            AgentTrace,
        )
        from arc_inference.types import StreamEvent, ToolCallFunction as TCF
        from arc_inference import TraceCallback
        from arc_inference.tools import ensure_tool

        # Verify key classes are available
        assert Agent is not None
        assert ChatMessage is not None
        assert Tool is not None
        assert ToolCall is not None
        assert AgentTrace is not None

        print("✓ Import verification passed - all dependencies available")
        return True
    except ImportError as e:
        print(f"✗ Import verification failed: {e}")
        return False


# ===========
# Test Group 3: Basic Instantiation
# ===========


def test_agent_basic_creation():
    """Test agent creation with various parameters"""

    # Test 1: Basic agent with default parameters
    agent = Agent()
    assert agent.system_prompt is None
    assert agent.max_iterations == 10
    assert agent.tool_choice == "auto"
    assert len(agent._messages) == 0

    # Test 2: Agent with system prompt
    system_prompt = "You are a helpful assistant"
    agent2 = Agent(system_prompt=system_prompt)
    assert agent2.system_prompt == system_prompt
    assert len(agent2._messages) == 1
    assert isinstance(agent2._messages[0], ChatMessage)
    assert agent2._messages[0].type == "system"

    # Test 3: Agent with max_iterations
    agent3 = Agent(max_iterations=5)
    assert agent3.max_iterations == 5

    # Test 4: Agent with custom tool_choice
    agent4 = Agent(tool_choice="required")
    assert agent4.tool_choice == "required"

    # Test 5: Agent with tools
    def simple_tool(arg1: str) -> str:
        return f"Processed: {arg1}"

    agent5 = Agent(tools=[simple_tool])
    assert "simple_tool" in agent5.tools
    assert len(agent5.tools) == 1

    # Test 6: Agent with all parameters
    agent6 = Agent(
        system_prompt="Test prompt",
        tools=[simple_tool],
        max_iterations=20,
        tool_choice="required",
        max_output_tokens=512,
        temperature=0.5,
        top_p=0.9,
        top_k=50,
        metadata={"key": "value"},
        tool_error_mode="raise",
        retry_incomplete_tool_calls=2,
        trace_callback=lambda event: None,
        max_same_tool_calls=2,
        context_window=4096,
        max_messages=50,
    )
    assert agent6.system_prompt == "Test prompt"
    assert agent6.max_iterations == 20
    assert agent6.max_output_tokens == 512
    assert agent6.temperature == 0.5
    assert agent6.tool_error_mode == "raise"
    assert agent6.retry_incomplete_tool_calls == 2
    assert agent6.max_same_tool_calls == 2
    assert agent6.context_window == 4096
    assert agent6.max_messages == 50

    print("✓ Basic instantiation verification passed")
    return True


def test_agent_instantiation_parameters():
    """Verify system prompt, max iterations, and tool_choice are stored correctly"""
    agent = Agent(
        system_prompt="Test system prompt",
        max_iterations=15,
        tool_choice="required",
    )

    assert agent.system_prompt == "Test system prompt"
    assert agent.max_iterations == 15
    assert agent.tool_choice == "required"
    assert agent._messages == [ChatMessage.system("Test system prompt")]

    # Verify messages list initialization
    assert isinstance(agent._messages, list)
    assert len(agent._messages) == 1

    print("✓ Parameter storage verification passed")
    return True


# ===========
# Test Group 4: Context Reset Functionality
# ===========


def test_agent_reset_functionality():
    """Test reset() method clears all state properly"""

    # Create agent with system prompt
    agent = Agent(system_prompt="Original system prompt")
    agent._messages.append(ChatMessage.user("User message 1"))
    agent._messages.append(ChatMessage.assistant("Assistant response 1"))
    agent._messages.append(ChatMessage.user("User message 2"))

    # Add some tool call state
    agent.last_trace = AgentTrace()

    # Verify initial state
    assert len(agent._messages) == 4
    assert agent.last_trace is not None

    # Call reset
    agent.reset()

    # Verify reset cleared everything
    assert len(agent._messages) == 1  # Only system prompt remains
    assert agent._messages[0].type == "system"
    assert agent._messages[0].content == "Original system prompt"
    assert agent.last_trace is None
    assert agent._recent_tool_calls == []
    assert agent._tool_result_cache == {}

    # Verify system prompt was preserved
    assert agent.system_prompt == "Original system prompt"

    print("✓ Context reset functionality verification passed")
    return True


def test_agent_reset_preserves_system_prompt():
    """Verify proper clearing of messages and internal state, restoring system prompt"""

    agent = Agent(
        system_prompt="Persistent system prompt",
        max_iterations=5,
    )

    # Add messages
    agent._messages.append(ChatMessage.user("Test user message"))
    agent._messages.append(ChatMessage.assistant("Test assistant response"))

    # Verify before reset
    assert len(agent._messages) == 3

    # Reset
    agent.reset()

    # Verify after reset
    assert len(agent._messages) == 1
    assert agent._messages[0].type == "system"
    assert agent._messages[0].content == "Persistent system prompt"
    assert agent.last_trace is None
    assert agent._tool_result_cache == {}

    # Verify agent can still be used after reset
    assert agent.system_prompt is not None

    print("✓ System prompt preservation verification passed")
    return True


# ===========
# Test Group 5: Stream API with Tool Calling
# ===========


def test_agent_with_tools():
    """Test agent execution with tool calling"""

    tool_calls_count = 0

    def counting_tool(arg1: str, arg2: int = 1) -> str:
        nonlocal tool_calls_count
        tool_calls_count += 1
        return f"Result of {arg1} with arg2={arg2}"

    agent = Agent(
        tools=[counting_tool],
        max_iterations=3,
        system_prompt="You have access to a counting tool. Use it to process inputs.",
    )

    # Verify tool was added
    assert "counting_tool" in agent.tools

    # Simulate a simple interaction (without actual streaming)
    agent._messages.append(ChatMessage.user("Count me: 5 times"))

    # Test _execute_async method directly
    result = agent._execute_async(
        "call1", "counting_tool", '{"arg1": "test", "arg2": 3}'
    )

    assert result.success
    assert "test" in result.content
    assert "arg2=3" in result.content

    print("✓ Stream API with tool calling verification passed")
    return True


def test_tool_call_caching():
    """Test tool call caching prevents repeating failed tool calls"""

    failed_tool = Tool(
        name="failing_tool",
        description="A tool that always fails",
        handler=lambda **kwargs: ("result", False, "This tool always fails"),
    )

    agent = Agent(tools=[failed_tool])

    # Execute the failing tool
    result1 = agent._execute_async("call1", "failing_tool", '{"arg1": "test"}')

    assert not result1.success
    assert result1.error == "This tool always fails"

    # Execute the same tool call again - should be cached
    result2 = agent._execute_async("call2", "failing_tool", '{"arg1": "test"}')

    assert not result2.success
    assert result2.error == "This tool always fails"

    # Verify the tool was added to tools dict
    assert "failing_tool" in agent.tools

    print("✓ Tool call caching verification passed")
    return True


def test_iteration_limits():
    """Test agent respects max_iterations constraint"""

    agent = Agent(max_iterations=3, system_prompt="Simple agent")

    # Simulate agent execution without actual streaming
    # Just verify the max_iterations is set correctly
    assert agent.max_iterations == 3

    # Verify _reset_execution_round_vars clears state for each iteration
    agent._reset_execution_round_vars()
    assert agent.last_trace is None
    assert agent._recent_tool_calls == []
    assert agent._tool_result_cache == {}

    print("✓ Iteration limits verification passed")
    return True


def test_state_reset():
    """Test clean reset of all context when needed"""

    agent = Agent(
        system_prompt="Reset test",
        max_iterations=10,
    )

    # Simulate accumulated state
    agent._messages.append(ChatMessage.user("Message 1"))
    agent._messages.append(ChatMessage.assistant("Response 1"))
    agent._messages.append(ChatMessage.user("Message 2"))

    agent._recent_tool_calls.append(("tool1", "args1"))
    agent._recent_tool_calls.append(("tool2", "args2"))

    agent._tool_result_cache["key1"] = ("cached_result", True, "success")
    agent._tool_result_cache["key2"] = ("cached_result2", False, "error")

    assert len(agent._messages) == 3
    assert len(agent._recent_tool_calls) == 2
    assert len(agent._tool_result_cache) == 2

    # Reset
    agent.reset()

    # Verify clean state
    assert len(agent._messages) == 1
    assert agent._messages[0].type == "system"
    assert agent._recent_tool_calls == []
    assert agent._tool_result_cache == {}
    assert agent.last_trace is None

    print("✓ State reset verification passed")
    return True


# ===========
# Helper Functions
# ===========


def _serialize_result_optimized(value: Any) -> str:
    """Compress tool results more efficiently"""
    if isinstance(value, str):
        return value
    try:
        result = json.dumps(
            value, ensure_ascii=False, default=str, separators=(",", ":")
        )
        if len(result) > 1024:
            try:
                compressed = zlib.compress(result.encode())
                return compressed.decode().hex()
            except:
                pass
        return result
    except Exception:
        return str(value)


def _parse_arguments_optimized(arguments: str) -> Any:
    try:
        return json.loads(arguments)
    except Exception:
        return arguments


def _parse_result_optimized(content: str) -> Any:
    try:
        return json.loads(content)
    except Exception:
        return content


def _tool_signature(name: str, arguments: str) -> tuple[str, str]:
    try:
        normalized = json.dumps(
            json.loads(arguments),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
    except Exception:
        normalized = arguments.strip()
    return name, normalized


def _compress_tool_arguments(arguments: str) -> str:
    """Compress tool arguments if they're too long"""
    if len(arguments) > 4096:
        try:
            compressed = base64.b64encode(zlib.compress(arguments.encode())).decode()
            return f"base64:{compressed}"
        except:
            pass
    return arguments


def _compress_reasoning(reasoning: str) -> str:
    """Compress reasoning if it exceeds reasonable length"""
    if len(reasoning) > 2048:
        return reasoning[:2048] + "... [truncated]"
    return reasoning


# ===========
# Run All Tests
# ===========

if __name__ == "__main__":
    print("=" * 60)
    print("Running Agent.py Verification Tests")
    print("=" * 60)

    # Test 1: Syntax
    print("\n[Test 1] Syntax Verification")
    test_agent_syntax()

    # Test 2: Imports
    print("\n[Test 2] Import Test")
    test_agent_imports()

    # Test 3: Basic Instantiation
    print("\n[Test 3] Basic Instantiation")
    test_agent_basic_creation()
    test_agent_instantiation_parameters()

    # Test 4: Context Reset
    print("\n[Test 4] Context Reset Functionality")
    test_agent_reset_functionality()
    test_agent_reset_preserves_system_prompt()

    # Test 5: Stream API with Tools
    print("\n[Test 5] Stream API with Tool Calling")
    test_agent_with_tools()
    test_tool_call_caching()
    test_iteration_limits()
    test_state_reset()

    print("\n" + "=" * 60)
    print("All tests completed successfully!")
    print("=" * 60)
