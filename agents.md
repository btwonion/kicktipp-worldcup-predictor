# Agent Instructions

## Project Overview

This repository is a Python 3.11 CLI for ranking football score predictions by
expected Kicktipp points. The main entry point is `kicktipp_tool.py`; the
prediction model lives in `models.py`, scoring logic in `scoring.py`, and
external data adapters under `data_sources/`.

## Setup

Use an editable install with development dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Runtime API keys are loaded from `.env`. Never commit real keys. Use
`.env.example` as the template.

## Common Commands

Run the test suite:

```bash
python -m pytest
```

Run linting:

```bash
ruff check .
```

Run type checks:

```bash
mypy .
```

Run the CLI locally:

```bash
python kicktipp_tool.py predict \
  --team-a "some team" \
  --team-b "another team" \
  --match-date 2026-06-11
```

Use manual probabilities and total goals when avoiding external API calls:

```bash
python kicktipp_tool.py predict \
  --team-a "some team" \
  --team-b "another team" \
  --p-a 0.36 \
  --p-draw 0.29 \
  --p-b 0.35 \
  --total-goals 2.45
```

## Repository Map

- `kicktipp_tool.py`: CLI parsing and prediction workflow.
- `models.py`: Poisson model, expected-goal derivation, and result models.
- `scoring.py`: Kicktipp points, expected value, and ranked tips.
- `config.py`: `.env` configuration loading.
- `data_sources/cache.py`: cache path, TTL, read, and write helpers.
- `data_sources/elo.py`: local and remote Elo loading.
- `data_sources/fixtures.py`: OpenFootball fixture loading.
- `data_sources/providers/`: The Odds API, football-data.org, and
  API-Football adapters.
- `data_sources/team_matching.py`: team name normalization and matching.
- `tests/`: focused pytest coverage for CLI, config, scoring, model, and data
  source behavior.

## Development Notes

- Prefer focused changes that preserve the existing module boundaries.
- Keep CLI behavior deterministic when tests use manual inputs or mocked data.
- Do not require live network access in tests.
- Avoid writing real API responses or generated cache contents into version
  control.
- Keep public errors and logs free of API keys; URL key parameters are
  redacted in CLI error handling.
- Follow the configured style: Python 3.11, Ruff line length 88, and the lint
  rules in `pyproject.toml`.

## Verification Before Handoff

For code changes, run the narrowest relevant tests first, then run:

```bash
python -m pytest
ruff check .
mypy .
```

If a command cannot be run locally, note the reason in the handoff.
