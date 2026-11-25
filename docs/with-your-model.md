# Test a model on the same support ticket

WorldFoundry runs the simulated ticket tools. Your model decides which tools to call. After each run, you get five pass/fail checks and a JSONL action trace.

## Run the example

1. Install the SDK and model client.

   ```bash
   python -m pip install "worldfoundry>=0.8.0" openai
   ```

2. Save [`support_agent.py`](../examples/support_agent.py) from GitHub using **Download raw file**.

3. Pick a provider and run its command next to the file. For a hosted model, set the listed API key in your environment first. Use an available tool-calling model if your account uses a different model ID.

   | Provider | What to set up | Run |
   | --- | --- | --- |
   | OpenAI GPT | `OPENAI_API_KEY` | `python support_agent.py --provider openai --model gpt-5-mini` |
   | Google Gemini | `GEMINI_API_KEY` | `python support_agent.py --provider gemini --model gemini-4-hydrogen` |
   | Anthropic Claude | `ANTHROPIC_API_KEY` | `python support_agent.py --provider claude --model claude-sonnet-5-5` |
   | Local Ollama | Start Ollama and run `ollama pull qwen3:8b` | `python support_agent.py --provider ollama --model qwen3:8b` |

The script uses the providers' OpenAI-compatible Chat Completions endpoints. Hosted providers receive the sample task and simulated tool inputs and outputs, and may charge for model calls. Ollama stays on your machine.

[OpenAI function calling](https://developers.openai.com/api/docs/guides/function-calling) · [Gemini compatibility](https://ai.google.dev/gemini-api/docs/openai) · [Claude compatibility](https://platform.claude.com/docs/en/cli-sdks-libraries/libraries/openai-sdk) · [Ollama compatibility](https://docs.ollama.com/api/openai-compatibility)

## Read the result

- **Score** shows how many checks passed. A result like `4/5` means one check failed.
- **Missed checks** name the state or reply requirement the model missed.
- **Trace** shows the simulated tool calls and their results. Each run saves its own file under `.wf-data/`.

Run the script again with a different model to compare both against the same starting ticket and rules. Scores can vary between runs. This example covers one test case. For varied starting states or events such as a mid-run priority reset, [build your own scenarios](custom-environments.md).
