"""Run a tool-calling model in a simulated WorldFoundry support desk."""
import argparse
import json
import os
from pathlib import Path

from openai import APIError, DefaultHttpxClient, OpenAI

from worldfoundry import Episode, WorldFoundry

PROVIDERS = {
    "openai": ("https://api.openai.com/v1/", "OPENAI_API_KEY"),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai/", "GEMINI_API_KEY"),
    "claude": ("https://api.anthropic.com/v1/", "ANTHROPIC_API_KEY"),
    "ollama": ("http://localhost:11434/v1/", None),
}
DATA_DIR = Path(".wf-data")


def run_agent(client: OpenAI, model: str, wf: WorldFoundry, episode: Episode) -> None:
    support_desk = next(env for env in wf.environment_catalog() if env["id"] == "support-desk")
    tools = [
        {
            "type": "function",
            "function": {
                "name": action["name"],
                "description": action["description"],
                "parameters": {
                    "type": "object",
                    "properties": action["parameters"],
                    "required": action["required"],
                    "additionalProperties": False,
                },
            },
        }
        for action in support_desk["actions"]
    ]
    messages = [
        {
            "role": "system",
            "content": (
                "Complete the task by calling the simulated ticket tools. "
                "Use one tool at a time and give a short final answer when done."
            ),
        },
        {"role": "user", "content": episode.instruction},
    ]

    for _ in range(8):
        response = client.chat.completions.create(model=model, messages=messages, tools=tools)
        if not response.choices:
            raise ValueError("The provider returned no model response.")
        message = response.choices[0].message
        if not message.tool_calls:
            break

        messages.append(message)
        for call in message.tool_calls:
            if call.type != "function":
                raise ValueError(f"Unsupported model tool call type: {call.type}")
            try:
                params = json.loads(call.function.arguments)
                if not isinstance(params, dict):
                    raise TypeError("Tool arguments must be a JSON object.")
                output = wf.act(episode.id, call.function.name, **params).observation
            except (TypeError, ValueError) as exc:
                output = {"error": str(exc)}
            messages.append({
                "role": "tool",
                "tool_call_id": call.id,
                "content": json.dumps(output),
            })


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=PROVIDERS, required=True)
    parser.add_argument("--model", required=True, help="A tool-calling model ID from the provider.")
    args = parser.parse_args()

    base_url, key_name = PROVIDERS[args.provider]
    api_key = os.environ.get(key_name) if key_name else "ollama"
    if not api_key:
        parser.error(f"Set {key_name} before running this provider.")

    wf = WorldFoundry(DATA_DIR)
    episode = wf.start("support-desk", seed=7)
    trace_path = DATA_DIR / f"{episode.id}.jsonl"
    try:
        local_http = DefaultHttpxClient(trust_env=False) if key_name is None else None
        with OpenAI(
            base_url=base_url, api_key=api_key, http_client=local_http, timeout=30, max_retries=0
        ) as client:
            run_agent(client, args.model, wf, episode)
        result = wf.submit(episode.id)
    except (APIError, ValueError) as exc:
        parser.exit(1, f"Run stopped: {exc}\nPartial trace: {trace_path}\n")
    finally:
        wf.export_trace(episode.id, trace_path)

    passed = sum(check.passed for check in result.checks)
    print(f"{args.model}: {passed}/{len(result.checks)} checks passed")
    for check in result.checks:
        if not check.passed:
            print(f"  Missed: {check.message}")
    print(f"Trace: {trace_path}")


if __name__ == "__main__":
    main()
