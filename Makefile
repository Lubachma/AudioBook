# Commandes du projet — « make » ou « make help » pour la liste.
#
# Le serveur tourne comme LaunchAgent macOS (KeepAlive) : un simple kill le
# relancerait aussitôt. On l'arrête donc via launchctl bootout (make stop) ;
# le service revient au prochain login ou avec make start. Pour qu'il ne
# revienne plus du tout : make service-remove.

LABEL   := com.audiobook.server
PLIST   := $(HOME)/Library/LaunchAgents/$(LABEL).plist
UID_NUM := $(shell id -u)
URL     := http://127.0.0.1:8765

ENGINE ?= qwen3
VOICE  ?= ref:claire

.DEFAULT_GOAL := help
.PHONY: help start stop restart status logs run install service-install service-remove sync test test-slow voices bench

help: ## Affiche cette aide
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

start: ## Démarre le serveur (service launchd, port 8765)
	@if [ ! -f "$(PLIST)" ]; then ./scripts/install_service.sh; exit 0; fi
	@for i in 1 2 3 4 5; do \
		launchctl print "gui/$(UID_NUM)/$(LABEL)" >/dev/null 2>&1 && break; \
		launchctl bootstrap "gui/$(UID_NUM)" "$(PLIST)" 2>/dev/null && break; \
		[ $$i -eq 5 ] && { echo "Échec du bootstrap launchd après 5 tentatives." >&2; exit 1; }; \
		sleep 2; \
	done
	@launchctl kickstart "gui/$(UID_NUM)/$(LABEL)"
	@echo "Serveur démarré : $(URL)"

stop: ## Arrête le serveur (make start pour relancer ; revient aussi au prochain login)
	@if launchctl bootout "gui/$(UID_NUM)/$(LABEL)" 2>/dev/null; then \
		echo "Serveur arrêté. « make start » pour le relancer (il reviendra aussi au prochain login)."; \
	else \
		echo "Serveur déjà arrêté."; \
	fi

restart: ## Redémarre le serveur
	@if launchctl print "gui/$(UID_NUM)/$(LABEL)" >/dev/null 2>&1; then \
		launchctl kickstart -k "gui/$(UID_NUM)/$(LABEL)"; \
		echo "Serveur redémarré : $(URL)"; \
	else \
		$(MAKE) start; \
	fi

status: ## État du service launchd + réponse HTTP
	@launchctl print "gui/$(UID_NUM)/$(LABEL)" 2>/dev/null \
		| grep -E '^[[:space:]]+(state|pid) =' \
		|| echo "Service non chargé (make start pour le démarrer)."
	@curl -fsS -o /dev/null -m 3 "$(URL)/api/config" \
		&& echo "HTTP OK : $(URL)" \
		|| echo "HTTP KO : pas de réponse sur $(URL)."

logs: ## Suit les logs du serveur (Ctrl-C pour quitter)
	@tail -n 50 -f "$(HOME)/Library/Logs/audiobook.out.log" "$(HOME)/Library/Logs/audiobook.err.log"

run: ## Serveur en avant-plan avec rechargement auto (faire make stop d'abord : même port)
	.venv/bin/uvicorn app.main:app --port 8765 --reload

install: ## Installe venvs + dépendances + modèles (~16 Go, long)
	./scripts/install.sh

service-install: ## (Ré)installe le LaunchAgent et démarre le serveur
	./scripts/install_service.sh

service-remove: ## Désinstalle le LaunchAgent (ne revient plus au login)
	./scripts/install_service.sh --remove

sync: ## Met à jour les dépendances Python (uv sync --extra local --extra dev)
	uv sync --extra local --extra dev

test: ## Tests rapides (moteurs mockés)
	uv run pytest

test-slow: ## Tests d'intégration réels (modèles locaux, minutes)
	uv run pytest -m slow -s

voices: ## (Re)fabrique les voix françaises designées (data/voices/)
	.venv/bin/python scripts/design_voices.py

bench: ## Banc de vitesse TTS — variables : ENGINE=qwen3 VOICE=ref:claire
	.venv/bin/python scripts/bench_tts.py --engine "$(ENGINE)" --voice "$(VOICE)"
