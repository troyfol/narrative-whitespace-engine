# Narrative Whitespace Engine (NWE)

> Config-driven, exec-grade media monitoring + narrative clustering + PR briefing generation for any industry sector

The Narrative Whitespace Engine is a Python pipeline that:

- Pulls **industry news** from RSS/Atom feeds (any sector — biotech, energy, tech, defense, etc.)
- Deduplicates and clusters stories into **macro narratives**
- Optionally **enriches RSS items** by fetching article bodies to improve clustering signal
- Scrapes **competitor press releases** (static HTML) and computes positioning metrics
- Uses an LLM (Anthropic or OpenAI) to generate a **mainstream-media hook** with **strict containment** and **verified quotes**
- Exports an executive-ready **Word (.docx) briefing** with full audit trails

Ships as a **desktop GUI** (PySide6) with live progress, log streaming, and config management — or run headless via CLI. Distributable as a single `.exe` via PyInstaller.

Built for **defensibility**: every run produces `run_manifest.json` with hashes, model metadata, prompt provenance, and deterministic settings. Failures don't crash the run — warnings are logged and surfaced in the final report's Appendix B.

**Ships with biotech defaults** — but everything is configurable. Change the `sector` field, swap in your RSS feeds, and you have a media intelligence engine for energy, tech, defense, or any other industry.

---

## Table of Contents

