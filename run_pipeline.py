#!/usr/bin/env python3
"""
Narrative Whitespace Engine — CLI entry point.

Usage
-----
::

    python run_pipeline.py --config config/example_config.yaml
    python run_pipeline.py --config config/example_config.yaml --dry-run

Exit codes
----------
0  Success (warnings allowed).
2  Config validation failure.
1  Unexpected fatal error.
"""

from __future__ import annotations

import argparse
import sys
import traceback
from pathlib import Path
from typing import Any

from src.article_enrichment import enrich_items
from src.clustering import (
    choose_k_by_silhouette,
    cluster_items,
    cluster_representatives,
    vectorize_items,
)
from src.config_loader import load_config
from src.config_schema import PipelineConfig
from src.dedup import deduplicate_items
from src.exceptions import PipelineWarning
from src.sampling import sample_items
from src.topic_binning import assign_bins
from src.llm_client import label_macro_narrative, translate_press_release
from src.llm_prompts import (
    HookTranslationResponse,
    MacroLabelResponse,
    build_hook_translation_prompt,
    build_macro_label_prompt,
)
from src.logging_utils import RunLogger, get_run_logger
from src.metrics import compute_all_metrics, tone_polarity_warning
from src.press_release_scrape import scrape_press_release
from src.provenance import init_run, write_run_manifest
from src.report_docx import build_report
from src.rss_ingest import ingest_rss



from src.text_standardizer import standardize
from src.utils import sha256_bytes, truncate_text_to_max_tokens, write_stage_json
from src.validation import (
    digit_mismatch_warnings,
    narrative_similarity_warnings,
    phase_claim_warnings,
    verify_two_quotes,
)


# ── CLI ───────────────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_pipeline",
        description="Narrative Whitespace Engine Pipeline.",
    )
    parser.add_argument(
        "--config",
        required=True,
        help="Path to the YAML configuration file.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Validate config and print resolved values; no network calls.",
    )
    parser.add_argument(
        "--sample-run",
        action="store_true",
        default=False,
        help=(
            "Run the full pipeline end-to-end using test fixtures — "
            "no network calls, no API key needed.  Produces a real "
            "runs/<run_id>/ directory with report.docx for inspection."
        ),
    )
    return parser


# ── Phase 1 orchestration ─────────────────────────────────────────────────

