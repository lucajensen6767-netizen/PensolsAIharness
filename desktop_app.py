import json
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

from ai_harness import AIHarness, HarnessConfig, HarnessError, load_config


APP_NAME = "AI Harness"
APP_DIRECTORY = Path.home() / "AppData" / "Local" / "AIHarness"


class AIHarnessDesktop:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title(APP_NAME)
        self.root.geometry("820x620")
        self.root.minsize(620, 460)

        APP_DIRECTORY.mkdir(parents=True, exist_ok=True)
        self.config_path = APP_DIRECTORY / "config.json"
        self.config = load_config(self.config_path) if self.config_path.exists() else HarnessConfig()
        self.config.memory_file = str(APP_DIRECTORY / "session.json")
        self.harness = AIHarness(self.config)
        self.busy = False

        self._build_ui()
        self._load_settings()
        self._load_history()

    def _build_ui(self) -> None:
        style = ttk.Style()
        if "vista" in style.theme_names():
            style.theme_use("vista")

        notebook = ttk.Notebook(self.root)
        notebook.pack(fill="both", expand=True, padx=12, pady=12)

        chat_frame = ttk.Frame(notebook, padding=8)
        settings_frame = ttk.Frame(notebook, padding=12)
        notebook.add(chat_frame, text="Chat")
        notebook.add(settings_frame, text="Settings")

        self.chat_output = scrolledtext.ScrolledText(
            chat_frame,
            wrap="word",
            state="disabled",
            font=("Segoe UI", 10),
        )
        self.chat_output.pack(fill="both", expand=True)

        input_frame = ttk.Frame(chat_frame)
        input_frame.pack(fill="x", pady=(8, 0))
        self.message_input = tk.Text(input_frame, height=3, wrap="word", font=("Segoe UI", 10))
        self.message_input.pack(side="left", fill="x", expand=True)
        self.message_input.bind("<Control-Return>", lambda _: self.send_message())

        self.send_button = ttk.Button(input_frame, text="Send", command=self.send_message, width=12)
        self.send_button.pack(side="right", padx=(8, 0), ipady=10)

        ttk.Label(
            settings_frame,
            text="OpenAI-compatible provider",
            font=("Segoe UI", 12, "bold"),
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 12))

        fields = [
            ("Base URL", "base_url", 1),
            ("Model", "model", 2),
            ("API Key", "api_key", 3),
            ("Timeout (seconds)", "timeout_seconds", 4),
        ]
        self.setting_vars: dict[str, tk.StringVar] = {}
        for label, key, row in fields:
            ttk.Label(settings_frame, text=label).grid(row=row, column=0, sticky="w", pady=5)
            variable = tk.StringVar()
            self.setting_vars[key] = variable
            widget = ttk.Entry(
                settings_frame,
                textvariable=variable,
                width=60,
                show="*" if key == "api_key" else None,
            )
            widget.grid(row=row, column=1, sticky="ew", padx=(12, 0), pady=5)

        settings_frame.columnconfigure(1, weight=1)

        actions = ttk.Frame(settings_frame)
        actions.grid(row=5, column=0, columnspan=2, sticky="w", pady=(18, 0))
        ttk.Button(actions, text="Save settings", command=self.save_settings).pack(side="left")
        ttk.Button(actions, text="Clear conversation", command=self.clear_conversation).pack(
            side="left", padx=(8, 0)
        )
        ttk.Button(actions, text="Export conversation", command=self.export_conversation).pack(
            side="left", padx=(8, 0)
        )

        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(self.root, textvariable=self.status_var, anchor="w").pack(
            fill="x", padx=14, pady=(0, 8)
        )

    def _load_settings(self) -> None:
        self.setting_vars["base_url"].set(self.config.base_url)
        self.setting_vars["model"].set(self.config.model)
        self.setting_vars["api_key"].set(self.config.api_key)
        self.setting_vars["timeout_seconds"].set(str(self.config.timeout_seconds))

    def _append_chat(self, role: str, text: str) -> None:
        self.chat_output.configure(state="normal")
        if self.chat_output.index("end-1c") != "1.0":
            self.chat_output.insert("end", "\n\n")
        self.chat_output.insert("end", "{}:\n{}".format(role, text))
        self.chat_output.configure(state="disabled")
        self.chat_output.see("end")

    def _load_history(self) -> None:
        for message in self.harness.memory.messages:
            role = message.get("role")
            content = message.get("content")
            if role in {"user", "assistant"} and isinstance(content, str):
                self._append_chat("You" if role == "user" else "Assistant", content)

    def send_message(self) -> None:
        if self.busy:
            return
        message = self.message_input.get("1.0", "end").strip()
        if not message:
            return

        self.message_input.delete("1.0", "end")
        self._append_chat("You", message)
        self.busy = True
        self.send_button.configure(state="disabled")
        self.status_var.set("Thinking...")

        thread = threading.Thread(target=self._send_in_background, args=(message,), daemon=True)
        thread.start()

    def _send_in_background(self, message: str) -> None:
        try:
            response = self.harness.run(message)
        except (HarnessError, OSError) as exc:
            self.root.after(0, lambda: self._show_error(str(exc)))
        except Exception as exc:
            self.root.after(0, lambda: self._show_error("Unexpected error: {}".format(exc)))
        else:
            self.root.after(0, lambda: self._show_response(response))

    def _show_response(self, response: str) -> None:
        self._append_chat("Assistant", response)
        self._finish_request("Ready")

    def _show_error(self, message: str) -> None:
        self.status_var.set("Error")
        messagebox.showerror(APP_NAME, message)
        self._finish_request("Ready")

    def _finish_request(self, status: str) -> None:
        self.busy = False
        self.send_button.configure(state="normal")
        self.status_var.set(status)

    def save_settings(self) -> None:
        try:
            timeout = int(self.setting_vars["timeout_seconds"].get())
            if timeout <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror(APP_NAME, "Timeout must be a positive whole number.")
            return

        self.config.base_url = self.setting_vars["base_url"].get().strip()
        self.config.model = self.setting_vars["model"].get().strip()
        self.config.api_key = self.setting_vars["api_key"].get().strip()
        self.config.timeout_seconds = timeout
        self.config.memory_file = str(APP_DIRECTORY / "session.json")

        data = {
            "base_url": self.config.base_url,
            "model": self.config.model,
            "api_key": self.config.api_key,
            "timeout_seconds": self.config.timeout_seconds,
            "max_tool_rounds": self.config.max_tool_rounds,
            "memory_file": self.config.memory_file,
        }
        self.config_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        self.harness = AIHarness(self.config)
        self.status_var.set("Settings saved")
        messagebox.showinfo(APP_NAME, "Settings saved.")

    def clear_conversation(self) -> None:
        if not messagebox.askyesno(APP_NAME, "Clear this conversation?"):
            return
        self.harness.memory.messages.clear()
        self.harness.memory.save()
        self.chat_output.configure(state="normal")
        self.chat_output.delete("1.0", "end")
        self.chat_output.configure(state="disabled")
        self.status_var.set("Conversation cleared")

    def export_conversation(self) -> None:
        destination = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON conversation", "*.json"), ("Text file", "*.txt"), ("All files", "*.*")],
            initialfile="ai-harness-conversation.json",
        )
        if not destination:
            return
        path = Path(destination)
        if path.suffix.lower() == ".txt":
            lines = []
            for message in self.harness.memory.messages:
                role = "You" if message.get("role") == "user" else "Assistant"
                lines.append("{}:\n{}".format(role, message.get("content", "")))
            path.write_text("\n\n".join(lines), encoding="utf-8")
        else:
            path.write_text(json.dumps(self.harness.memory.messages, indent=2), encoding="utf-8")
        self.status_var.set("Conversation exported")
        messagebox.showinfo(APP_NAME, "Conversation exported.")


def main() -> None:
    root = tk.Tk()
    AIHarnessDesktop(root)
    root.mainloop()


if __name__ == "__main__":
    main()
