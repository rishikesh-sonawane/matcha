VENV = venv
PYTHON = $(VENV)/bin/python
RUFF = $(VENV)/bin/ruff
BANDIT = $(VENV)/bin/bandit
PRECOMMIT = $(VENV)/bin/pre-commit
PYINSTALLER = $(VENV)/bin/pyinstaller

.PHONY: run run-configure run-new-profile run-noninteractive
.PHONY: test test-verbose lint format format-fix static-analysis pre-commit check
.PHONY: build-executable build-container clean

# ── Run ──────────────────────────────────────────────────────────────────────

run: $(VENV)
	$(VENV)/bin/matcha

run-configure: $(VENV)
	$(VENV)/bin/matcha --configure

run-new-profile: $(VENV)
	$(VENV)/bin/matcha --new-profile

run-noninteractive: $(VENV)
	$(VENV)/bin/matcha --non-interactive

# ── Test & Quality ────────────────────────────────────────────────────────────

test: $(VENV)
	$(PYTHON) -m unittest discover tests -v

test-verbose: $(VENV)
	$(PYTHON) -m unittest discover tests -v --buffer

test-coverage: $(VENV)
	$(VENV)/bin/coverage run -m pytest tests -q
	$(VENV)/bin/coverage report --fail-under=80

lint: $(VENV)
	$(RUFF) check .

format: $(VENV)
	$(RUFF) format --diff .

format-fix: $(VENV)
	$(RUFF) check --fix .
	$(RUFF) format .

static-analysis: $(VENV)
	$(BANDIT) -c pyproject.toml -r src/matcha -lll

pre-commit: $(VENV)
	$(PRECOMMIT) run --all-files --show-diff-on-failure

check: lint format static-analysis pre-commit test
	@echo "━━━ All checks passed ━━━"

# ── Build ─────────────────────────────────────────────────────────────────────

build-executable: $(VENV)
	$(PYINSTALLER) --onefile --name matcha $(VENV)/bin/matcha

build-container:
	docker build -t matcha:latest .

# ── Clean ─────────────────────────────────────────────────────────────────────

clean:
	rm -rf __pycache__ */__pycache__ .pytest_cache
	rm -rf build dist *.spec
	rm -f matcha-image.tar.gz
	rm -rf *.egg-info

# ── Bootstrap ─────────────────────────────────────────────────────────────────

venv:
	python3 -m venv $(VENV)
	$(VENV)/bin/pip install --upgrade pip
	$(VENV)/bin/pip install -r requirements.txt
	$(VENV)/bin/pip install -e .
	$(VENV)/bin/pip install ruff bandit pre-commit pyinstaller
	$(PRECOMMIT) install