def run_phase1(
    config: PipelineConfig,
    run_ctx: dict[str, Any],
    logger: RunLogger,
) -> dict[str, Any]:
    """Execute Phase 1: RSS ingest → dedup → entities/clustering → LLM labeling.

    Returns a dict with keys ``warnings``, ``prompt_hashes``,
    ``input_hashes``, ``model_provenance`` for manifest enrichment.
    """
    warnings: list[PipelineWarning] = []
    prompt_hashes: dict[str, str] = {}
    input_hashes: dict[str, Any] = {}
    model_provenance: dict[str, str] = {}

    run_dir = Path(run_ctx["run_dir"])

    # ── 1.1  RSS ingest ───────────────────────────────────────────────
    logger.info("phase1_rss_start")

    feeds = [{"url": f.url, "name": f.name} for f in config.rss.feeds]
    entries, rss_warnings, window_start, window_end = ingest_rss(feeds, config, logger)
    warnings.extend(rss_warnings)

    # Standardize text for each entry.
    for entry in entries:
        combined = f"{entry['title']} {entry['summary']}"
        std = standardize(combined)
        entry["clean_text_for_llm"] = std["clean_text_for_llm"]
        entry["clean_text_for_nlp"] = std["clean_text_for_nlp"]

    # Record input hashes from raw_entry provenance.
    input_hashes["rss_entry_hashes"] = [e["raw_hash"] for e in entries]
    input_hashes["rss_entry_count"] = len(entries)

    write_stage_json(run_dir / "stage_1_rss_ingest.json", {
        "stage": "rss_ingest",
        "entry_count": len(entries),
        "window_start": window_start,
        "window_end": window_end,
        "entries": [
            {
                "source_name": e["source_name"],
                "title": e["title"],
                "summary": e["summary"],
                "link": e["link"],
                "canonical_link": e["canonical_link"],
                "published_utc": e["published_utc"],
                "clean_text_for_llm": e["clean_text_for_llm"],
                "clean_text_for_nlp": e["clean_text_for_nlp"],
            }
            for e in entries
        ],
        "warnings": [w.to_dict() for w in rss_warnings],
    })
    logger.info("phase1_rss_complete", entry_count=len(entries))

    # ── 1.2  Deduplication ────────────────────────────────────────────
    logger.info("phase1_dedup_start")

    dedup_result = deduplicate_items(
        entries,
        similarity_threshold=config.dedup.similarity_threshold,
        tfidf_params=config.dedup.vectorizer.model_dump(),
    )
    deduped = dedup_result["deduped_items"]

    write_stage_json(run_dir / "stage_2_dedup.json", {
        "stage": "dedup",
        "input_count": len(entries),
        "deduped_count": len(deduped),
        "deduped_items": [
            {
                "source_name": e.get("source_name", ""),
                "title": e["title"],
                "summary": e["summary"],
                "canonical_link": e["canonical_link"],
                "published_utc": e["published_utc"],
            }
            for e in deduped
        ],
        "groups": dedup_result["groups"],
    })
    logger.info("phase1_dedup_complete", deduped_count=len(deduped))

    # ── 1.2a  Sampling (optional) ─────────────────────────────────────
    sampling_stats: dict[str, Any] | None = None
    if config.sampling.enabled:
        logger.info("phase1_sampling_start")
        pre_sample_count = len(deduped)
        sample_result = sample_items(
            deduped,
            per_feed_cap=config.sampling.per_feed_cap,
            total_cap=config.sampling.total_cap,
            strategy=config.sampling.strategy,
            random_seed=config.sampling.random_seed,
        )
        deduped = sample_result["sampled_items"]
        sampling_stats = {
            "input_count": pre_sample_count,
            "output_count": len(deduped),
            "dropped_count": pre_sample_count - len(deduped),
            "per_feed_counts": sample_result["per_feed_counts"],
        }
        logger.info(
            "phase1_sampling_complete",
            input_count=pre_sample_count,
            output_count=len(deduped),
        )

    # ── 1.2b  Article enrichment (optional) ───────────────────────────
    enrichment_stats: dict[str, Any] | None = None
    if config.enrichment.enabled:
        logger.info("phase1_enrichment_start")
        enrich_result = enrich_items(deduped, config.enrichment, config.scraping, logger=logger)
        deduped = enrich_result["enriched_items"]
        enrichment_stats = enrich_result["stats"]
        warnings.extend(enrich_result["warnings"])
        logger.info(
            "phase1_enrichment_complete",
            attempted=enrichment_stats["attempted"],
            succeeded=enrichment_stats["succeeded"],
            failed=enrichment_stats["failed"],
        )

    # ── 1.2c  Quality gate (optional) ─────────────────────────────────
    quality_gate_stats: dict[str, Any] | None = None
    dropped_items: list[dict[str, Any]] = []
    if config.quality_gate.enabled:
        logger.info("phase1_quality_gate_start")
        gate_min_chars = config.quality_gate.min_chars
        gate_min_words = config.quality_gate.min_words

        active_items: list[dict[str, Any]] = []
        for item in deduped:
            gate_text = (
                item.get("enriched_clean_text_for_llm")
                or item.get("clean_text_for_llm")
                or f"{item.get('title', '')} {item.get('summary', '')}"
            )
            if len(gate_text) >= gate_min_chars and len(gate_text.split()) >= gate_min_words:
                active_items.append(item)
            else:
                item["quality_gate_dropped"] = True
                dropped_items.append(item)

        quality_gate_stats = {
            "input_count": len(deduped),
            "passed_count": len(active_items),
            "dropped_count": len(dropped_items),
        }

        if dropped_items:
            warnings.append(PipelineWarning(
                category="quality_gate_dropped",
                message=(
                    f"{len(dropped_items)} of {len(deduped)} items dropped "
                    f"by quality gate (min_chars={gate_min_chars}, "
                    f"min_words={gate_min_words})."
                ),
                source="run_pipeline.run_phase1",
                context=quality_gate_stats,
            ))

        deduped = active_items
        logger.info(
            "phase1_quality_gate_complete",
            passed=len(active_items),
            dropped=len(dropped_items),
        )

    # ── 1.3  Clustering ──────────────────────────────────────────────
    logger.info("phase1_clustering_start")

    # --- Clustering ---
    labels: list[int] = []
    cluster_result: dict[str, Any] = {}

    if len(deduped) >= 2:
        X, _vec = vectorize_items(
            deduped,
            tfidf_params=config.dedup.vectorizer.model_dump(),
        )

        k_result = choose_k_by_silhouette(
            X,
            k_min=config.clustering.min_k,
            k_max=config.clustering.max_k,
            weak_threshold=config.clustering.low_silhouette_threshold,
            random_state=config.clustering.random_state,
        )

        chosen_k = k_result["chosen_k"]

        if k_result["fallback_used"]:
            chosen_k = config.clustering.fallback_k
            warnings.append(PipelineWarning(
                category="weak_clustering",
                message=(
                    f"Best silhouette score {k_result['best_score']:.4f} "
                    f"below threshold; using fallback K={chosen_k}."
                ),
                source="run_pipeline.run_phase1",
            ))

        # Clamp chosen_k to feasible range.
        chosen_k = max(2, min(chosen_k, len(deduped) - 1))

        labels = cluster_items(X, chosen_k, random_state=config.clustering.random_state)
        reps = cluster_representatives(
            X, labels, deduped,
            per_cluster=config.clustering.representatives_per_cluster,
        )

        cluster_result = {
            "chosen_k": chosen_k,
            "best_score": k_result["best_score"],
            "all_scores": k_result["all_scores"],
            "fallback_used": k_result["fallback_used"],
            "labels": labels,
            "representatives": {str(k): v for k, v in reps.items()},
        }
    else:
        # 0 or 1 items — single cluster.
        labels = [0] * len(deduped)
        cluster_result = {
            "chosen_k": 1,
            "best_score": -1.0,
            "all_scores": {},
            "fallback_used": True,
            "labels": labels,
            "representatives": {"0": list(range(len(deduped)))},
        }

    # ── 1.3b  Topic binning fallback (optional) ─────────────────────
    topic_binning_result: dict[str, Any] | None = None
    if (
        config.topic_binning.enabled
        and config.topic_binning.use_as_cluster_fallback
        and cluster_result.get("fallback_used")
        and config.topic_binning.bins
    ):
        logger.info("phase1_topic_binning_start")
        bin_defs = [
            {"name": b.name, "keywords": b.keywords}
            for b in config.topic_binning.bins
        ]
        tb_result = assign_bins(deduped, bin_defs)
        topic_binning_result = {
            "bin_counts": tb_result["bin_counts"],
            "unassigned_count": tb_result["unassigned_count"],
        }
        logger.info(
            "phase1_topic_binning_complete",
            bins=len(tb_result["bin_counts"]),
            unassigned=tb_result["unassigned_count"],
        )

    stage3_data: dict[str, Any] = {
        "stage": "clusters",
        "clustering": cluster_result,
    }
    if sampling_stats is not None:
        stage3_data["sampling_stats"] = sampling_stats
    if enrichment_stats is not None:
        stage3_data["enrichment_stats"] = enrichment_stats
    if quality_gate_stats is not None:
        stage3_data["quality_gate_stats"] = quality_gate_stats
    if topic_binning_result is not None:
        stage3_data["topic_binning"] = topic_binning_result

    write_stage_json(run_dir / "stage_3_clusters.json", stage3_data)
    logger.info(
        "phase1_clustering_complete",
        chosen_k=cluster_result["chosen_k"],
    )

    # ── 1.4  LLM macro labeling ───────────────────────────────────────
    logger.info("phase1_macro_labels_start")

    narratives: list[dict[str, Any]] = []
    cluster_failures: list[dict[str, Any]] = []
    unique_labels = sorted(set(labels))
    total_items = len(deduped)

    for cluster_id in unique_labels:
        member_indices = [i for i, lbl in enumerate(labels) if lbl == cluster_id]
        headlines = [deduped[i]["title"] for i in member_indices]

        prompt = build_macro_label_prompt(
            cluster_id, headlines, sector=config.pipeline.sector,
        )

        try:
            parsed, meta = label_macro_narrative(
                prompt, config, MacroLabelResponse, run_context=run_ctx,
            )

            coverage_pct = (
                round(len(member_indices) / total_items * 100, 1)
                if total_items > 0 else 0.0
            )

            narratives.append({
                "cluster_id": cluster_id,
                "title": parsed.title,
                "summary": parsed.summary,
                "article_count": len(member_indices),
                "coverage_pct": coverage_pct,
                "member_indices": member_indices,
                "llm_metadata": meta,
            })

            if meta.get("prompt_hash"):
                prompt_hashes[f"cluster_{cluster_id}"] = meta["prompt_hash"]

        except Exception as exc:
            cluster_failures.append({
                "cluster_id": cluster_id,
                "error": str(exc),
                "headline_count": len(headlines),
            })
            warnings.append(PipelineWarning(
                category="llm_label_failed",
                message=f"Failed to label cluster {cluster_id}: {exc}",
                source="run_pipeline.run_phase1",
                context={"cluster_id": cluster_id},
            ))
            logger.warning(
                "llm_label_failed", cluster_id=cluster_id, detail=str(exc),
            )

    # Narrative similarity warnings.
    sim_warnings = narrative_similarity_warnings(
        narratives, threshold=config.validation.narrative_similarity_threshold,
    )
    warnings.extend(sim_warnings)

    # Extract model provenance from first successful LLM call.
    if narratives:
        first_meta = narratives[0].get("llm_metadata", {})
        model_provenance = {
            "provider": first_meta.get("provider", ""),
            "model": first_meta.get("model", ""),
        }

    write_stage_json(run_dir / "stage_4_macro_labels.json", {
        "stage": "macro_labels",
        "narrative_count": len(narratives),
        "narratives": narratives,
        "similarity_warnings": [w.to_dict() for w in sim_warnings],
        "cluster_failures": cluster_failures,
    })
    logger.info(
        "phase1_macro_labels_complete",
        narrative_count=len(narratives),
        failures=len(cluster_failures),
    )

    return {
        "warnings": warnings,
        "prompt_hashes": prompt_hashes,
        "input_hashes": input_hashes,
        "model_provenance": model_provenance,
        "window_start": window_start,
        "window_end": window_end,
    }


