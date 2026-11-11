# Makefile for dumping Wikipedia articles to PDF
# Usage: make dump subject="Your Subject Here" depth=2 max_articles=1000

subject ?= The Ramones
depth ?= 2
max_articles ?= 100
PYTHON ?= python3
ARGS ?=

.PHONY: dump dump-local

dump:
	@docker compose run --build --rm wiki python /app/dump.py "$(subject)" --depth "$(depth)" --max-articles "$(max_articles)" $(ARGS)

dump-local:
	@$(PYTHON) dump.py "$(subject)" --depth "$(depth)" --max-articles "$(max_articles)" $(ARGS)