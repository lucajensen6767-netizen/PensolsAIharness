import json
import tempfile
import unittest
from pathlib import Path

from ai_harness import (
    HarnessConfig,
    HarnessError,
    AIHarness,
    SessionMemory,
    Tool,
    ToolRegistry,
    safe_calculate,
)


class FakeProvider:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def chat(self, messages):
        self.calls.append(messages)
        return next(self.responses)


class HarnessTests(unittest.TestCase):
    def test_calculator_rejects_unsafe_expression(self):
        with self.assertRaises(HarnessError):
            safe_calculate({"expression": "__import__('os').system('echo bad')"})

    def test_calculator_evaluates_expression(self):
        self.assertEqual(safe_calculate({"expression": "(4 + 2) * 3"}), "18")

    def test_tool_round_trip(self):
        provider = FakeProvider([
            'TOOL {"name":"calculate","arguments":{"expression":"6*7"}}',
            "The result is 42.",
        ])
        with tempfile.TemporaryDirectory() as directory:
            memory = SessionMemory(Path(directory) / "session.json")
            harness = AIHarness(HarnessConfig(), provider=provider, memory=memory)
            result = harness.run("What is 6 times 7?")

        self.assertEqual(result, "The result is 42.")
        self.assertEqual(len(provider.calls), 2)

    def test_direct_response_is_saved_to_memory(self):
        provider = FakeProvider(["Hello!"])
        with tempfile.TemporaryDirectory() as directory:
            memory = SessionMemory(Path(directory) / "session.json")
            harness = AIHarness(HarnessConfig(), provider=provider, memory=memory)
            harness.run("Hello")
            saved = json.loads((Path(directory) / "session.json").read_text(encoding="utf-8"))

        self.assertEqual(saved[-1]["role"], "assistant")
        self.assertEqual(saved[-1]["content"], "Hello!")

    def test_registry_rejects_unknown_tool(self):
        registry = ToolRegistry()
        with self.assertRaises(HarnessError):
            registry.execute("missing", {})


if __name__ == "__main__":
    unittest.main()
