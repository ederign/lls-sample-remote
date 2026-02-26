.PHONY: server client

server:
	uv run llama stack run run.yaml

client:
	uv run python main.py
