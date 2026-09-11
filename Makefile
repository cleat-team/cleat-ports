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

# DIALECT selects which database the ports run against: postgres (default),
# mysql or mssql. It picks the compose profile, the DSN and the worker's
# -driver flag together, because getting one of the three wrong produces an
# error about SSL or about a missing "=" rather than about dialect.
DIALECT ?= postgres

# Matches MSSQL_SA_PASSWORD in docker-compose.yml. Named here because `make deps`
# has to connect as sa to create the user database SQL Server does not create
# for itself.
MSSQL_SA_PASSWORD ?= Cleat!Passw0rd

.PHONY: deps
deps: ## Start the database for DIALECT (default postgres): make deps DIALECT=mysql
	@case "$(DIALECT)" in \
	  postgres) docker compose up -d --wait postgres ;; \
	  mysql|mssql) docker compose --profile $(DIALECT) up -d --wait postgres $(DIALECT) ;; \
	  *) echo "DIALECT must be postgres, mysql or mssql (got: $(DIALECT))" >&2; exit 2 ;; \
	esac
	@# SQL Server has no equivalent of POSTGRES_DB or MYSQL_DATABASE: the image
	@# creates no user database, so a fresh container comes up with master only
	@# and the worker fails at startup with
	@#
	@#   Cannot open database "cleat_ports" that was requested by the login.
	@#   Using the user default database "master" instead.
	@#
	@# which names the database and not the fact that nothing ever created it.
	@# The other two dialects get this from an environment variable in
	@# docker-compose.yml, so the asymmetry is invisible until the container is
	@# recreated -- and a long-lived container hides it indefinitely.
	@# An API key lives in the database it was minted against, so a recreated
	@# database invalidates it -- while .port-results/api-key.<dialect> survives,
	@# and mint_key returns early on any non-empty file. The result is a 401 on
	@# every test, which names authentication: the one thing that is not wrong.
	@#
	@# This is the same defect as the shared key file, one level deeper. There
	@# the file's NAME did not distinguish two databases; here its EXISTENCE
	@# stands in for the key still being valid. Tying the key's lifetime to the
	@# database's is what actually removes the class.
	@# Both keys, and the tenant id beside them. An API key lives in the
	@# database it was minted against, and so does the tenant it names -- so a
	@# recreated database must invalidate all three together. Clearing only the
	@# first leaves the second tenant's key and id pointing at rows that no
	@# longer exist, which surfaces as a 401 on the cross-tenant tests alone.
	@rm -f .port-results/$${COMPOSE_PROJECT_NAME:-default}/api-key.$(DIALECT) \
	      .port-results/$${COMPOSE_PROJECT_NAME:-default}/api-key-b.$(DIALECT) \
	      .port-results/$${COMPOSE_PROJECT_NAME:-default}/tenant-b.$(DIALECT)
	@if [ "$(DIALECT)" = "mssql" ]; then \
	  echo "==> ensuring the cleat_ports database exists on SQL Server"; \
	  docker compose exec -T mssql /opt/mssql-tools18/bin/sqlcmd \
	    -S localhost -U sa -P "$(MSSQL_SA_PASSWORD)" -C \
	    -Q "IF DB_ID('cleat_ports') IS NULL CREATE DATABASE cleat_ports;" \
	    || { echo "failed to create the cleat_ports database" >&2; exit 1; }; \
	fi

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
	@# CLEAT_PORTS_DIALECT is EXPORTED rather than prefixed onto run-port.sh,
	@# because the trap runs in this shell and a command prefix does not reach
	@# it. Prefixed, cleanup ran as the default dialect: worker.sh matches the
	@# running process against $$CLEAT_PORTS_DSN, so a postgres stop could not
	@# match a mysql or mssql worker, called this run's OWN worker foreign and
	@# refused. Every non-postgres run then stranded its worker and the next
	@# run at a different dialect was refused.
	@export CLEAT_PORTS_DIALECT=$(DIALECT); \
	 trap './scripts/worker.sh stop' EXIT INT TERM; ./scripts/run-port.sh "$(PORT)"

.PHONY: worker-up
worker-up: ## Start the shared cleat worker (normally done for you by `make port`)
	CLEAT_PORTS_DIALECT=$(DIALECT) ./scripts/worker.sh ensure

.PHONY: worker-down
worker-down: ## Stop the shared cleat worker: make worker-down DIALECT=mysql
	@# Needs DIALECT too -- worker.sh identifies the worker by its DSN, so a
	@# bare `make worker-down` cannot stop a mysql or mssql worker.
	CLEAT_PORTS_DIALECT=$(DIALECT) ./scripts/worker.sh stop

.PHONY: all-ports
all-ports: ## Run every port; keeps going on failure and fails at the end
	@# Exported for the reason on `port` above: the trap cannot see a prefix.
	@export CLEAT_PORTS_DIALECT=$(DIALECT); \
	trap './scripts/worker.sh stop' EXIT INT TERM; \
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
clean: ## Remove build artifacts from every port, for THIS run only
	@for p in $(PORTS); do $(MAKE) -C "ports/$$p" clean 2>/dev/null || true; done
	@# This run's subdirectory, never the whole tree. Several sessions share
	@# this checkout and key their state by COMPOSE_PROJECT_NAME, so a bare
	@# `rm -rf .port-results` deletes every concurrent session's pidfiles, keys
	@# and logs at once -- a worse version of the sharing this layout exists to
	@# prevent, and instantaneous rather than gradual.
	rm -rf .port-results/$${COMPOSE_PROJECT_NAME:-default}
