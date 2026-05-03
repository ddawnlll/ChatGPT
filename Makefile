.PHONY: help setup-browser start-proxy start-api shell setup-python setup-bun setup clean-profile kill-browser enter-pi

# Export critical macOS environment variables for all commands
export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export PLAYWRIGHT_BROWSERS_PATH=$(shell pwd)/bin/browsers

# Default target
help:
	@echo "Available commands:"
	@echo "  make setup         - Full setup (python, bun, browser)"
	@echo "  make setup-python  - Create Python .venv and install dependencies"
	@echo "  make setup-bun     - Install root and frontend dependencies via bun"
	@echo "  make setup-browser - Check that a system browser is available"
	@echo "  make setup-pi      - Register the local proxy as a provider to pi coding agent"
	@echo "  make start-proxy   - Start the OpenAI-compatible proxy server"
	@echo "  make start-api     - Start the standard API server"
	@echo "  make shell         - Enter the Python virtual environment shell"
	@echo "  make login         - Open Firefox to log in to ChatGPT (one-time)"
	@echo "  make enter-pi      - Start the pi coding agent using the ChatGPT Proxy"
	@echo "  make clean-profile - Remove Firefox profile to start fresh"
	@echo "  make diag          - Run Playwright diagnostics"

login:
	@bun tools/login.mjs

diag:
	@bun tools/diag.js

kill-browser:
	@echo "Killing browser processes..."
	@pkill -f "Google Chrome" || true
	@pkill -f "Chromium" || true
	@echo "Done!"

clean-profile: kill-browser
	@echo "Removing browser profiles (will require re-login)..."
	rm -rf data/browser_profile
	rm -rf data/firefox_profile
	@echo "Done!"

setup-browser:
	@echo "Setting up local browser environment..."
	.venv/bin/python tools/setup_browser.py

setup-pi:
	@echo "Registering provider to pi coding agent..."
	.venv/bin/python tools/setup_pi_provider.py

start-proxy:
	@echo "Starting Proxy Server..."
	.venv/bin/uvicorn proxy.app.main:app --host 0.0.0.0 --port 8081 --reload

start-api:
	@echo "Starting API Server..."
	.venv/bin/python api_server.py

shell:
	@echo "Entering python virtual environment shell (type 'exit' to leave)..."
	@bash -c "source .venv/bin/activate && exec bash"

enter-pi:
	@echo "Starting pi coding agent with ChatGPT proxy (Ensure 'make start-proxy' is running in another tab!)"
	pi --provider chatgpt-wrapper --model chatgpt-playwright

setup-python:
	@echo "Setting up Python virtual environment..."
	python3 -m venv .venv
	.venv/bin/pip install --upgrade pip
	@if [ -f requirements.txt ]; then .venv/bin/pip install -r requirements.txt; fi

setup-bun:
	@echo "Setting up Bun dependencies (Root)..."
	bun install
	@echo "Setting up Bun dependencies (Frontend)..."
	cd frontend && bun install

setup: setup-python setup-bun setup-browser setup-pi
	@echo "Setup complete!"
