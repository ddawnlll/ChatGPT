.PHONY: help setup-browser start-proxy start-api shell setup-python setup-bun setup clean-profile kill-browser enter-pi test-proxy test-pi-contract test-browser-e2e test-all-fast test-all test-all-live test-js test-regression test-regression-live

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
	@echo "  make test-all      - Run staged full test suite (browser E2E skips unless RUN_BROWSER_E2E=1)"
	@echo "  make test-all-live - Run full suite including live browser E2E"
	@echo "  make test-regression      - Run fast deterministic regression coverage"
	@echo "  make test-regression-live - Run regression coverage plus live pi/browser smokes"

login:
	@bun tools/login.mjs

diag:
	@bun tools/diag.js

test-proxy:
	.venv/bin/pytest \
		tests/test_tools_shim_regressions.py \
		tests/test_router_agent_regressions.py \
		tests/test_streaming_contract.py \
		-q

test-pi-contract:
	.venv/bin/pytest \
		tests/test_pi_tool_contract_e2e.py \
		tests/test_pi_agent_cli_e2e.py \
		tests/test_fake_playwright_daemon.py \
		tests/test_fake_playwright_daemon_process.py \
		-q

test-regression:
	.venv/bin/pytest \
		tests/test_tools_shim_regressions.py \
		tests/test_router_agent_regressions.py \
		tests/test_pi_agent_cli_e2e.py \
		-q

test-regression-live: test-regression
	RUN_BROWSER_E2E=1 .venv/bin/pytest \
		tests/test_real_browser_smoke.py \
		tests/test_real_browser_write_smoke.py \
		tests/test_real_pi_browser_smoke.py \
		-q

test-js:
	bun run test:playwright-helpers

test-browser-e2e:
	RUN_BROWSER_E2E=1 .venv/bin/pytest \
		tests/test_real_browser_smoke.py \
		tests/test_real_browser_write_smoke.py \
		tests/test_real_pi_browser_smoke.py \
		-q

test-all-fast: test-js
	.venv/bin/pytest tests -q -m "not browser_e2e"

test-all:
	.venv/bin/python tools/test_all.py

test-all-live:
	RUN_BROWSER_E2E=1 .venv/bin/python tools/test_all.py

kill-browser:
	@echo "Killing browser processes..."
	@pkill -x chrome || true
	@pkill -x chromium || true
	@pgrep -f "chromium-browser" >/dev/null && pkill -f "chromium-browser" || true
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