# ── Phase 2 orchestration ─────────────────────────────────────────────────

def run_phase2(
    config: PipelineConfig,
    run_ctx: dict[str, Any],
    logger: RunLogger,
) -> dict[str, Any]:
    """Execute Phase 2: competitor press-release scrape + metrics baseline.

    Iterates over each competitor's press_release_urls, scrapes each URL
    with partial-success semantics (failures become warnings), computes
    positioning metrics on successful scrapes, and writes
    ``stage_5_press_release_scrape_metrics.json``.

    Returns a dict with keys ``warnings``, ``scrape_hashes`` for manifest
    enrichment.
    """
    import time as _time
    import random as _random

    warnings: list[PipelineWarning] = []
    scrape_hashes: dict[str, str] = {}
    run_dir = Path(run_ctx["run_dir"])

    logger.info("phase2_start")

    competitor_results: list[dict[str, Any]] = []

    for comp in config.competitors:
        comp_name = comp.name
        logger.info("phase2_competitor_start", competitor=comp_name)

        for url in comp.press_release_urls:
            logger.info("phase2_scrape_start", competitor=comp_name, url=url)

            result = scrape_press_release(url, config)

            if result["error"] is not None:
                # Partial success: log warning, skip metrics.
                if result["warning"] is not None:
                    warnings.append(result["warning"])
                logger.warning(
                    "phase2_scrape_failed",
                    competitor=comp_name,
                    url=url,
                    detail=result["error"],
                )
                competitor_results.append({
                    "competitor": comp_name,
                    "url": url,
                    "error": result["error"],
                    "metrics": None,
                    "extraction_method": None,
                    "char_count": 0,
                    "word_count": 0,
                })
                continue

            # Record scrape hash for provenance.
            if result["raw_hash"]:
                scrape_hashes[url] = result["raw_hash"]

            # Compute metrics on the LLM-track text.
            text_for_metrics = result["clean_text_for_llm"]
            metrics = compute_all_metrics(text_for_metrics, config)

            # Check for tone polarity warnings.
            tone_warnings = tone_polarity_warning(metrics)
            for tw in tone_warnings:
                tw.context["competitor"] = comp_name
                tw.context["url"] = url
            warnings.extend(tone_warnings)

            competitor_results.append({
                "competitor": comp_name,
                "url": url,
                "error": None,
                "extraction_method": result["extraction_method"],
                "char_count": result["char_count"],
                "word_count": result["word_count"],
                "raw_hash": result["raw_hash"],
                "clean_text_for_llm": result["clean_text_for_llm"],
                "metrics": metrics,
            })

            logger.info(
                "phase2_scrape_complete",
                competitor=comp_name,
                url=url,
                method=result["extraction_method"],
                chars=result["char_count"],
            )

            # Polite delay between scrapes.
            delay_min, delay_max = config.scraping.delay_range_seconds
            _time.sleep(_random.uniform(delay_min, delay_max))

        logger.info("phase2_competitor_complete", competitor=comp_name)

    # Write stage artifact.
    write_stage_json(run_dir / "stage_5_press_release_scrape_metrics.json", {
        "stage": "press_release_scrape_metrics",
        "competitor_count": len(config.competitors),
        "total_urls": sum(len(c.press_release_urls) for c in config.competitors),
        "successful_scrapes": sum(
            1 for r in competitor_results if r["error"] is None
        ),
        "failed_scrapes": sum(
            1 for r in competitor_results if r["error"] is not None
        ),
        "results": competitor_results,
        "warnings": [w.to_dict() for w in warnings],
    })

    logger.info(
        "phase2_complete",
        total_results=len(competitor_results),
        failures=sum(1 for r in competitor_results if r["error"] is not None),
    )

    return {
        "warnings": warnings,
        "scrape_hashes": scrape_hashes,
        "competitor_results": competitor_results,
    }


