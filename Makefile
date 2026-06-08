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
	$(PYTHON) main.py

run-configure: $(VENV)
	$(PYTHON) main.py --configure

run-new-profile: $(VENV)
	$(PYTHON) main.py --new-profile

run-noninteractive: $(VENV)
	$(PYTHON) main.py --non-interactive

# ── Test & Quality ────────────────────────────────────────────────────────────

test: $(VENV)
	$(PYTHON) -m unittest discover tests -v

test-verbose: $(VENV)
	$(PYTHON) -m unittest discover tests -v --buffer

lint: $(VENV)
	$(RUFF) check .

format: $(VENV)
	$(RUFF) format --diff .

format-fix: $(VENV)
	$(RUFF) check --fix .
	$(RUFF) format .

static-analysis: $(VENV)
	$(BANDIT) -r ai.py config.py main.py matcher.py profile.py scrapers -lll

pre-commit: $(VENV)
	$(PRECOMMIT) run --all-files --show-diff-on-failure

check: lint format static-analysis pre-commit test
	@echo "━━━ All checks passed ━━━"

# ── Build ─────────────────────────────────────────────────────────────────────

build-executable: $(VENV)
	$(PYINSTALLER) --onefile --name matcha main.py

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
	$(VENV)/bin/pip install ruff bandit pre-commit pyinstaller
	$(PRECOMMIT) install
