# Contributor research

This Streamlit app analyzes contributors to a public GitHub repository. GitHub supplies repository and contributor facts. A live run uses Tavily to find identity-matched public sources. Results remain available for review and JSON export.

The app does **not** infer malicious intent, nationality, citizenship, immigration status, or U.S.-person eligibility. Missing or ambiguous public information is a research gap, not a rating of a contributor.

## Run the app

Install [uv](https://docs.astral.sh/uv/), then run:

```bash
cp .env.example .env
# Add your Tavily API key to .env
uv sync
uv run streamlit run app.py
```

The app opens at `http://localhost:8501`. You can also enter credentials through **Settings**.

## Configuration

Required:

- `TAVILY_API_KEY`

Optional:

- `GITHUB_TOKEN` for a larger GitHub REST API allowance
- `TAVILY_PROJECT_ID` for Tavily usage attribution

Credentials stay in the process environment or current app session. They are not included in reports or exports.

## Use

1. Choose one of the suggested repositories or enter another public GitHub repository.
2. Add a Tavily API key under **Settings**.
3. Select **Run analysis**.
4. Review the Overview, Contributors, Evidence, and Export tabs.

The most recent completed analysis is stored locally in `data/latest_live_report.json`; a new run replaces it. That generated file is excluded from Git. This repository does not include saved contributor reports or profile snapshots.

## Responsible use

This tool gathers public information about real people. Confirm identity matches manually, respect source terms and applicable law, and do not use its output as an automated employment, access, legal-status, or security determination. See [NOTICE.md](NOTICE.md).

## Development

```bash
uv run pytest
```

Tests use in-memory synthetic data and fakes; they do not call GitHub or Tavily.

## Project structure

```text
app.py                              Streamlit interface and local report persistence
contributor_lens/github_client.py  GitHub repository and profile ingestion
contributor_lens/tavily_client.py  Tavily Search, Extract, and identity matching
contributor_lens/scoring.py        Evidence measures and public-source outcomes
contributor_lens/export.py         Provenance-aware JSON report
contributor_lens/pipeline.py       Live orchestration and serialization
assets/fonts/                       Inter font and SIL Open Font License
tests/                              Offline unit tests
docs/METHODOLOGY.md                 Methodology, limits, and validation notes
```

## Interface assets

The interface uses the Inter typeface, distributed under the SIL Open Font License in [assets/fonts/OFL.txt](assets/fonts/OFL.txt). Tavily is named only to identify the service used by the demo. This repository does not contain Tavily or Nebius logo files or other proprietary brand artwork.

## License

The project source code is available under the [MIT License](LICENSE). Inter remains separately licensed under its included SIL Open Font License.