# ── Phase 3 orchestration ─────────────────────────────────────────────────

def run_phase3(
    config: PipelineConfig,
    run_ctx: dict[str, Any],
    logger: RunLogger,
    phase2_results: list[dict[str, Any]],
) -> dict[str, Any]:
    """Execute Phase 3: strict synthesis / hook translation.

    For each successful competitor scrape from Phase 2:

    1. Truncate text to ``max_input_tokens``.
    2. Build a hook translation prompt.
    3. Call the LLM for structured output.
    4. Verify quotes, check digit mismatches, check phase claims.
    5. Write ``stage_6_hook_translations.json``.

    Parameters
    ----------
    phase2_results : list[dict]
        The ``results`` list from Stage 5 — each entry has ``competitor``,
        ``url``, ``error``, ``clean_text_for_llm``, etc.  Only entries
        with ``error is None`` are processed.

    Returns a dict with keys ``warnings``, ``prompt_hashes`` for manifest
    enrichment.
    """
    warnings: list[PipelineWarning] = []
    prompt_hashes: dict[str, str] = {}
    run_dir = Path(run_ctx["run_dir"])

    logger.info("phase3_start")

    translations: list[dict[str, Any]] = []
    translation_failures: list[dict[str, Any]] = []

    for p2_entry in phase2_results:
        if p2_entry.get("error") is not None:
            continue  # Skip failed scrapes.

        comp_name = p2_entry["competitor"]
        url = p2_entry["url"]
        clean_text = p2_entry.get("clean_text_for_llm")

        if not clean_text:
            continue

        logger.info("phase3_translate_start", competitor=comp_name, url=url)

        # ── 3.1  Token truncation ─────────────────────────────────────
        trunc = truncate_text_to_max_tokens(
            clean_text,
            config.llm.max_input_tokens,
            encoding_name=config.llm.tiktoken_encoding,
        )
        text_for_llm = trunc["text"]
        truncation_meta = {
            "original_tokens": trunc["original_tokens"],
            "truncated_tokens": trunc["truncated_tokens"],
            "was_truncated": trunc["was_truncated"],
        }

        if trunc["was_truncated"]:
            warnings.append(PipelineWarning(
                category="text_truncated",
                message=(
                    f"Source text for {comp_name} truncated from "
                    f"{trunc['original_tokens']} to {trunc['truncated_tokens']} tokens."
                ),
                source="run_pipeline.run_phase3",
                context={
                    "competitor": comp_name,
                    "url": url,
                    "original_tokens": trunc["original_tokens"],
                    "truncated_tokens": trunc["truncated_tokens"],
                },
            ))

        # ── 3.2  Build prompt ─────────────────────────────────────────
        prompt = build_hook_translation_prompt(
            comp_name, url, text_for_llm,
            sector=config.pipeline.sector,
            impact_label=config.report.impact_label,
        )

        # ── 3.3  Call LLM ─────────────────────────────────────────────
        # Sanitize competitor name for prompt label filename.
        safe_name = comp_name.lower().replace(" ", "_")
        prompt_label = f"phase3_{safe_name}"

        try:
            parsed, meta = translate_press_release(
                prompt, config, HookTranslationResponse,
                run_context=run_ctx,
                prompt_label=prompt_label,
            )
        except Exception as exc:
            translation_failures.append({
                "competitor": comp_name,
                "url": url,
                "error": str(exc),
            })
            warnings.append(PipelineWarning(
                category="hook_translation_failed",
                message=f"Failed to translate press release for {comp_name}: {exc}",
                source="run_pipeline.run_phase3",
                context={"competitor": comp_name, "url": url},
            ))
            logger.warning(
                "phase3_translate_failed",
                competitor=comp_name, url=url, detail=str(exc),
            )
            continue

        if meta.get("prompt_hash"):
            prompt_hashes[f"phase3_{safe_name}"] = meta["prompt_hash"]

        # ── 3.4  Quote verification ───────────────────────────────────
        # Verify against the EXACT text sent to the LLM (truncated if applicable).
        quote_results = verify_two_quotes(
            parsed.two_verified_quotes, text_for_llm,
        )

        for i, qr in enumerate(quote_results["results"]):
            if qr["status"] == "failed":
                warnings.append(PipelineWarning(
                    category="quote_verification_failed",
                    message=(
                        f"Quote {i+1} for {comp_name} failed all "
                        f"verification tiers."
                    ),
                    source="run_pipeline.run_phase3",
                    context={
                        "competitor": comp_name,
                        "quote_index": i,
                        "quote": parsed.two_verified_quotes[i],
                    },
                ))
            elif qr["status"] in ("soft_verified", "soft_verified_ellipsis"):
                warnings.append(PipelineWarning(
                    category=f"quote_{qr['status']}",
                    message=(
                        f"Quote {i+1} for {comp_name} was "
                        f"{qr['status']} (Tier {qr['tier']})."
                    ),
                    source="run_pipeline.run_phase3",
                    context={
                        "competitor": comp_name,
                        "quote_index": i,
                        "tier": qr["tier"],
                    },
                ))

        # ── 3.5  Digit mismatch warnings ──────────────────────────────
        output_text = (
            f"{parsed.hook_headline} {parsed.mainstream_summary} "
            + " ".join(parsed.key_impact)
            + " ".join(parsed.why_it_matters)
        )
        digit_warnings = digit_mismatch_warnings(output_text, text_for_llm)
        for dw in digit_warnings:
            dw.context["competitor"] = comp_name
            dw.context["url"] = url
        warnings.extend(digit_warnings)

        # ── 3.6  Phase claim warnings ─────────────────────────────────
        phase_warnings = phase_claim_warnings(output_text, text_for_llm)
        for pw in phase_warnings:
            pw.context["competitor"] = comp_name
            pw.context["url"] = url
        warnings.extend(phase_warnings)

        translations.append({
            "competitor": comp_name,
            "url": url,
            "hook_headline": parsed.hook_headline,
            "mainstream_summary": parsed.mainstream_summary,
            "two_verified_quotes": parsed.two_verified_quotes,
            "key_impact": parsed.key_impact,
            "why_it_matters": parsed.why_it_matters,
            "quote_verification": quote_results,
            "truncation": truncation_meta,
            "llm_metadata": meta,
            "digit_warnings": [w.to_dict() for w in digit_warnings],
            "phase_warnings": [w.to_dict() for w in phase_warnings],
        })

        logger.info(
            "phase3_translate_complete",
            competitor=comp_name,
            url=url,
            quotes_passed=quote_results["all_passed"],
        )

    # Write stage artifact.
    write_stage_json(run_dir / "stage_6_hook_translations.json", {
        "stage": "hook_translations",
        "translation_count": len(translations),
        "translations": translations,
        "translation_failures": translation_failures,
        "warnings": [w.to_dict() for w in warnings],
    })

    logger.info(
        "phase3_complete",
        translations=len(translations),
        failures=len(translation_failures),
    )

    return {
        "warnings": warnings,
        "prompt_hashes": prompt_hashes,
    }


