# AI Harness

A small, dependency-free Python harness for provider-agnostic LLM chat, tool calls, and persistent session memory.

## Run locally

Start Ollama and pull a model:

```powershell
ollama pull llama3.2
ollama serve
```

Then run:

```powershell
python ai_harness.py
```

Use a single prompt:

```powershell
python ai_harness.py --prompt "What is 15 percent of 240?"
```

Any OpenAI-compatible endpoint can be configured in `config.json` or on the command line:

```powershell
python ai_harness.py --base-url "https://your-provider.example/v1" --model "model-name" --api-key "your-key"
```

## Built-in tools

- `calculate`: basic arithmetic
- `get_time`: current UTC date and time

Tools are invoked by returning an exact JSON tool request. The harness executes the tool and sends the result back to the model.

## Memory

Conversation history is persisted to `.ai-harness/session.json` by default. Delete that file to start a fresh session.

## Tests

```powershell
python -m unittest -v test_ai_harness.py
```

## Desktop app

Run the desktop interface directly:

```powershell
python desktop_app.py
```

Build a downloadable Windows package:

```powershell
.\build_desktop.ps1
```

The build script creates:

- `dist\AI Harness Desktop\AI Harness.exe`
- `dist\AI-Harness-Windows.zip`

Desktop settings and conversation history are stored under:

```text
%LOCALAPPDATA%\AIHarness
```

## Share on GitHub

The repository excludes generated executables and local session data. Publish source changes normally, then create a version tag to trigger a Windows build:

```powershell
git add .
git commit -m "Prepare desktop release"
git tag v1.0.0
git push origin main
git push origin v1.0.0
```

The Windows release workflow tests the Python code, builds `AI-Harness-Windows.zip`, and attaches the ZIP and standalone executable to the GitHub Release for that tag.
