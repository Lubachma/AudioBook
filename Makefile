# Project commands — run "make" or "make help" for the list.
#
# The server runs as a macOS LaunchAgent (KeepAlive): a plain kill would get
# restarted immediately. It is therefore stopped via launchctl bootout
# (make stop); the service comes back at next login or with make start.
# To remove it for good: make service-remove.

LABEL   := com.audiobook.server
PLIST   := $(HOME)/Library/LaunchAgents/$(LABEL).plist
UID_NUM := $(shell id -u)
URL     := http://127.0.0.1:8765

ENGINE ?= qwen3
VOICE  ?= ref:claire

.DEFAULT_GOAL := help
.PHONY: help start stop restart status logs run install service-install service-remove sync test test-slow voices bench

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

start: ## Start the server (launchd service, port 8765)
	@if [ ! -f "$(PLIST)" ]; then ./scripts/install_service.sh; exit 0; fi
	@for i in 1 2 3 4 5; do \
		launchctl print "gui/$(UID_NUM)/$(LABEL)" >/dev/null 2>&1 && break; \
		launchctl bootstrap "gui/$(UID_NUM)" "$(PLIST)" 2>/dev/null && break; \
		[ $$i -eq 5 ] && { echo "launchd bootstrap failed after 5 attempts." >&2; exit 1; }; \
		sleep 2; \
	done
	@launchctl kickstart "gui/$(UID_NUM)/$(LABEL)"
	@echo "Server started: $(URL)"

stop: ## Stop the server (make start to relaunch; it also comes back at next login)
	@if launchctl bootout "gui/$(UID_NUM)/$(LABEL)" 2>/dev/null; then \
		echo "Server stopped. Run 'make start' to relaunch it (it also comes back at next login)."; \
	else \
		echo "Server already stopped."; \
	fi

restart: ## Restart the server
	@if launchctl print "gui/$(UID_NUM)/$(LABEL)" >/dev/null 2>&1; then \
		launchctl kickstart -k "gui/$(UID_NUM)/$(LABEL)"; \
		echo "Server restarted: $(URL)"; \
	else \
		$(MAKE) start; \
	fi

status: ## launchd service state + HTTP check
	@launchctl print "gui/$(UID_NUM)/$(LABEL)" 2>/dev/null \
		| grep -E '^[[:space:]]+(state|pid) =' \
		|| echo "Service not loaded (make start to start it)."
	@curl -fsS -o /dev/null -m 3 "$(URL)/api/config" \
		&& echo "HTTP OK: $(URL)" \
		|| echo "HTTP DOWN: no response at $(URL)."

logs: ## Follow the server logs (Ctrl-C to quit)
	@tail -n 50 -f "$(HOME)/Library/Logs/audiobook.out.log" "$(HOME)/Library/Logs/audiobook.err.log"

run: ## Foreground server with auto-reload (run make stop first: same port)
	.venv/bin/uvicorn app.main:app --port 8765 --reload

install: ## Install venvs + dependencies + models (~16 GB, takes a while)
	./scripts/install.sh

service-install: ## (Re)install the LaunchAgent and start the server
	./scripts/install_service.sh

service-remove: ## Uninstall the LaunchAgent (no longer comes back at login)
	./scripts/install_service.sh --remove

sync: ## Update Python dependencies (uv sync --extra local --extra dev)
	uv sync --extra local --extra dev

test: ## Fast test suite (mocked engines)
	uv run pytest

test-slow: ## Real integration tests (local models, takes minutes)
	uv run pytest -m slow -s

voices: ## (Re)build the designed French voices (data/voices/)
	.venv/bin/python scripts/design_voices.py

bench: ## TTS speed benchmark — variables: ENGINE=qwen3 VOICE=ref:claire
	.venv/bin/python scripts/bench_tts.py --engine "$(ENGINE)" --voice "$(VOICE)"