# ── Phase 4 orchestration ─────────────────────────────────────────────────

def run_phase4(
    config: PipelineConfig,
    run_ctx: dict[str, Any],
    logger: RunLogger,
    phase1: dict[str, Any],
    phase2: dict[str, Any],
    phase3: dict[str, Any],
    all_warnings: list[PipelineWarning],
) -> dict[str, Any]:
    """Execute Phase 4: generate the executive briefing (Word document).

    Parameters
    ----------
    phase1 : dict
        Phase 1 enriched result dict (narratives, clustering, deduped items).
    phase2 : dict
        Phase 2 enriched result dict (competitor_results with metrics).
    phase3 : dict
        Phase 3 enriched result dict (translations, quote verification).
    all_warnings : list[PipelineWarning]
        Accumulated warnings from all prior phases.

    Returns a dict with ``report_path`` and ``report_hash``.
    """
    logger.info("phase4_start")

    # Build Phase 1 report data from stage artifacts + enriched results.
    run_dir = Path(run_ctx["run_dir"])

    # Load stage JSONs if available for richer data.
    import json

    p1_report: dict[str, Any] = {}
    stage1_path = run_dir / "stage_1_rss_ingest.json"
    if stage1_path.exists():
        stage1 = json.loads(stage1_path.read_text(encoding="utf-8"))
        p1_report["rss_entry_count"] = stage1.get("entry_count", 0)
        p1_report["window_start"] = phase1.get(
            "window_start", stage1.get("window_start", "N/A"),
        )
        p1_report["window_end"] = phase1.get(
            "window_end", stage1.get("window_end", "N/A"),
        )

    stage2_path = run_dir / "stage_2_dedup.json"
    if stage2_path.exists():
        stage2 = json.loads(stage2_path.read_text(encoding="utf-8"))
        p1_report["dedup_input_count"] = stage2.get("input_count", 0)
        p1_report["dedup_output_count"] = stage2.get("deduped_count", 0)
        p1_report["deduped_items"] = stage2.get("deduped_items", [])

    stage3_path = run_dir / "stage_3_clusters.json"
    if stage3_path.exists():
        stage3 = json.loads(stage3_path.read_text(encoding="utf-8"))
        p1_report["clustering"] = stage3.get("clustering", {})

    stage4_path = run_dir / "stage_4_macro_labels.json"
    if stage4_path.exists():
        stage4 = json.loads(stage4_path.read_text(encoding="utf-8"))
        p1_report["narratives"] = stage4.get("narratives", [])

    # Phase 2 report data.
    p2_report: dict[str, Any] = {
        "competitor_results": phase2.get("competitor_results", []),
    }

    # Phase 3 report data.
    p3_report: dict[str, Any] = {}
    stage6_path = run_dir / "stage_6_hook_translations.json"
    if stage6_path.exists():
        stage6 = json.loads(stage6_path.read_text(encoding="utf-8"))
        p3_report["translations"] = stage6.get("translations", [])

    # Serialize warnings for report.
    warn_dicts = [w.to_dict() for w in all_warnings]

    report_path = build_report(
        run_ctx, config, p1_report, p2_report, p3_report, warn_dicts,
    )

    # Compute report hash.
    report_bytes = Path(report_path).read_bytes()
    report_hash = sha256_bytes(report_bytes)

    logger.info(
        "phase4_complete",
        report_path=report_path,
        report_hash=report_hash,
    )

    return {
        "report_path": report_path,
        "report_hash": report_hash,
    }


