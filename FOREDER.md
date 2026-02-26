# FOREDER.md — How This Project Works (and What We Learned)

## What is this project?

A Llama Stack server that acts as a **multi-provider inference gateway**. You start one server, and it can route requests to OpenAI, Google Gemini, and Anthropic Claude — all through a single unified API. The twist: no API keys are stored on the server. Callers pass their own keys per-request.

Think of it like a hotel concierge desk. The concierge (Llama Stack) doesn't own any cars, but if you hand them your car keys, they'll drive whichever one you ask for.

## The Architecture

```
                         ┌─────────────────────┐
                         │   Llama Stack        │
  Client ──────────────► │   (port 8321)        │
  + API key in header    │                      │
                         │  ┌─ openai ────────────► api.openai.com
                         │  ├─ openai-mini ───────► api.openai.com
                         │  ├─ gemini ────────────► generativelanguage.googleapis.com
                         │  └─ anthropic ─────────► api.anthropic.com
                         └─────────────────────┘
```

Each provider is a `remote::passthrough` instance — a pure proxy that forwards OpenAI-format requests to the target API. The models are explicitly declared in `run.yaml` under `registered_resources`.

## The Codebase

It's tiny — only 4 files matter:

| File | What it does |
|---|---|
| `run.yaml` | Server configuration: providers, models, storage |
| `main.py` | Sample Python client showing regular + streaming inference |
| `Makefile` | `make server` / `make client` shortcuts |
| `.env` | API keys (git-ignored, never committed) |

Everything else (`pyproject.toml`, `uv.lock`, `.python-version`) is standard uv project scaffolding.

## How `run.yaml` is structured

The config has four sections that matter:

### 1. Providers — where to send requests

```yaml
providers:
  inference:
    - provider_id: openai
      provider_type: remote::passthrough
      config:
        base_url: https://api.openai.com
```

Each provider maps a `provider_id` to a `base_url`. The `remote::passthrough` type means "just forward the request, don't do anything clever."

### 2. Registered Resources — which models exist

```yaml
registered_resources:
  models:
    - provider_id: openai
      model_id: gpt-4o
      model_type: llm
```

This is the model catalog. When a client calls `/v1/models`, only these show up. The `model_id` combined with `provider_id` becomes the full identifier: `openai/gpt-4o`.

### 3. Storage — where metadata lives

SQLite databases for the model registry and inference state. Boring but necessary. These get auto-created under `~/.llama/distributions/lls-openai/`.

### 4. Server — port config

Just `port: 8321`.

## The Big Decision: Why `remote::passthrough`?

This was the most interesting part of the project. Here's the story.

### The problem with `remote::openai`

Llama Stack's natural choice for OpenAI is `remote::openai`. But it has a fatal flaw for our use case: **it requires a valid API key at server startup**.

Why? Because at boot, the OpenAI provider calls `/v1/models` to auto-discover all available models (114 of them!). It then uses this list to validate any models you try to register via `registered_resources`. No key → no discovery → no validation → no registration → crash.

We traced this through the code:

1. `Stack.initialize()` calls `register_resources()`
2. Which calls `ModelsRoutingTable.register_model()`
3. Which calls `register_object_with_provider()`
4. Which calls `OpenAIMixin.register_model()`
5. Which calls `check_model_availability()`
6. Which calls `list_models()` → hits the OpenAI API
7. No key → empty model cache → `ValueError: Model gpt-4o is not available`

We also discovered `allowed_models` — a config filter that limits auto-discovery. But it can't help: even with `allowed_models: [gpt-4o]`, the provider still needs a valid key to discover that one model. And `allowed_models: []` means nothing passes the filter, so `registered_resources` can't validate against an empty list.

### The vLLM escape hatch

We found that `remote::vllm` handles this differently. It overrides `check_model_availability()` to return `True` unconditionally when auth credentials are set. The OpenAI provider doesn't — it inherits the strict validation.

