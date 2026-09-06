# cleat-ports — run ported upstream test suites against cleat.
#
# The cleat toolchain under test is selected by CLEAT_REF, which defaults to
# CLEAT_PINNED_REF in cleat-version.env -- currently `develop`, so ports track
# cleat's development branch rather than the last release. See the rationale and
# the cost of that choice in cleat-version.env.

include cleat-version.env
export

CLEAT_REF ?= $(CLEAT_PINNED_REF)
PORTS     := $(notdir $(wildcard ports/*))
PORTS     := $(filter-out TEMPLATE README.md,$(PORTS))

.DEFAULT_GOAL := help

.PHONY: help
help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
	  | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'
	@echo
	@echo "  ports: $(PORTS)"

.PHONY: deps
deps: ## Start PostgreSQL for the ports to run against
	docker compose up -d --wait

.PHONY: deps-down
deps-down: ## Stop and remove the PostgreSQL container and its volume
	docker compose down -v

.PHONY: install-cleat
install-cleat: ## Install the cleat toolchain at CLEAT_REF (default: pinned)
	@echo "==> installing cleat @ $(CLEAT_REF)"
	./scripts/install-cleat.sh "$(CLEAT_REF)"

.PHONY: port
port: ## Run one port: make port PORT=dbos-transact-py
	@test -n "$(PORT)" || { echo "usage: make port PORT=<name>  (have: $(PORTS))" >&2; exit 2; }
	@test -d "ports/$(PORT)" || { echo "no such port: $(PORT)" >&2; exit 2; }
	@trap './scripts/worker.sh stop' EXIT INT TERM; ./scripts/run-port.sh "$(PORT)"

.PHONY: worker-up
worker-up: ## Start the shared cleat worker (normally done for you by `make port`)
	./scripts/worker.sh ensure

.PHONY: worker-down
worker-down: ## Stop the shared cleat worker
	./scripts/worker.sh stop

.PHONY: all-ports
all-ports: ## Run every port; keeps going on failure and fails at the end
	@trap './scripts/worker.sh stop' EXIT INT TERM; \
	rc=0; for p in $(PORTS); do \
	  echo "=== $$p"; ./scripts/run-port.sh "$$p" || rc=1; \
	done; exit $$rc

.PHONY: new-port
new-port: ## Scaffold a new port: make new-port PORT=<name>
	@test -n "$(PORT)" || { echo "usage: make new-port PORT=<name>" >&2; exit 2; }
	@test ! -e "ports/$(PORT)" || { echo "ports/$(PORT) already exists" >&2; exit 2; }
	cp -R ports/TEMPLATE "ports/$(PORT)"
	@echo "scaffolded ports/$(PORT) — now fill in UPSTREAM, README.md, and Makefile"
	@echo "see docs/adding-a-port.md"

.PHONY: clean
clean: ## Remove build artifacts from every port
	@for p in $(PORTS); do $(MAKE) -C "ports/$$p" clean 2>/dev/null || true; done
	rm -rf .port-results