# ── Sample-run helpers ────────────────────────────────────────────────────

_FIXTURES_DIR = Path(__file__).resolve().parent / "tests" / "fixtures"


def _load_fixture_bytes(name: str) -> bytes:
    """Load raw bytes from a file in the ``tests/fixtures/`` directory."""
    return (_FIXTURES_DIR / name).read_bytes()


def _load_fixture_json(name: str) -> dict:
    """Load and parse a JSON file from ``tests/fixtures/``."""
    import json as _json
    return _json.loads((_FIXTURES_DIR / name).read_text(encoding="utf-8"))


def _sample_run_config_overlay(config: PipelineConfig) -> PipelineConfig:
    """Return a config copy with sample-run overrides applied.

    - Sets ``max_input_tokens`` low (200) to exercise truncation logic.
    - Uses a dummy API key env (never resolved in sample mode).
    - Disables polite delays (not needed for fixtures).
    - Points RSS feeds / competitors at fixture-compatible names.
    """
    import copy
    d = config.model_dump()
    d["llm"]["max_input_tokens"] = 200
    d["llm"]["api_key_env"] = "NWE_SAMPLE_RUN_KEY"
    d["scraping"]["delay_range_seconds"] = [0.0, 0.0]
    d["rss"]["feeds"] = [{"url": "https://sample.example.com/feed", "name": "SampleFeed"}]
    d["rss"]["lookback_days"] = 400  # Wide window so fixture dates always pass.
    d["competitors"] = [
        {
            "name": "Moderna",
            "press_release_urls": [
                "https://sample.example.com/press/moderna-phase3",
            ],
        },
    ]
    return PipelineConfig(**d)


