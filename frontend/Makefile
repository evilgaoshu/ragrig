NPM ?= npm

.PHONY: install lint test test-run build audit check

install:
	$(NPM) install

lint: install
	$(NPM) run lint

test: test-run

test-run: install
	$(NPM) run test:run

build: install
	$(NPM) run build

audit: install
	$(NPM) audit --audit-level=high

check: lint test-run build
