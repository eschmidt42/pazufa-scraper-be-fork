<div align="center">

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
&nbsp;&nbsp;
[![Python](https://img.shields.io/badge/Python-3.12+-blue.svg)](https://www.python.org/)
[![Scrapy](https://img.shields.io/badge/Scrapy-2.16+-green.svg)](https://scrapy.org/)
[![Pydantic v2](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/pydantic/pydantic/main/docs/badge/v2.json)](https://pydantic.dev)
&nbsp;&nbsp;
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![ty](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ty/main/assets/badge/v0.json)](https://github.com/astral-sh/ty)
[![prek](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/j178/prek/master/docs/assets/badge-v0.json)](https://github.com/j178/prek)
&nbsp;&nbsp;
[![CI: Quality Control](https://ci.codeberg.org/api/badges/16670/status.svg?workflow=quality-control)](https://ci.codeberg.org/repos/16670)
[![CI: Build Docker](https://ci.codeberg.org/api/badges/16670/status.svg?workflow=build-and-publish-image)](https://ci.codeberg.org/repos/16670)
&nbsp;&nbsp;
[![Docker Image Latest](https://img.shields.io/docker/v/sejaeger/pazufa-scraper-be?label=Docker-latest)](https://hub.docker.com/r/sejaeger/pazufa-scraper-be/tags)
[![Docker Image Latest Tag](https://img.shields.io/docker/v/sejaeger/pazufa-scraper-be?sort=semver&label=Docker)](https://hub.docker.com/r/sejaeger/pazufa-scraper-be/tags)

</div>

---

# `pazufa-scraper-be` — Abgeordnetenhaus von Berlin

A scraper for the [Abgeordnetenhaus von Berlin](https://www.abgeordnetenhaus-berlin.de/) parliament, part of the
[Parlamentszusammenfasser](https://codeberg.org/PaZuFa/parlamentszusammenfasser) (PaZuFa) platform
([pazufa.de](https://pazufa.de)).

Built with [Scrapy](https://scrapy.org/) (crawling & item pipelines), [pydantic](https://docs.pydantic.dev/) (data validation),
[xberg](https://xberg.io/) (PDF extraction), and
[pazufa-corelib](https://codeberg.org/PaZuFa/pazufa-scraper-core) (pazufa backend api client & LLM summaries).

---

## Setup

Requires Python 3.12+.

```bash
uv install
```

## Usage

```bash
# run a spider for current 'wahlperiode'
scrapy runspider pazufa_scraper_be/spiders/gesetz_vorgang.py
```

Using `-s`, you can change scrapy settings.
Check out [the settings.py file](./pazufa_scraper_be/settings.py) for more details.
You might be interested in the following:

| Setting | Default | Description |
| -- | -- | -- |
| `LOG_LEVEL` | `INFO` | Set log level for std out. |
| `WAHLPERIODE` | `19` | Set which wahlperiode to scrape. |

There are a some settings, which activate certain features.

| Setting | Env Var | Default | Description |
| -- | -- | -- | -- |
| `API_TOKEN` | `PAZUFA_API_TOKEN` | `None` | Activates submission to PaZuFa API. Used for authentication and is handed out by backend developer/hoster. |
| `API_URL` | `PAZUFA_API_URL` | `http://localhost:8080` | Required if `API_TOKEN` is set. Used to point to a certain backend/API (local, staging, prod). |
| `LLM_TOKEN` | `PAZUFA_LLM_TOKEN` | `None` | Activates generation of summaries using LLM. |
| `LLM_MODEL` | `PAZUFA_LLM_MODEL` | `openrouter/openai/gpt-5-nano` | Required if `LLM_TOKEN` is set. Choose which model to use from [openrouter.ai](https://openrouter.ai/models?input_modalities=text). |
| `LLM_TIMEOUT` | `PAZUFA_LLM_TIMEOUT` | `300` | Required if `LLM_TOKEN` is set. Timeout for LLM API calls in seconds. |
| `MATTERMOST_TOKEN` | `PAZUFA_MATTERMOST_TOKEN` | `None` | Activates notifications to Mattermost. |
| `MATTERMOST_URL` | `PAZUFA_MATTERMOST_URL` | `https://chat.pazufa.de/hooks` | Required if `MATTERMOST_TOKEN` is set. Mattermost webhook URL. |

For usage via docker see [docker/](./docker/) and [docs](./docker/README.md).

## Development

### Code Hygiene

If you want to make use of git hooks run

```bash
prek install
```

to install and

```bash
prek run --all-files
```

to run all hooks for all files.

For more fine-grained control use

```bash
# linting
prek run ruff-check --all-files
# formatting
prek run formatting --all-files
# type checking
prek run ty --all-files
# testing
prek run test --all-files
```

### Testing

Unit and integration tests are organized as

```text
tests
├── integration
└── unit
    └── pazufa_scraper_be
        ├── conftest.py & helpers.py
        └── {module/}test_{module}.py
```

#### Unit Tests

To run unit tests use

```bash
pytest
pytest tests/unit
```

To get the test coverage run

```bash
pytest --cov
```

or

```bash
pytest --cov --cov-report=html
```

to create a `htmlcov/` directory with the results. Run

```bash
open htmlcov/index.html
```

for an interactive overview.

#### Integration Tests

The objective is to check that the `ITEM_PIPELINES`, given the same `xml` feed, produce the same output (at least when it comes to deterministic fields, not llm summaries or similar). We want to do this for several Vorgänge.

So essentially what we want to do is trace the pipeline executions. We use `mlflow` here for that.

To do the tracing of the pipelines itself we wrap the `.process_item` methods, snapshot their inputs and outputs.

To create reference traces to later compare against run

```bash
uv run python scripts/create_integration_test_references.py
```

before you do any changes to the pipelines. This writes the traces to `tests/integration-tests-mlflow.db`.

Those traces can be visually inspected in your browser when you start an mlflow server, e.g. using

```bash
mlflow server \
  --backend-store-uri "sqlite:////absolute/path/above/to/tests/integration-tests-mlflow.db" \
  --host 127.0.0.1 \
  --port 5000
```

Then after you've done your code changes to the pipelines you can re-run the same Vorgänge (make sure the feed file is unchanged) using

```bash
uv run pytest -m integration
```

The `integration` marked test(s) does a limited sanity check of the pipeline outputs for you. If the test(s) fail you should be provided with `item_id` / Vorgang ID identifiers.

To help you understand the differences between the reference run and the test run the notebook [`notebooks/test-and-reference-run-diff.ipynb`](./notebooks/test-and-reference-run-diff.ipynb) is provided for you. It let's you inspect the inputs and outputs of each run side by side, highlighting differences.