def _make_sample_label_fn():
    """Return a mock ``label_macro_narrative`` backed by fixture JSON."""
    fixture = _load_fixture_json("llm_macro_label_response.json")

    def _fn(prompt, config, schema_model, run_context=None, **kwargs):
        parsed = MacroLabelResponse(**fixture)
        prompt_hash = sha256_bytes(prompt.encode("utf-8"))
        if run_context is not None:
            prompts_dir = Path(run_context["prompts_dir"])
            prompt_file = prompts_dir / f"macro_label_{prompt_hash[:12]}.txt"
            prompt_file.write_text(prompt, encoding="utf-8")
        metadata = {
            "provider": "sample-run",
            "model": "fixture",
            "prompt_hash": prompt_hash,
            "timestamp": "2025-02-24T12:00:00+00:00",
            "retries_used": 0,
            "raw_response": parsed.model_dump_json(),
            "validation_errors": [],
        }
        return parsed, metadata

    return _fn


def _make_sample_translate_fn():
    """Return a mock ``translate_press_release`` backed by fixture JSON."""
    fixture = _load_fixture_json("llm_hook_response.json")

    def _fn(prompt, config, schema_model, *, run_context=None,
            prompt_label="phase3_hook", **kwargs):
        parsed = HookTranslationResponse(**fixture)
        prompt_hash = sha256_bytes(prompt.encode("utf-8"))
        if run_context is not None:
            prompts_dir = Path(run_context["prompts_dir"])
            prompt_file = prompts_dir / f"{prompt_label}_{prompt_hash[:12]}.txt"
            prompt_file.write_text(prompt, encoding="utf-8")
        metadata = {
            "provider": "sample-run",
            "model": "fixture",
            "prompt_hash": prompt_hash,
            "timestamp": "2025-02-24T12:00:00+00:00",
            "retries_used": 0,
            "raw_response": parsed.model_dump_json(),
            "validation_errors": [],
        }
        return parsed, metadata

    return _fn


def _make_sample_scrape_fn():
    """Return a mock ``scrape_press_release`` backed by fixture HTML."""
    html_bytes = _load_fixture_bytes("press_release_sample.html")
    from src.press_release_scrape import extract_text_from_html

    def _fn(url, config):
        extraction = extract_text_from_html(
            html_bytes,
            selectors=config.scraping.extraction_selectors,
            min_chars=config.scraping.min_chars,
            min_words=config.scraping.min_words,
        )
        std = standardize(extraction["text"])
        return {
            "url": url,
            "raw_hash": sha256_bytes(html_bytes),
            "extraction_method": extraction["method"],
            "clean_text_for_llm": std["clean_text_for_llm"],
            "clean_text_for_nlp": std["clean_text_for_nlp"],
            "char_count": extraction["char_count"],
            "word_count": extraction["word_count"],
            "error": None,
            "warning": None,
        }

    return _fn


