# Quickstart Guide

Get the Narrative Whitespace Engine running in under 10 minutes.

---

## 1. Prerequisites

- **Python 3.10+** (tested on 3.10 through 3.13)
- **pip** (ships with Python)
- An **LLM API key** — OpenAI or Anthropic

---

## 2. Install

### Windows PowerShell

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install -r requirements-gui.txt   # optional — needed for the desktop GUI
```

### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-gui.txt   # optional — needed for the desktop GUI
```

---

## 3. Set your API key

The engine reads your LLM key from an environment variable. The variable name is set in your config file under `llm.api_key_env` (default: `OPENAI_API_KEY`).

### PowerShell (session)

```powershell
$env:OPENAI_API_KEY = "sk-your-key-here"
```

### Bash

```bash
export OPENAI_API_KEY="sk-your-key-here"
```

To use **Anthropic** instead, set `llm.provider: "anthropic"` and `llm.api_key_env: "ANTHROPIC_API_KEY"` in your config, then export that variable.

---

## 4. Choose your sector

NWE ships with **biotech** as the default sector. To run for a different industry, change a few config fields:

| Field | What to set | Example |
| ----- | ----------- | ------- |
| `pipeline.sector` | Your industry keyword | `"energy"`, `"tech"`, `"defense"` |
| `report.title` | Report cover page title | `"Energy Sector Briefing"` |
| `report.impact_label` | Label for the impact bullet section | `"Market Impact"`, `"User Impact"` |
| `rss.feeds` | RSS/Atom feed URLs for your sector | Your industry news sources |
| `competitors` | Competitor names + press release URLs | Your competitive set |

If you're running for biotech, the defaults work out of the box — just add your feeds and competitors.

---

## 5. Configure

### Option A: Desktop GUI (recommended)

```bash
python run_gui.py
```

The GUI has four setup tabs:

1. **API / Model** — paste your API key, pick provider and model
2. **Feeds & Competitors** — add RSS feeds and competitor press release URLs
3. **Settings** — sector, entity suffixes, clustering, report options, and more
4. **Run** — start the pipeline, watch progress in real time

You can save and load configs as YAML files from the toolbar.

### Option B: Edit YAML directly

Copy the example config and edit it:

```bash
cp config/example_config.yaml config/my_config.yaml
```

At minimum, set these fields:

```yaml
pipeline:
  sector: "biotech"           # or your sector

rss:
  feeds:
    - url: "https://example.com/feed.xml"
      name: "Example Feed"
  lookback_days: 7

llm:
  provider: "openai"
  model: "gpt-4o-mini"
  api_key_env: "OPENAI_API_KEY"

competitors:
  - name: "Competitor A"
    press_release_urls:
      - "https://example.com/press/release-1"
```

See [docs/CONFIG_REFERENCE.md](docs/CONFIG_REFERENCE.md) for every available field.

---

## 6. Run

### GUI

Click **Start Pipeline** on the Run tab. Progress and logs stream in real time.

### CLI (headless)

```bash
python run_pipeline.py --config config/my_config.yaml
```

A typical run with 5 feeds and 3 competitors takes 2-5 minutes depending on LLM response times and scraping delays.

---

## 7. Review output

Each run creates a folder under `runs/<run_id>/` containing:

| File | What's inside |
| ---- | ------------- |
| `report.docx` | Executive briefing — open in Word (TOC auto-updates on open) |
| `run_manifest.json` | Provenance: hashes, model metadata, prompt info, warnings |
| `logs.jsonl` | Structured JSON logs, phase by phase |
| `prompts/*.txt` | Rendered LLM prompts for auditability |
| `stage_*.json` | Intermediate phase artifacts |
| `config_resolved.yaml` | Exact config used after Pydantic validation |

The **report.docx** includes:

- Executive Summary (macro narratives + competitor count)
- Macro Narratives section (cluster labels, coverage %, representative headlines)
- Competitor section (positioning metrics, hook translations, verified quotes)
- Competitor Positioning Summary Table (readability, hedging density, sentiment)
- Appendix A: Methods & Limitations
- Appendix B: Data Quality Notes (all warnings and fallback decisions)

---

## 8. Customize further

- **[docs/CONFIG_REFERENCE.md](docs/CONFIG_REFERENCE.md)** — field-by-field reference for every config option
- **[README.md](README.md)** — full architecture, optional features, debugging, testing, and more

### Optional features to explore

| Feature | Config section | What it does |
| ------- | -------------- | ------------ |
| **Sampling** | `sampling` | Cap items per feed and/or total to prevent single-feed dominance |
| **Enrichment** | `enrichment` | Fetch full article bodies from RSS links for richer clustering |
| **Quality gate** | `quality_gate` | Filter out ultra-short items before clustering |
| **Topic binning** | `topic_binning` | Keyword-based topic pre-segmentation as a clustering fallback |

---

## 9. Example sector configs

### Biotech (ships with repo)

The default config is ready for biotech. Key defaults:

```yaml
pipeline:
  sector: "biotech"
report:
  title: "Biotech Narrative Whitespace Briefing"
  impact_label: "Patient Impact"
```

### Energy (template)

```yaml
pipeline:
  sector: "energy"
report:
  title: "Energy Sector Narrative Briefing"
  impact_label: "Market Impact"
metrics:
  hedging_lexicon: ["preliminary", "estimated", "projected", "anticipated", "subject to"]
  fls_keywords: ["forecast", "outlook", "guidance", "expects", "plans to"]
```

### Tech (template)

```yaml
pipeline:
  sector: "tech"
report:
  title: "Tech Landscape Narrative Briefing"
  impact_label: "User Impact"
metrics:
  hedging_lexicon: ["beta", "experimental", "early access", "preliminary", "estimated"]
  fls_keywords: ["roadmap", "plans to", "expects", "upcoming", "will launch"]
```

### Defense (template)

```yaml
pipeline:
  sector: "defense"
report:
  title: "Defense & Aerospace Narrative Briefing"
  impact_label: "Stakeholder Impact"
metrics:
  hedging_lexicon: ["anticipated", "projected", "estimated", "contingent", "subject to"]
  fls_keywords: ["contract", "award", "expects", "plans to", "will deliver"]
```

---

## Troubleshooting

| Problem | Fix |
| ------- | --- |
| `LLMFormatError: API key not set` | Export the env var matching `llm.api_key_env` in your config |
| TOC shows field codes in Word | Right-click the TOC and select "Update Field" → "Update entire table" |
| Low silhouette scores / weak clusters | Enable `enrichment` to fetch article bodies, or add `topic_binning` as a fallback |
| GUI won't launch | Install GUI dependencies: `pip install -r requirements-gui.txt` |