You can see this in the [llama-stack source](https://github.com/llamastack/llama-stack/blob/main/src/llama_stack/providers/remote/inference/vllm/vllm.py#L56).

### The `remote::passthrough` solution

We discovered that `remote::passthrough` does **zero model validation**:

```python
async def register_model(self, model: Model) -> Model:
    return model  # That's it. No validation.
```

It's a pure proxy. You can register literally any model ID. The API key is never needed at startup — only at inference time, passed via the `X-LlamaStack-Provider-Data` header.

This also works for Gemini and Anthropic because both expose OpenAI-compatible endpoints:
- Gemini: `https://generativelanguage.googleapis.com/v1beta/openai`
- Anthropic: `https://api.anthropic.com/v1/` ([docs](https://docs.anthropic.com/en/api/openai-sdk))

## Bugs and Gotchas We Hit

### 1. The `telemetry` API was removed in 0.5.1

The docs and examples online still reference it, but `Api('telemetry')` throws `ValueError: API 'telemetry' does not exist`. We had to strip it from the config.

### 2. Tilde (`~`) in YAML paths doesn't expand

`db_path: ~/.llama/...` created a literal `~/` directory inside the project instead of expanding to the home directory. Fix: use `${env.HOME}/.llama/...`.

### 3. The `models` top-level key is silently ignored

Early configs had a top-level `models:` section (not under `registered_resources:`). Pydantic's `StackConfig` has no `models` field, so it was silently dropped. The server ran fine because auto-discovery registered the models anyway. Sneaky.

### 4. `PassthroughProviderDataValidator` requires both fields

The validator requires **both** `passthrough_url` AND `passthrough_api_key` in the header — even when `base_url` is already set in `run.yaml`. Both fields are `required=True` with no defaults. If you only send the API key, validation fails silently (logged, returns None), and you get a confusing error.

### 5. Auto-discovery and `registered_resources` are additive

They don't replace each other. Auto-discovery registers `openai/gpt-4o`, then `registered_resources` tries to register it again → duplicate error. If `registered_resources` uses a different model_id (e.g., `gpt-4o` without prefix), no conflict — but then you have two entries for the same model.

### 6. SQLite DB persistence causes stale state

Models registered by auto-discovery persist in the kvstore across restarts. If you change the config and restart, old models still exist. We had to `rm` the DB files between restarts to get a clean slate.

## Technologies Used

| Tech | Why |
|---|---|
| **Llama Stack 0.5.1** | Meta's AI application framework — provides a unified API layer across providers |
| **uv** | Fast Python package manager — handles deps, venvs, and script running |
| **Python 3.12** | Minimum required by llama-stack 0.5.1 |
| **httpx** | HTTP client for the sample script (already a transitive dep) |
| **SQLite** | Backing store for model registry and inference state |

## Lessons for Future Work

1. **Read the source, not the docs.** The llama-stack docs are outdated for 0.5.1. The actual behavior lives in `OpenAIMixin`, `StackConfig`, and the provider implementations. `uv run python -c "import inspect; ..."` is your best friend when packages ship only `.pyc` files.

2. **Provider choice matters more than you'd think.** `remote::openai` vs `remote::passthrough` isn't just a naming difference — it's a completely different validation, lifecycle, and feature set. Pick the wrong one and your server won't even start.

3. **Always clear the kvstore when iterating on `run.yaml`.** Stale model registrations from previous runs will haunt you with confusing duplicate errors.

4. **Anthropic's OpenAI compatibility layer is real and works.** You don't need the `remote::anthropic` provider if you just want chat completions. The passthrough proxy pointing at `https://api.anthropic.com` works fine.

5. **The `X-LlamaStack-Provider-Data` header pattern is powerful but awkward.** Passing credentials per-request keeps the server stateless, but the redundant URL requirement and JSON-in-header format is clunky. A proper auth middleware would be cleaner for production.
