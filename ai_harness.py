import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable


@dataclass
class HarnessConfig:
    base_url: str = "http://localhost:11434/v1"
    model: str = "llama3.2"
    api_key: str = ""
    timeout_seconds: int = 120
    max_tool_rounds: int = 4
    memory_file: str = ".ai-harness/session.json"


class HarnessError(RuntimeError):
    pass


class OpenAICompatibleProvider:
    def __init__(self, config: HarnessConfig) -> None:
        self.config = config

    def chat(self, messages: list[dict[str, str]]) -> str:
        url = self.config.base_url.rstrip("/") + "/chat/completions"
        body = json.dumps({
            "model": self.config.model,
            "messages": messages,
            "temperature": 0.2,
        }).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = "Bearer " + self.config.api_key

        request = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise HarnessError("Provider returned HTTP {}: {}".format(exc.code, detail)) from exc
        except urllib.error.URLError as exc:
            raise HarnessError("Could not reach provider at {}: {}".format(url, exc.reason)) from exc

        try:
            return payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise HarnessError("Provider returned an unexpected response: {!r}".format(payload)) from exc


@dataclass
class Tool:
    name: str
    description: str
    function: Callable[[dict[str, Any]], Any]
    parameters: dict[str, Any]


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def prompt_description(self) -> str:
        lines = []
        for tool in self._tools.values():
            lines.append("- {}: {} {}".format(
                tool.name,
                tool.description,
                json.dumps(tool.parameters, sort_keys=True),
            ))
        return "\n".join(lines)

    def execute(self, name: str, arguments: dict[str, Any]) -> Any:
        tool = self.get(name)
        if tool is None:
            raise HarnessError("Unknown tool: {}".format(name))
        return tool.function(arguments)


@dataclass
class SessionMemory:
    file_path: Path
    messages: list[dict[str, str]] = field(default_factory=list)

    def load(self) -> "SessionMemory":
        if not self.file_path.exists():
            return self
        try:
            data = json.loads(self.file_path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                self.messages = [item for item in data if isinstance(item, dict)]
        except (json.JSONDecodeError, OSError) as exc:
            raise HarnessError("Could not read memory {}: {}".format(self.file_path, exc)) from exc
        return self

    def add(self, role: str, content: str) -> None:
        self.messages.append({
            "role": role,
            "content": content,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    def save(self) -> None:
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.file_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.messages, indent=2), encoding="utf-8")
        temporary.replace(self.file_path)

    def chat_messages(self, limit: int = 40) -> list[dict[str, str]]:
        recent = self.messages[-limit:]
        return [
            {"role": item["role"], "content": item["content"]}
            for item in recent
            if item.get("role") in {"system", "user", "assistant"} and isinstance(item.get("content"), str)
        ]


def safe_calculate(arguments: dict[str, Any]) -> str:
    expression = arguments.get("expression")
    if not isinstance(expression, str) or len(expression) > 200:
        raise HarnessError("expression must be a string of at most 200 characters")

    allowed = set("0123456789+-*/(). %,")
    if any(character not in allowed for character in expression):
        raise HarnessError("expression contains unsupported characters")

    expression = expression.replace("%", "/100")
    try:
        result = eval(expression, {"__builtins__": {}}, {})
    except (SyntaxError, ArithmeticError, NameError, TypeError) as exc:
        raise HarnessError("Invalid expression") from exc
    if isinstance(result, (int, float)):
        return str(result)
    raise HarnessError("expression did not produce a number")


def get_current_time(_: dict[str, Any]) -> str:
    return datetime.now(timezone.utc).isoformat()


def build_tool_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(Tool(
        "calculate",
        "Evaluate a basic arithmetic expression.",
        safe_calculate,
        {"expression": "string"},
    ))
    registry.register(Tool(
        "get_time",
        "Get the current UTC date and time.",
        get_current_time,
        {},
    ))
    return registry


def tool_request(content: str) -> tuple[str, dict[str, Any]] | None:
    marker = "TOOL "
    stripped = content.strip()
    if not stripped.startswith(marker):
        return None
    try:
        payload = json.loads(stripped[len(marker):])
        name = payload["name"]
        arguments = payload.get("arguments", {})
        if not isinstance(name, str) or not isinstance(arguments, dict):
            return None
        return name, arguments
    except (json.JSONDecodeError, KeyError, TypeError):
        return None


class AIHarness:
    def __init__(
        self,
        config: HarnessConfig,
        provider: OpenAICompatibleProvider | None = None,
        memory: SessionMemory | None = None,
        tools: ToolRegistry | None = None,
    ) -> None:
        self.config = config
        self.provider = provider or OpenAICompatibleProvider(config)
        self.memory = (memory or SessionMemory(Path(config.memory_file))).load()
        self.tools = tools or build_tool_registry()

    def system_prompt(self) -> str:
        tools = self.tools.prompt_description()
        return (
            "You are a helpful AI assistant. "
            "Answer directly unless a tool is useful. "
            "To call a tool, respond with exactly "
            "'TOOL {\"name\":\"tool_name\",\"arguments\":{\"key\":\"value\"}}'. "
            "Use only the following tools:\n" + tools
        )

    def run(self, user_message: str) -> str:
        self.memory.add("user", user_message)
        messages = [{"role": "system", "content": self.system_prompt()}]
        messages.extend(self.memory.chat_messages())

        for _ in range(self.config.max_tool_rounds):
            response = self.provider.chat(messages)
            request = tool_request(response)
            if request is None:
                self.memory.add("assistant", response)
                self.memory.save()
                return response

            name, arguments = request
            try:
                result = self.tools.execute(name, arguments)
                tool_output = json.dumps(result) if not isinstance(result, str) else result
            except HarnessError as exc:
                tool_output = "Error: {}".format(exc)

            messages.append({"role": "assistant", "content": response})
            messages.append({
                "role": "user",
                "content": "TOOL_RESULT " + json.dumps({
                    "name": name,
                    "output": tool_output,
                }),
            })

        raise HarnessError("Tool loop exceeded max_tool_rounds")


def load_config(path: Path) -> HarnessConfig:
    if not path.exists():
        return HarnessConfig()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise HarnessError("Could not read config {}: {}".format(path, exc)) from exc
    return HarnessConfig(**{key: value for key, value in data.items() if hasattr(HarnessConfig(), key)})


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a provider-agnostic local AI harness.")
    parser.add_argument("--config", default="config.json", help="Path to JSON configuration.")
    parser.add_argument("--base-url", help="OpenAI-compatible API base URL.")
    parser.add_argument("--model", help="Model name.")
    parser.add_argument("--api-key", help="API key if required.")
    parser.add_argument("--memory-file", help="Session memory file.")
    parser.add_argument("--prompt", help="Send one prompt and exit.")
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        config = load_config(Path(args.config))
        if args.base_url:
            config.base_url = args.base_url
        if args.model:
            config.model = args.model
        if args.api_key:
            config.api_key = args.api_key
        if args.memory_file:
            config.memory_file = args.memory_file

        harness = AIHarness(config)
        if args.prompt:
            print(harness.run(args.prompt))
            return 0

        print("AI Harness ready. Model: {}. Memory: {}".format(config.model, config.memory_file))
        print("Type 'exit' or 'quit' to leave.")
        while True:
            try:
                message = input("> ")
            except EOFError:
                break
            if message.strip().lower() in {"exit", "quit"}:
                break
            if not message.strip():
                continue
            try:
                print(harness.run(message))
            except HarnessError as exc:
                print("Error: {}".format(exc), file=sys.stderr)
        return 0
    except HarnessError as exc:
        print("Error: {}".format(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
