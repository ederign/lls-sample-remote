# lls-openai

Llama Stack server using the `remote::passthrough` provider with OpenAI, Gemini, and Anthropic. No API key stored on the server — keys are passed per-request via headers.

## Setup

```bash
uv sync
```

Create a `.env` file with your API keys:

```bash
cat > .env <<EOF
OPENAI_API_KEY=sk-your-key-here
GEMINI_API_KEY=your-gemini-key-here
ANTHROPIC_API_KEY=your-anthropic-key-here
EOF
```

## Start the server

```bash
make server
```

Or manually:

```bash
uv run llama stack run run.yaml
```

The server starts on `http://localhost:8321` with no API key required at boot.

## Registered models

The `run.yaml` explicitly registers models via `registered_resources` (no auto-discovery):

| Model ID | Provider | Display Name |
|---|---|---|
| `openai/gpt-4o` | openai | GPT-4o |
| `openai-mini/gpt-4o-mini` | openai-mini | GPT-4o Mini |
| `openai-mini/gpt-4.1-nano` | openai-mini | GPT-4.1 Nano |
| `gemini/gemini-2.5-flash-lite` | gemini | Gemini 2.5 Flash Lite |
| `anthropic/claude-haiku-4-5-20251001` | anthropic | Claude Haiku 4.5 |

## List models

```bash
curl -s http://localhost:8321/v1/models | jq '.data[].id'
```

Export your API key first:

```bash
export $(cat .env)
```

## Inference (regular)

```bash
curl -s http://localhost:8321/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "X-LlamaStack-Provider-Data: {\"passthrough_api_key\": \"$OPENAI_API_KEY\", \"passthrough_url\": \"https://api.openai.com\"}" \
  -d '{
    "model": "openai/gpt-4o",
    "messages": [{"role": "user", "content": "Hello!"}]
  }' | jq '.choices[0].message.content'
```

## Inference with Gemini

```bash
curl -s http://localhost:8321/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "X-LlamaStack-Provider-Data: {\"passthrough_api_key\": \"$GEMINI_API_KEY\", \"passthrough_url\": \"https://generativelanguage.googleapis.com/v1beta/openai\"}" \
  -d '{
    "model": "gemini/gemini-2.5-flash-lite",
    "messages": [{"role": "user", "content": "Which model are you?"}]
  }' | jq '.choices[0].message.content'
```

## Inference with Anthropic (Claude)

Anthropic exposes an [OpenAI-compatible endpoint](https://docs.anthropic.com/en/api/openai-sdk), so `remote::passthrough` works here too.

```bash
curl -s http://localhost:8321/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "X-LlamaStack-Provider-Data: {\"passthrough_api_key\": \"$ANTHROPIC_API_KEY\", \"passthrough_url\": \"https://api.anthropic.com\"}" \
  -d '{
    "model": "anthropic/claude-haiku-4-5-20251001",
    "messages": [{"role": "user", "content": "Which model are you?"}]
  }' | jq '.choices[0].message.content'
```

## Inference (streaming)

```bash
curl -s -N http://localhost:8321/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "X-LlamaStack-Provider-Data: {\"passthrough_api_key\": \"$OPENAI_API_KEY\", \"passthrough_url\": \"https://api.openai.com\"}" \
  -d '{
    "model": "openai/gpt-4o",
    "stream": true,
    "messages": [{"role": "user", "content": "Count from 1 to 5."}]
  }'
```

## Python client

```bash
make client
```

Or:

```bash
export $(cat .env) && uv run python main.py
```

## Why `remote::passthrough` instead of `remote::openai`?

The `remote::openai` provider requires a valid API key at server startup because it auto-discovers models by calling OpenAI's `/v1/models` endpoint. It also validates models during `registered_resources` registration against that discovered list.

`remote::passthrough` skips all of that:
- `register_model()` does zero validation — any model ID is accepted
- No auto-discovery at startup
- API key is only needed at inference time, passed per-request

**Tradeoffs:**
- The `X-LlamaStack-Provider-Data` header requires both `passthrough_url` and `passthrough_api_key`, even when `base_url` is set in `run.yaml`
- No `OpenAIMixin` processing (no embedding metadata, no stream_options for usage stats in streaming)
- Pure proxy — less integrated with llama-stack's model management
