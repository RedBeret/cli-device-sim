PYTHON ?= python3.12
VENV ?= .venv
COMPOSE ?= docker compose

.PHONY: install test up down logs reset demo

install:
	$(PYTHON) -m venv $(VENV)
	. $(VENV)/bin/activate && pip install --upgrade pip && pip install -e .[dev]

test:
	. $(VENV)/bin/activate && pytest

up:
	$(COMPOSE) up --build -d

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f sim

reset:
	curl -fsS -X POST http://127.0.0.1:8080/reset

demo: up
	$(COMPOSE) exec -T sim python -m cli_device_sim demo-client --ssh-host 127.0.0.1 --ssh-port 2222 --api-url http://127.0.0.1:8080 --reset-first
