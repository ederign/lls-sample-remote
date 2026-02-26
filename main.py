"""Sample client that calls the Llama Stack server via its OpenAI-compatible API.

The server uses the remote::passthrough provider, which means:
- No API key is stored in the server config (run.yaml)
- Models are explicitly registered via registered_resources (no auto-discovery)
- The API key is passed per-request via the X-LlamaStack-Provider-Data header

Drawbacks of remote::passthrough vs remote::openai:
- The header requires BOTH passthrough_url and passthrough_api_key, even when
  base_url is already set in run.yaml (the validator enforces both fields)
- No OpenAIMixin processing: no embedding metadata, no model type awareness,
  no stream_options injection for usage stats in streaming responses
- It's a pure proxy — less integrated with llama-stack's model management
"""

import json
import os

import httpx


LLAMA_STACK_URL = "http://localhost:8321"


def provider_data_header(api_key: str) -> dict:
    return {
        "X-LlamaStack-Provider-Data": json.dumps({
            "passthrough_api_key": api_key,
            "passthrough_url": "https://api.openai.com",  # required by the validator even if set in run.yaml
        })
    }


def chat(api_key: str):
    """Regular (non-streaming) chat completion."""
    headers = {"Content-Type": "application/json", **provider_data_header(api_key)}

    response = httpx.post(
        f"{LLAMA_STACK_URL}/v1/chat/completions",
        headers=headers,
        json={
            "model": "openai/gpt-4o",
            "messages": [{"role": "user", "content": "Say hello in three languages. Be brief."}],
        },
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    print("=== Regular ===")
    print(data["choices"][0]["message"]["content"])


def chat_streaming(api_key: str):
    """Streaming chat completion."""
    headers = {"Content-Type": "application/json", **provider_data_header(api_key)}

    print("\n=== Streaming ===")
    with httpx.stream(
        "POST",
        f"{LLAMA_STACK_URL}/v1/chat/completions",
        headers=headers,
        json={
            "model": "openai/gpt-4o",
            "stream": True,
            "messages": [{"role": "user", "content": "Count from 1 to 5."}],
        },
        timeout=30,
    ) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            if not line.startswith("data: "):
                continue
            payload = line.removeprefix("data: ")
            if payload.strip() == "[DONE]":
                break
            chunk = json.loads(payload)
            content = chunk["choices"][0]["delta"].get("content")
            if content:
                print(content, end="", flush=True)
    print()


def main():
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise SystemExit("Set OPENAI_API_KEY environment variable")

    chat(api_key)
    chat_streaming(api_key)


if __name__ == "__main__":
    main()