- [Why This Exists](#why-this-exists)
- [What It Produces](#what-it-produces)
- [Architecture](#architecture)
- [Quickstart](#quickstart)
- [Multi-Sector Usage](#multi-sector-usage)
- [Desktop GUI](#desktop-gui)
- [CLI Usage](#cli-usage)
- [Configuration](#configuration)
- [Feed Packs (Biotech Examples)](#feed-packs-biotech-examples)
- [Optional Features](#optional-features)
- [Output Structure](#output-structure)
- [Defensibility Checklist](#defensibility-checklist)
- [Debugging and Observability](#debugging-and-observability)
- [Testing](#testing)
- [Project Structure](#project-structure)
- [Building the Executable](#building-the-executable)
- [Troubleshooting](#troubleshooting)
- [Limitations](#limitations)
- [Accuracy & Legal Disclaimers](#accuracy--legal-disclaimers)
- [License](#license)

---

## Why This Exists

Comms, investor relations, and strategy teams across any industry are constantly asked:

- What narratives dominate the news cycle right now?
- How are competitors positioning their milestones and announcements?
- Where is the "whitespace" — what's not being claimed or emphasized?

NWE automates the first 80%:

- Collect -> dedup -> (optional) enrich -> cluster -> label macro narratives
- Extract competitor positioning signals from press releases
- Produce an exec briefing that can be reviewed, edited, and circulated

The tool ships with **biotech defaults** (RSS feeds, metrics lexicons), but every aspect is configurable via YAML. See [Multi-Sector Usage](#multi-sector-usage) for adapting to other industries.

---

## What It Produces

A single run creates a folder under `runs/<run_id>/` containing:

- `report.docx` — executive briefing (TOC, executive summary, narratives, competitor section, appendices). **Note:** After opening the report in Word, right-click the Table of Contents and select **"Update Field" → "Update entire table"** to populate page numbers.
- `run_manifest.json` — provenance, hashes, model/prompt metadata, warnings
- `logs.jsonl` — structured JSONL logs (phase-by-phase)
- `prompts/*.txt` — rendered prompt text files for auditability
- `stage_*.json` — phase artifacts used to build the report
- `config_resolved.yaml` — exact config used (after Pydantic validation)

---

## Architecture

NWE runs as a **four-phase pipeline**, driven from either the desktop GUI or CLI:

### Phase 1 — RSS Ingest -> Dedup -> Enrichment -> Clustering -> Macro Narrative Labeling

1. **Ingest** RSS/Atom entries within the lookback window
2. **Deduplicate** syndicated/near-duplicate stories using TF-IDF + cosine similarity
3. *(Optional)* **Sample** items per-feed and/or total caps to prevent feed dominance
4. *(Optional)* **Enrich** items by fetching full article bodies — dramatically improves clustering signal (silhouette scores from ~0.04 to 0.3+ in testing)
5. *(Optional)* **Quality gate** filters out ultra-short items (kept in stage JSON for traceability)
6. **Cluster** story vectors with K-means, selecting K via silhouette score (with weak-clustering guardrail + fallback)
7. *(Optional)* **Topic binning** replaces cluster labels with keyword-based bins when silhouette is weak
8. **Label** each cluster via LLM (strict JSON schema). The LLM is instructed to act as a `{sector} media analyst` — configurable per run.

### Phase 2 — Competitor Press Release Scrape + Positioning Metrics

- Scrape competitor press release URLs with polite retry/backoff
- Extract text via multi-strategy fallback (CSS selectors -> largest p-block -> body)
- Compute:
  - Readability (Flesch-Kincaid grade via `textstat`)
  - Hedging density per 1,000 words
  - Forward-looking statement detection + excerpt
  - VADER sentiment proxy (with domain-context exclusions)

### Phase 3 — LLM "Jargon Translator" (Strict Containment + Verification)

- Token counting and truncation via `tiktoken` (safe decoding; appends `[TRUNCATED]`)
- LLM generates a mainstream-media hook in strict JSON
- Post-verification checks:
  - **Multi-tier quote verification** — exact match, soft-verified (whitespace + quote normalization), ellipsis-aware (Unicode `...`)
  - Digit mismatch warnings (no invented numbers)
  - Trial phase claim warnings (Phase 3 vs Phase III patterns)

### Phase 4 — Word Document Generation (python-docx)

- Executive Summary (deterministic from pipeline data)
- Macro Narratives (coverage %, silhouette scores, representative headlines)
- Competitor Share of Voice (metrics + hook + verified quotes + verification status)
- Competitor Positioning Summary Table (readability, hedging density, VADER sentiment with min/median/max across all competitors)
- Per-competitor rankings (Rank N/M for readability, hedging, and sentiment)
- Appendix A: Methods & Limitations
- Appendix B: Data Quality Notes (all warnings, fallback decisions)
- TOC field code (auto-updates when opened in Word)

---

## Quickstart

### 1. Create and activate a virtual environment

**Recommended Python:** 3.10+ (tested on 3.10 through 3.13).

#### Windows PowerShell

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

#### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
pip install -r requirements-gui.txt   # PySide6 for the desktop GUI
```

### 3. Set your LLM API key

The env var name must match `llm.api_key_env` in your config file.

#### PowerShell (session-based)

```powershell
$env:OPENAI_API_KEY = "PASTE_YOUR_KEY_HERE"
python -c "import os; print('SET' if os.getenv('OPENAI_API_KEY') else 'MISSING')"
```

#### Linux / macOS

```bash
export OPENAI_API_KEY="sk-your-key-here"
```

### 4. Launch

**Desktop GUI (recommended for most users):**

```bash
python run_gui.py
```

**CLI (headless / scripted):**

```bash
python run_pipeline.py --config config/example_config.yaml
```

See [QUICKSTART.md](QUICKSTART.md) for a more detailed getting-started guide, including how to configure for different sectors.

---

## Multi-Sector Usage

NWE is designed to work for any industry. The `sector` field in your config controls how the LLM frames its analysis, and all domain-specific settings are configurable.

### Key config fields to change per sector

| Field | What it controls | Biotech default | Energy example | Tech example |
| ----- | ---------------- | --------------- | -------------- | ------------ |
| `pipeline.sector` | LLM persona ("You are a {sector} media analyst") | `"biotech"` | `"energy"` | `"tech"` |
| `report.title` | Report cover page title | `"Biotech Narrative Whitespace Briefing"` | `"Energy Sector Briefing"` | `"Tech Landscape Briefing"` |
| `report.impact_label` | Impact bullet section heading | `"Patient Impact"` | `"Market Impact"` | `"User Impact"` |
| `rss.feeds` | News sources | BioSpace, STAT, etc. | Utility Dive, OilPrice, etc. | TechCrunch, Ars Technica, etc. |
| `competitors` | Press release URLs | Pharma companies | Energy companies | Tech companies |
| `metrics.hedging_lexicon` | Domain hedging terms | Clinical hedging terms | Regulatory hedging terms | Product hedging terms |

### Steps to adapt for a new sector

1. Copy `config/example_config.yaml` as your starting point
2. Set `pipeline.sector` to your industry (e.g. `"energy"`)
3. Replace `rss.feeds` with industry-relevant RSS/Atom feeds
4. Set `report.title` and `report.impact_label` for your audience
5. Add your competitors and their press release URLs
6. Update `metrics` lexicons if needed (hedging terms, FLS keywords, domain-negative terms)

---

## Desktop GUI

The GUI wraps the full pipeline in a PySide6 desktop application with five tabs:

### Tab 1 — API / Model

- API key entry (paste directly, session-only, never saved to disk)
- Provider selection (OpenAI / Anthropic) with preset model lists
- Full LLM parameter control: temperature, top_p, max tokens, JSON mode, instructor toggle, tiktoken encoding

### Tab 2 — Feeds & Competitors

- RSS feed table (add/remove feeds, set lookback window and timeout)
- Competitor list with per-competitor press release URL management
- Inline editing for all fields

### Tab 3 — Settings

- Scrollable panels for every pipeline config section
- Industry sector field for LLM prompt context
- Checkable group boxes for optional features (sampling, quality gate, enrichment, topic binning)
- Full control over dedup thresholds, clustering parameters, scraping settings, metrics lexicons, report metadata, and logging

### Tab 4 — Run

- **Start Pipeline** / **Stop Pipeline** / **Sample Run** buttons
- Live progress bar with per-phase status indicators (color-coded: pending -> active -> done/failed)
- Real-time log viewer with level filtering (DEBUG/INFO/WARNING/ERROR)
- Per-URL enrichment progress (index N of M) so you can tell the pipeline is working during long enrichment phases
- Abort takes effect at phase boundaries (cannot interrupt mid-LLM-call)

### Tab 5 — Results

Four sub-tabs populated after a run completes:

| Sub-tab | Content |
| ------- | ------- |
| **Summary** | Run ID, timestamps, config hash, warning count, "Open Report" and "Open Folder" buttons |
| **Narratives** | Tree view of clusters with titles, summaries, and expandable member headlines |
| **Competitors** | Table with name, word count, FK grade, hedging density, FLS count, VADER compound, error status |
| **Warnings** | Sortable table of all pipeline warnings (category, message, source) |

### Menu Bar

- **File > Load YAML** — load any existing config file (validated through the engine's Pydantic schema)
- **File > Save YAML** — export current form state as a valid pipeline config
- **File > Exit**
- **Help > About**

### Threading Model

The GUI stays responsive during pipeline execution:

- **PipelineWorker** (QThread) runs phases 1-4 sequentially, emitting progress signals
- **LogWatcher** (QThread) tails `logs.jsonl` and streams parsed records to the log viewer
- All inter-thread communication via Qt signals (queued, thread-safe)

---

## CLI Usage

### Dry run (validate config only; no network; no token spend)

```bash
python run_pipeline.py --config config/my_config.yaml --dry-run
```

Prints the resolved config as JSON and exits. No network calls, no files written.

### Full live run (Phases 1-4)

```bash
python run_pipeline.py --config config/my_config.yaml
```

### Sample run (offline fixtures; no network; no API key required)

```bash
python run_pipeline.py --config config/example_config.yaml --sample-run
```

Runs an end-to-end smoke test using bundled test fixtures. Useful for verifying the installation without consuming API tokens. Also available via the "Sample Run" button in the GUI.

### Exit codes

| Code | Meaning |
| ---- | ------- |
| 0 | Success (warnings allowed) |
| 2 | Config validation failure (human-readable list) |
| 1 | Unexpected fatal error |

---

## Configuration

All pipeline behavior is controlled via YAML config (except secrets, which use env var indirection). Configs can be loaded, edited, and saved through the GUI or managed as files directly. See [docs/CONFIG_REFERENCE.md](docs/CONFIG_REFERENCE.md) for field-by-field documentation.

### Config sections

| Section | Purpose |
| ------- | ------- |
| `pipeline` | Run identity (name, description, sector) |
| `rss` | Feed sources, lookback window, timeout |
| `dedup` | Similarity threshold + TF-IDF vectorizer params |
| `clustering` | K-range, silhouette guardrails, fallback K, random seed |
| `llm` | Provider/model, env-var key name, temperature, token limits, encoding |
| `scraping` | User-agent, polite delays, backoff, extraction selectors |
| `competitors` | Press release URLs per competitor |
| `metrics` | Hedging, FLS, and domain-negative lexicons + context exclusions |
| `validation` | Narrative similarity threshold for duplicate warnings |
| `report` | Document title, subtitle, author, TOC toggle, impact label |
| `sampling` | *(optional)* Per-feed and total caps to prevent feed dominance |
| `enrichment` | *(optional)* Fetch full article bodies to improve clustering |
| `quality_gate` | *(optional)* Filter garbage-short items before clustering |
| `topic_binning` | *(optional)* Keyword-based topic bins as cluster fallback |
| `logging` | Log level (DEBUG/INFO/WARNING/ERROR/CRITICAL) + structured flag |

### LLM providers

NWE supports both **OpenAI** and **Anthropic** as LLM providers. Set `llm.provider` to `"openai"` or `"anthropic"` and `llm.api_key_env` to the corresponding environment variable name. Use `llm.tiktoken_encoding` to match your model's tokenizer (`cl100k_base` for GPT-4/3.5, `o200k_base` for GPT-4o/Anthropic).

---

## Feed Packs (Biotech Examples)

NWE ships with biotech-focused config files as examples. Users in other sectors should create their own configs following the same structure.

| Skew | Focus | Config |
| ---- | ----- | ------ |
| **A** | Trials / Clinical | `config/live_A_trials.yaml` |
| **C** | Deals / Finance / Commercial | `config/live_C_deals.yaml` |

Recommended workflow:

1. Run each skew and compare silhouette scores, cluster sizes, and narrative quality
2. Use the one that best fits your intelligence needs, or run all weekly

All skew configs ship with sampling enabled (`per_feed_cap: 25`, `total_cap: 100`) and high-volume structured-data domains blocked from enrichment to keep run times manageable.

---

## Optional Features

All optional features default to `enabled: false` and can be toggled independently in your config or via the GUI's checkable group boxes in the Settings tab.

### Article Enrichment

Fetches full article bodies from RSS links to provide richer text for TF-IDF clustering. In testing, enabling enrichment improved silhouette scores from ~0.04 to 0.3+.

```yaml
enrichment:
  enabled: true
  request_timeout_seconds: 15
  blocked_domains:             # Skip domains that serve structured data, not articles
    - "dailymed.nlm.nih.gov"
    - "ema.europa.eu"
  min_chars: 200
  retry:
    max_retries: 2
    backoff_base: 2.0
    retryable_statuses: [429, 500, 502, 503, 504]
```

Enrichment runs after dedup/sampling and before the quality gate. Failures emit warnings but don't crash the pipeline (partial-success semantics). Items gain `enriched_clean_text_for_llm` and `enriched_clean_text_for_nlp` fields, which clustering and topic binning prefer over the shorter title+summary text.

Per-URL progress is logged to `logs.jsonl` (and streamed live in the GUI) so you can track enrichment progress during long runs.

### Feed Sampling / Caps

Prevents a single prolific feed from dominating cluster assignments. Recommended when using high-volume feeds.

```yaml
sampling:
  enabled: true
  strategy: newest_first       # or "random" for seeded random sampling
  per_feed_cap: 25             # max items per feed
  total_cap: 100               # max total items after per-feed cap
  random_seed: 42              # deterministic sampling (random strategy only)
```

### Quality Gate

Filters ultra-short items that degrade clustering. Items failing the gate are excluded from clustering/LLM but kept in stage JSON with `quality_gate_dropped: true` for traceability.

```yaml
quality_gate:
  enabled: true
  min_chars: 200
  min_words: 40
```

The quality gate runs **after** enrichment so enriched text counts toward thresholds.

### Topic Binning (Cluster Fallback)

When silhouette is weak and clustering produces "mixed-topic soup," keyword-based bins provide structure.

```yaml
topic_binning:
  enabled: true
  use_as_cluster_fallback: true
  bins:
    - name: "Regulatory"
      keywords: ["FDA", "EMA", "approval", "clearance", "label"]
    - name: "Trials"
      keywords: ["Phase 1", "Phase 2", "Phase 3", "enrollment", "endpoint"]
    - name: "Deals"
      keywords: ["acquisition", "merger", "partnership", "licensing"]
```

Topic binning only activates when `use_as_cluster_fallback: true` AND the silhouette optimizer fell back to the fallback K.

---

## Output Structure

Every run writes exclusively to `runs/<run_id>/`:

```
runs/<run_id>/
    run_manifest.json              # Full provenance record
    config_resolved.yaml           # Validated config snapshot
    prompts/                       # Rendered prompt text files
        macro_label_<hash>.txt
        phase3_<competitor>_<hash>.txt
    stage_1_rss_ingest.json        # Raw RSS entries + metadata
    stage_2_dedup.json             # Dedup groups + unique articles
    stage_3_clusters.json          # Clusters + optional stats
    stage_4_macro_labels.json      # LLM-generated narrative labels
    stage_5_press_release_scrape_metrics.json  # Scrape results + metrics
    stage_6_hook_translations.json # LLM translations + verification
    report.docx                    # Executive briefing (Word)
    logs.jsonl                     # Structured event log
```

No files are written outside `runs/<run_id>/` (config and resources are read-only).

### What each stage file contains

| File | Contents |
| ---- | -------- |
| `stage_1_rss_ingest.json` | All ingested RSS entries with source attribution, timestamps, standardized text |
| `stage_2_dedup.json` | Original vs. deduplicated counts, dedup groups showing which articles were merged |
| `stage_3_clusters.json` | Cluster assignments, silhouette scores, plus `sampling_stats`, `enrichment_stats`, `quality_gate_stats`, `topic_binning` when those features are enabled |
| `stage_4_macro_labels.json` | LLM-generated narrative title + summary per cluster, coverage percentages, similarity warnings |
| `stage_5_press_release_scrape_metrics.json` | Per-URL scrape results, extraction method, readability/hedging/FLS/VADER/tone metrics |
| `stage_6_hook_translations.json` | Hook headlines, mainstream summaries, verified quotes with tier status, digit/phase warnings |
| `report.docx` | Complete executive briefing with TOC, exec summary, narratives, competitor analysis, positioning summary table, appendices |

---

## Defensibility Checklist

Every run produces artifacts designed for audit and compliance:

| Artifact | What it proves |
| -------- | -------------- |
| `run_manifest.json` | Complete provenance: run ID, timestamps, config hash, git commit, LLM model/provider, package versions, determinism settings |
| `prompts/` directory | Exact text sent to the LLM — stored with SHA-256 hash for tamper detection |
| `prompt_hashes` in manifest | Map of prompt purpose -> SHA-256 hash, cross-referenced with stored files |
| `input_hashes` in manifest | SHA-256 hashes of RSS payloads and scraped HTML — proves what data was ingested |
| Stage JSON files (1-6) | Complete intermediate results at every pipeline step — full audit trail |
| `config_resolved.yaml` | Exact config used (after Pydantic validation), no ambiguity about settings |
| Appendix B in report | All data quality warnings: soft-verified quotes, digit mismatches, scrape failures, weak clustering, etc. |
| `logs.jsonl` | Structured event log with timestamps for every pipeline operation |

---

## Debugging and Observability

### Where to look first

- `runs/<run_id>/logs.jsonl` — phase-by-phase events, warnings, errors
- `runs/<run_id>/run_manifest.json` — provenance, hashes, model info, determinism settings
- `runs/<run_id>/stage_*.json` — what each phase produced
- **GUI Run tab** — live log viewer with level filtering and per-URL enrichment progress

### Enable DEBUG logging

```yaml
logging:
  level: "DEBUG"
  structured: true
```

### Quick PowerShell: show warnings and errors for latest run

```powershell
$run = Get-ChildItem runs -Directory | Sort-Object LastWriteTime -Descending | Select-Object -First 1
$log = Join-Path $run.FullName "logs.jsonl"
"Newest run: $($run.FullName)"
Select-String -Path $log -Pattern '"level":"WARNING"|"level":"ERROR"'
```

---

## Testing

```bash
pytest tests/ -v
```

The test suite (553 tests) covers:

- Config validation (Pydantic v2 schema, range checks, cross-field validators)
- URL canonicalization and text standardization
- Deduplication grouping and determinism
- Clustering determinism and silhouette selection
- Multi-tier quote verification (exact, soft, Unicode ellipsis)
- Digit mismatch and phase claim detection
- Safe token truncation
- Report generation (including positioning summary table and competitor rankings)
- Article enrichment (domain blocking, retry on 429/5xx, partial failure)
- Feed sampling (per-feed caps, total caps, newest-first and random strategies, determinism with seed)
- Quality gate (threshold filtering, enriched text fallback)
- Topic binning (keyword matching, first-match priority, unassigned items)
- End-to-end integration smoke tests with mocked LLM responses

---

## Project Structure

```
narrative-whitespace-engine/
    run_gui.py                         # GUI entry point (PySide6)
    run_pipeline.py                    # CLI entry point (argparse)
    requirements.txt                   # Pipeline dependencies
    requirements-gui.txt               # GUI dependencies (PySide6)
    QUICKSTART.md                      # Getting started guide
    NarrativeWhitespaceEngine.spec     # PyInstaller build config
    _pyinstaller_runtime_hook.py       # Runtime hook for frozen builds
    AIG.ico                            # Application icon
    config/
        example_config.yaml            # Production-ready config template
        live_A_trials.yaml             # Biotech Skew A: Trials/Clinical
        live_C_deals.yaml              # Biotech Skew C: Deals/Finance/Commercial
    docs/
        CONFIG_REFERENCE.md            # Field-by-field config docs
        REAL_RUN_CHECKLIST.md          # Operational checklist
    src/
        __init__.py
        config_schema.py               # Pydantic v2 config validation
        config_loader.py               # YAML -> PipelineConfig
        rss_ingest.py                  # RSS fetch + parse + window filtering
        text_standardizer.py           # Text cleaning (LLM + NLP dual tracks)
        dedup.py                       # TF-IDF cosine deduplication
        clustering.py                  # KMeans + silhouette K selection
        article_enrichment.py          # Article body enrichment (fetch + extract)
        sampling.py                    # Per-feed and total caps
        topic_binning.py               # Keyword-based topic binning
        llm_client.py                  # LLM calls (Anthropic/OpenAI + instructor)
        llm_prompts.py                 # Prompt templates + Pydantic response schemas
        press_release_scrape.py        # HTTP fetch + HTML extraction + backoff
        metrics.py                     # Readability, hedging, FLS, VADER, tone
        validation.py                  # Quote verification, digit/phase checks
        report_docx.py                 # Word document generation with styles
        provenance.py                  # Run init + manifest writing
        logging_utils.py               # Structured JSON logging (JSONL)
        utils.py                       # Shared utilities (canonicalize, truncate, hash)
        exceptions.py                  # Custom exceptions + PipelineWarning dataclass
    gui/
        __init__.py
        main_window.py                 # QMainWindow + 5 tabs + menu bar + status bar
        config_bridge.py               # GUI forms <-> PipelineConfig <-> YAML
        style.py                       # Dark-theme QSS stylesheet + colour constants
        resources.py                   # Path resolution (dev + PyInstaller frozen)
        tabs/
            __init__.py
            api_model_tab.py           # Tab 1: API key, provider, model, LLM params
            feeds_comps_tab.py         # Tab 2: RSS feeds + competitors
            settings_tab.py            # Tab 3: All pipeline config sections
            run_tab.py                 # Tab 4: Start/stop, progress, live logs
            results_tab.py             # Tab 5: Run output viewer (5 sub-tabs)
        workers/
            __init__.py
            pipeline_worker.py         # QThread — runs phases 1-4
            log_watcher.py             # QThread — tails logs.jsonl
    tests/
        fixtures/                      # RSS, HTML, and LLM response test fixtures
        test_*.py                      # 553 tests across 26 test modules
    Makefile                           # install / test / run helpers
```

---

## Building the Executable

NWE can be packaged as a single `.exe` using PyInstaller. A pre-configured `.spec` file handles all data bundling, hidden imports, and conda DLL resolution:

```bash
pip install pyinstaller
pyinstaller NarrativeWhitespaceEngine.spec --clean --noconfirm
```

The resulting `dist/NarrativeWhitespaceEngine.exe` (~160 MB) is a self-contained executable that bundles:

- Python runtime + all dependencies
- PySide6 GUI framework
- tiktoken encoding cache
- Config templates, resources, and test fixtures (for sample runs)
- Conda DLLs (sqlite3, lzma, bz2, expat, mpdec, ffi)

The `gui/resources.py` module handles path resolution for both development (`python run_gui.py`) and frozen (PyInstaller `_MEIPASS`) environments. When frozen, `runs/` output is written next to the `.exe` (not inside the temp extraction folder) so output persists after the process exits.

A runtime hook (`_pyinstaller_runtime_hook.py`) sets `TIKTOKEN_CACHE_DIR` so bundled encodings are found without network access.

**Note:** The `.spec` file resolves all paths dynamically from the active Python environment. No machine-specific paths are hardcoded — it should work on any machine with the same dependencies installed.

---

## Troubleshooting

### "No API key was entered" (GUI) / "API key environment variable is not set" (CLI)

**GUI:** Paste your API key directly in the API / Model tab before clicking Start Pipeline. The key is held in memory only — never written to disk.

**CLI:** Your process can't see the env var specified by `llm.api_key_env` in your config.

```powershell
$env:OPENAI_API_KEY = "PASTE_YOUR_KEY_HERE"
python -c "import os; print('SET' if os.getenv('OPENAI_API_KEY') else 'MISSING')"
```

### Enrichment appears stuck

Enrichment fetches full article bodies with polite delays (1.5-3s per URL) and retries on timeout. With 77+ URLs, this can take several minutes. The GUI's live log viewer shows per-URL progress (`enrichment_item_start index=N total=M`) so you can confirm it's advancing.

To speed up enrichment:

- **Enable sampling** (`per_feed_cap: 25`, `total_cap: 100`) to reduce item count before enrichment
- **Block high-volume structured-data domains** in `enrichment.blocked_domains`

### Blocked scrapes (403/429/captcha)

The scraper uses configurable exponential backoff but will not bypass authentication or CAPTCHAs. If a URL returns 403 or 429:

- The pipeline logs a warning and continues (partial success semantics)
- The competitor appears in the report with "Scrape failed" status
- Check `scraping.user_agent` — some sites block generic user agents
- Consider finding a static HTML distribution copy (GlobeNewswire, BusinessWire, AccessNewswire, PRNewswire)

### Scrape extracted text too short (0 chars, 0 words)

Usually means JS-rendered content, consent interstitials, or non-matching CSS selectors. Switch to a static HTML press release distribution copy or add a site-specific `extraction_selectors` entry.

### Context length truncation

If a press release is very long, the pipeline truncates it to `llm.max_input_tokens` before sending to the LLM. When this happens:

- A `text_truncated` warning appears in Appendix B
- Quote verification runs against the truncated text (the exact text the LLM saw)
- To reduce truncation: increase `llm.max_input_tokens` (check your provider's context window)

### Weak clustering (low silhouette scores)

If silhouette scores are below 0.1:

- **Enable enrichment** — this is the single biggest improvement (0.04 -> 0.3+ in testing)
- **Enable quality gate** — filters noise items that blur cluster boundaries
- **Enable feed sampling** — prevents one feed from dominating clusters
- **Enable topic binning** — provides keyword-based fallback structure
- Review your feed mix — feeds with very different content types cluster better

---

## Limitations

- **Not ground truth.** The system summarizes publicly available text and generates LLM outputs; it is a draft-generation tool requiring human review.
- **RSS coverage is incomplete.** Feeds are editorial selections; missing outlets means missing narratives.
- **Scraping is fragile.** Some sites block or render content client-side; prefer static distribution copies.
- **Sentiment is a proxy.** VADER is heuristic and can be skewed by domain-specific terminology (mitigated by domain-negative context exclusions).
- **Clustering quality depends on input signal.** Very short summaries yield low silhouette scores; enrichment and quality gates help substantially.

---

## Security Note

API keys are never stored in config files or saved by the GUI. In **GUI mode**, the key is pasted directly into the API / Model tab and held in memory only for that session — never written to disk. In **CLI mode**, the config references an environment variable name (`llm.api_key_env`) and the key is resolved at runtime. If no key is available, the pipeline exits with a clear error.

Never commit `.env` files or API keys to version control. Use your platform's secret management (environment variables, vault, CI secrets).

---

## Accuracy & Legal Disclaimers

### Accuracy disclaimer

Despite validation, containment, and provenance measures:

- Outputs may contain errors, omissions, or misleading framing
- LLM-generated text must be treated as a draft for human review
- Do not make high-stakes decisions without verifying against primary sources

### Legal / compliance disclaimer

- Intended for lawful use with **publicly accessible** RSS/Atom feeds and public press release pages
- You are responsible for complying with:
  - Website Terms of Service
  - robots.txt policies where applicable
  - Rate limiting and fair-use expectations
  - Internal policies regarding content storage and distribution
- This tool does not bypass paywalls or access controls and should not be used to do so

### Not legal, medical, or investment advice

Nothing produced by this pipeline constitutes legal, medical, investment, or regulatory advice.

---

## License

Add your organization's license here (MIT / Apache-2.0 / Proprietary), and ensure your usage aligns with third-party content policies for the sources you ingest.