# ── CLI entry point ──────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    """Parse CLI args, validate config, and run Phases 1–4.

    Returns the exit code (0, 1, or 2).
    """
    parser = _build_parser()
    args = parser.parse_args(argv)

    # ── Load & validate config ───────────────────────────────────────
    try:
        config, config_hash, _raw = load_config(
            args.config, dry_run=args.dry_run,
        )
    except SystemExit:
        return 2
    except (FileNotFoundError, ValueError) as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 2

    if args.dry_run:
        print("\nConfig is valid. Dry-run complete.", file=sys.stderr)
        return 0

    # ── Sample-run overlay ───────────────────────────────────────────
    sample_mode = getattr(args, "sample_run", False)
    if sample_mode:
        import os
        os.environ.setdefault("NWE_SAMPLE_RUN_KEY", "sample-run-no-api-key")
        config = _sample_run_config_overlay(config)
        config_hash = sha256_bytes(b"sample-run")

    # ── Initialise run ───────────────────────────────────────────────
    run_ctx = init_run(config, config_hash)
    logger = get_run_logger(run_ctx["log_path"])
    logger.info(
        "run_initialised",
        run_id=run_ctx["run_id"],
        config_hash=config_hash,
        sample_mode=sample_mode,
    )

    if sample_mode:
        logger.info("sample_run_mode_active")

    # Write an initial manifest stub.
    write_run_manifest(run_ctx, config, config_hash)
    logger.info("manifest_stub_written")

    # ── Apply sample-run patches ─────────────────────────────────────
    from unittest.mock import patch as _patch
    from contextlib import ExitStack

    patches = ExitStack()
    if sample_mode:
        rss_bytes = _load_fixture_bytes("rss_sample.xml")
        patches.enter_context(
            _patch("src.rss_ingest.fetch_feed", return_value=rss_bytes),
        )
        patches.enter_context(
            _patch("run_pipeline.label_macro_narrative",
                   side_effect=_make_sample_label_fn()),
        )
        patches.enter_context(
            _patch("run_pipeline.scrape_press_release",
                   side_effect=_make_sample_scrape_fn()),
        )
        patches.enter_context(
            _patch("run_pipeline.translate_press_release",
                   side_effect=_make_sample_translate_fn()),
        )

    with patches:
        # ── Phase 1 execution ────────────────────────────────────────
        phase1_result = run_phase1(config, run_ctx, logger)
        logger.info("pipeline_phase1_complete", run_id=run_ctx["run_id"])

        # ── Phase 2 execution ────────────────────────────────────────
        phase2_result = run_phase2(config, run_ctx, logger)
        logger.info("pipeline_phase2_complete", run_id=run_ctx["run_id"])

        # ── Phase 3 execution ────────────────────────────────────────
        phase3_result = run_phase3(
            config, run_ctx, logger, phase2_result["competitor_results"],
        )
        logger.info("pipeline_phase3_complete", run_id=run_ctx["run_id"])

    # ── Merge results ────────────────────────────────────────────────
    all_warnings = (
        phase1_result["warnings"]
        + phase2_result["warnings"]
        + phase3_result["warnings"]
    )
    merged_input_hashes = {
        **phase1_result["input_hashes"],
        "scrape_hashes": phase2_result["scrape_hashes"],
    }
    merged_prompt_hashes = {
        **phase1_result["prompt_hashes"],
        **phase3_result["prompt_hashes"],
    }

    # ── Phase 4 execution ────────────────────────────────────────────
    phase4_result = run_phase4(
        config, run_ctx, logger,
        phase1_result, phase2_result, phase3_result,
        all_warnings,
    )
    logger.info("pipeline_phase4_complete", run_id=run_ctx["run_id"])

    # ── Rewrite manifest with report provenance ──────────────────────
    write_run_manifest(
        run_ctx,
        config,
        config_hash,
        model_provenance=phase1_result["model_provenance"],
        prompt_hashes=merged_prompt_hashes,
        input_hashes=merged_input_hashes,
        warnings=all_warnings,
    )

    # Enrich manifest with report path and hash.
    import json
    manifest_path = Path(run_ctx["manifest_path"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["report_path"] = phase4_result["report_path"]
    manifest["report_hash"] = phase4_result["report_hash"]
    if sample_mode:
        manifest["sample_run"] = True
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )

    logger.info("pipeline_complete", run_id=run_ctx["run_id"])
    print(f"Pipeline complete: {run_ctx['run_dir']}")
    print(f"Report: {phase4_result['report_path']}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(1)
