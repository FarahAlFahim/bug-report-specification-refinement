"""SHERLOC baseline: independent repository exploration, then the fixed report schema.

Phase: 'sherloc'
Input: Original SWE-Bench instances + local git clone of the repository
Output: Bug reports in the same fixed report schema as ExploreSpec

SHERLOC (Tamoyan et al., 2026, https://arxiv.org/abs/2606.24820) is a
training-free localization agent. Given the original bug report and the
pre-fix repository, it explores the repository with four read-only tools
(view_file, codebase_search, repo_tree, connected_tree) and answers with a
<findings> block of structured diagnostic findings for candidate code
locations (location explanation, root cause, solution idea, dependencies,
testing impact) followed by a <locations> block of file paths and line ranges.

SHERLOC does not natively produce a refined bug report. For a consistent
downstream input format, the original report and SHERLOC's final findings are
passed to the same report generator used by ExploreSpec, which presents them in
the fixed report schema (Title, Description, RootCause, StepsToReproduce,
ExpectedBehavior, ObservedBehavior).

Faithfulness to the reference implementation
(https://github.com/NVIDIA-NeMo/Skills/tree/main/recipes/sherloc):
  - prompts/sherloc_system.txt is the reference system prompt, verbatim. The
    reference sends it unformatted on every turn, so its doubled braces are kept.
  - src/agents/sherloc_utils/ holds the reference tool executor, response
    parser, context manager and repository views with only imports adapted.
  - run_sherloc_episode() follows the reference exploration loop step by step:
    first-and-recent truncation, loop detection before and after generation,
    the proactive context check, the final-turn instruction, response-length
    retries and implicit tool-call recovery, with the reference defaults.
  - The repository snapshot is built from the git tree at base_commit with the
    reference snapshot layout and filtering, instead of a pickled snapshot.

The exploration loop, its intervention messages and prompts/sherloc_system.txt
are adapted from the reference implementation, Copyright (c) 2026, NVIDIA
CORPORATION, licensed under the Apache License, Version 2.0 (see
src/agents/sherloc_utils/LICENSE).

Differences forced by the serving backend:
  - Generated-token counts and truncation come from the API usage metadata and
    finish_reason; tool-output tokens are counted with tiktoken.
  - GPT-5 models accept only their default sampling parameters, so the
    reference temperature/top_p apply to other models only.
  - The reference-patch coverage statistic is not computed: the gold patch is
    never read by this pipeline.
"""

import copy
import logging
import os
import subprocess
import time
from collections import Counter
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import openai
import tiktoken
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

import src.state as state
from src.agents.common import generate_final_bug_report, save_instance_result
from src.agents.sherloc_utils.context_manager import ContextManager
from src.agents.sherloc_utils.defaults import (
    DEFAULT_COMMON_WORDS_FILTER,
    DEFAULT_EXCLUDE_DIRS,
    DEFAULT_FILE_EXTENSIONS,
)
from src.agents.sherloc_utils.dialog_processor import DialogProcessor
from src.agents.sherloc_utils.repo_manager import RepoManager
from src.agents.sherloc_utils.tool_executor import ToolExecutor
from src.utils.io import load_json_safe, mkdirp, save_json_atomic
from src.utils.json_parser import parse_json_best_effort
from src.utils.llm import _is_gpt5_model, load_prompt, make_chat_llm

logger = logging.getLogger("context_engineering.agents.sherloc")


# ---------------------------------------------------------------------------
# Settings — defaults are those of the reference SherlocGenerationConfig
# ---------------------------------------------------------------------------

@dataclass
class SherlocSettings:
    inference: SimpleNamespace = field(default_factory=lambda: SimpleNamespace(
        temperature=0.99,
        top_p=0.95,
        tokens_to_generate=81920,
    ))
    total_steps: int = 20

    file_extensions: list = field(default_factory=lambda: list(DEFAULT_FILE_EXTENSIONS))
    exclude_dirs: list = field(default_factory=lambda: list(DEFAULT_EXCLUDE_DIRS))

    enable_implicit_tool_detection: bool = True
    common_words_filter: list = field(default_factory=lambda: list(DEFAULT_COMMON_WORDS_FILTER))

    max_seq_length: int = 262144
    show_line_counts: bool = False
    max_view_lines: int = 1000

    enable_loop_detection: bool = True
    loop_detection_threshold: int = 3

    enable_enhanced_context: bool = True
    context_safety_margin: float = 0.9

    enable_response_length_management: bool = True
    max_retries: int = 2
    inject_length_warnings: bool = True
    response_warning_threshold: float = 0.75
    response_critical_threshold: float = 0.9

    enable_final_turn_prompt: bool = True


class _TiktokenCounter:
    """Adapter giving tiktoken the tokenizer interface ToolExecutor expects."""

    def __init__(self, model_name: str):
        try:
            self._enc = tiktoken.encoding_for_model(model_name)
        except Exception:
            self._enc = tiktoken.get_encoding("cl100k_base")

    def encode(self, text: str, add_special_tokens: bool = False) -> List[int]:
        return self._enc.encode(text, disallowed_special=())


# ---------------------------------------------------------------------------
# Repository snapshot at the pre-fix commit
# ---------------------------------------------------------------------------

def _path_survives_filter(parts: List[str], exclude_dirs: list, file_extensions: list) -> bool:
    """Same per-name test as RepoManager.filter_repo_dict, applied to a whole path."""
    for part in parts:
        if part in exclude_dirs:
            return False
        if "." in part and part.split(".")[-1] not in file_extensions:
            return False
    return True


def build_repo_snapshot(repo_local_path: str, commit: str, instance_id: str,
                        settings: SherlocSettings) -> dict:
    """Build the reference snapshot layout from the git tree at `commit`.

    Directories map to sub-dictionaries and each file to
    {"classes": [], "functions": [], "text": <lines>}, with entries inserted in
    sorted path order and undecodable files skipped, as in the reference
    snapshot builder. Paths that the reference filter would remove are not
    read; RepoManager.filter_repo_dict is still applied afterwards.
    """
    ls = subprocess.run(
        ["git", "ls-tree", "-r", "-z", "--full-tree", commit],
        cwd=repo_local_path, capture_output=True, timeout=300,
    )
    if ls.returncode != 0:
        raise RuntimeError(f"git ls-tree failed for {commit}: {ls.stderr.decode(errors='replace')}")

    blobs = []
    for entry in ls.stdout.decode("utf-8", errors="replace").split("\0"):
        if not entry:
            continue
        meta, path = entry.split("\t", 1)
        mode, obj_type, sha = meta.split()
        if obj_type != "blob" or mode == "120000":  # skip submodules and symlinks
            continue
        parts = path.split("/")
        if _path_survives_filter(parts, settings.exclude_dirs, settings.file_extensions):
            blobs.append((tuple(parts), sha))
    blobs.sort()

    cat = subprocess.run(
        ["git", "cat-file", "--batch"],
        cwd=repo_local_path, input="".join(f"{sha}\n" for _, sha in blobs).encode(),
        capture_output=True, timeout=600,
    )
    if cat.returncode != 0:
        raise RuntimeError(f"git cat-file failed: {cat.stderr.decode(errors='replace')}")

    structure: Dict[str, Any] = {}
    out, pos = cat.stdout, 0
    for parts, sha in blobs:
        header_end = out.index(b"\n", pos)
        size = int(out[pos:header_end].split()[2])
        content = out[header_end + 1: header_end + 1 + size]
        pos = header_end + 1 + size + 1
        try:
            text = content.decode("utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        node = structure
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = {"classes": [], "functions": [], "text": text}

    repo_dict = {"instance_id": instance_id, "structure": structure}
    return RepoManager.filter_repo_dict(repo_dict, settings.exclude_dirs, settings.file_extensions)


# ---------------------------------------------------------------------------
# One generation call
# ---------------------------------------------------------------------------

def _response_text(response) -> str:
    """Return the reply text, keeping any separately returned reasoning in <think>."""
    content = response.content
    if isinstance(content, list):
        content = "".join(
            part.get("text", "") if isinstance(part, dict) else str(part) for part in content
        )
    content = content or ""
    reasoning = (getattr(response, "additional_kwargs", {}) or {}).get("reasoning_content")
    if reasoning and "<think>" not in content:
        content = f"<think>\n{reasoning}\n</think>\n\n{content}"
    return content


def _generate(llm, model_name: str, system_prompt: str, turns: List[Dict],
              settings: SherlocSettings) -> Dict[str, Any]:
    """Replay the dialogue as the reference fill_prompt does and generate one reply."""
    messages = [SystemMessage(content=system_prompt)]
    for turn in turns[:-1]:
        if turn.get("inputs", ""):
            messages.append(HumanMessage(content=turn["inputs"]))
        if turn.get("assistant", ""):
            messages.append(AIMessage(content=turn["assistant"]))
    messages.append(HumanMessage(content=turns[-1].get("inputs", "")))

    kwargs = {"max_tokens": settings.inference.tokens_to_generate}
    if not _is_gpt5_model(model_name):
        kwargs["top_p"] = settings.inference.top_p
    # Transient API failures are retried here so they never end an episode early.
    response = _call_with_api_retries(lambda: llm.invoke(messages, **kwargs))

    text = _response_text(response)
    usage = getattr(response, "usage_metadata", None) or {}
    num_tokens = usage.get("output_tokens")
    if num_tokens is None:
        num_tokens = len(tiktoken.get_encoding("cl100k_base").encode(text, disallowed_special=()))
    finish_reason = (getattr(response, "response_metadata", {}) or {}).get("finish_reason")
    return {"generation": text, "num_generated_tokens": num_tokens, "finish_reason": finish_reason}


API_RETRIES = 5


def _status_code(err: Exception) -> Optional[int]:
    code = getattr(err, "status_code", None)
    if code is None:
        code = getattr(getattr(err, "response", None), "status_code", None)
    return code if isinstance(code, int) else None


def _is_transient_api_error(err: Exception) -> bool:
    """Rate limits, timeouts, connection drops and 5xx responses, from any client library."""
    if isinstance(err, (openai.RateLimitError, openai.APIConnectionError, openai.InternalServerError)):
        return True
    code = _status_code(err)
    if code is not None:
        return code == 429 or code >= 500
    name = type(err).__name__
    return any(s in name for s in ("RateLimit", "Timeout", "Connection", "ServiceUnavailable"))


def _call_with_api_retries(fn):
    """Call `fn`, retrying transient API errors with exponential backoff."""
    for attempt in range(API_RETRIES + 1):
        try:
            return fn()
        except Exception as e:
            if attempt == API_RETRIES or not _is_transient_api_error(e):
                raise
            delay = min(60, 5 * 2 ** attempt)
            logger.warning(f"Transient API error ({type(e).__name__}: {e}); retrying in {delay}s")
            time.sleep(delay)


def _is_bad_request(err: Exception) -> bool:
    return isinstance(err, openai.BadRequestError) or _status_code(err) == 400


def _is_context_length_error(err: Exception) -> bool:
    msg = str(err).lower()
    return any(s in msg for s in (
        "context length", "context_length_exceeded", "maximum context",
        "reduce the length of the messages", "longer than the model's context length",
    ))


# ---------------------------------------------------------------------------
# SHERLOC exploration loop (reference: SherlocGenerationTask.process_single_datapoint)
# ---------------------------------------------------------------------------

def run_sherloc_episode(problem_statement: str, repo_dict: dict, llm, model_name: str,
                        system_prompt: str, settings: SherlocSettings,
                        tool_executor: ToolExecutor, instance_id: str) -> Dict[str, Any]:
    """Run one SHERLOC localization episode and return its result record."""
    prefix = f"[{instance_id}] "

    if not problem_statement.strip():
        logger.warning(f"{prefix}Skipping data point due to empty problem statement")
        return {"status": "skipped", "reason": "empty_problem_statement", "turns": [],
                "locations": None, "findings": None, "num_turns": 0, "total_generated_tokens": 0}

    total_steps = settings.total_steps
    max_tokens = settings.inference.tokens_to_generate
    chat_history: List[Dict[str, Any]] = []
    total_generated_tokens = 0

    tree_structure = RepoManager.tree_repo_dict(repo_dict, settings.show_line_counts)
    inputs = f"""
### Problem Description
{problem_statement}

### Repository Structure
{tree_structure}
"""
    data_point: Dict[str, Any] = {"turns": [{
        "turn_id": 0,
        "inputs": inputs,
        "assistant": "",
        "tool_call": None,
        "tool_output": "",
        "_retry_count": 0,
        "_input_tokens": len(inputs) // 4,
    }]}

    def renumber(turns):
        for i, turn in enumerate(turns):
            turn["turn_id"] = i

    reason = None
    status = None
    try:
        for cur_step in range(total_steps):
            logger.info(f"{prefix}Step {cur_step + 1}/{total_steps}")

            # Keep the opening turn and the most recent turns within the context budget.
            safe_max = int(settings.max_seq_length * settings.context_safety_margin)
            original_turns_count = len(data_point["turns"])
            data_point["turns"], truncation_stats = ContextManager.first_and_recent_truncate(
                data_point["turns"], safe_max, max_tokens
            )
            if truncation_stats["removed_turns"] > 0:
                logger.info(f"{prefix}Truncated dialogue from {original_turns_count} to "
                            f"{len(data_point['turns'])} turns: {truncation_stats}")

            prepared = copy.deepcopy(data_point)
            context_turn_ids = [t.get("turn_id", i) for i, t in enumerate(prepared["turns"])]

            if settings.enable_loop_detection and len(chat_history) >= settings.loop_detection_threshold - 1:
                is_loop, loop_info = ContextManager.detect_repetitive_tool_calls(
                    chat_history, settings.loop_detection_threshold - 1
                )
                if is_loop:
                    logger.warning(f"{prefix}Potential loop detected before generation: {loop_info}")
                    prepared["turns"] = ContextManager.inject_loop_intervention(prepared["turns"], loop_info)
                    data_point["turns"] = copy.deepcopy(prepared["turns"])
                    renumber(data_point["turns"])

            if settings.enable_enhanced_context:
                will_fit, error_msg, context_stats = ContextManager.check_context_before_generation(
                    prepared, settings
                )
                if not will_fit:
                    logger.error(f"{prefix}Context length check failed: {error_msg} {context_stats}")
                    status = "failed"
                    reason = "context_length_exceeded_proactive"
                    break

            if ContextManager.should_inject_final_turn(
                cur_step, total_steps, status, enable_final_turn_prompt=settings.enable_final_turn_prompt
            ):
                logger.info(f"{prefix}Injecting final turn instruction at step {cur_step + 1}/{total_steps}")
                prepared["turns"] = ContextManager.inject_final_turn_instruction(
                    prepared["turns"], is_final_turn=True
                )
                # The instruction may extend the last turn or open a new one; persist either way.
                added_turn = len(prepared["turns"]) > len(data_point["turns"])
                data_point["turns"] = copy.deepcopy(prepared["turns"])
                if added_turn:
                    renumber(data_point["turns"])
                context_turn_ids = [t.get("turn_id", i) for i, t in enumerate(prepared["turns"])]

            response_type = "final_turn" if cur_step == total_steps - 1 else "normal"

            retry_count = 0
            actual_generated_tokens = 0
            hit_cap = False
            llm_output: Dict[str, Any] = {}
            while retry_count <= settings.max_retries:
                try:
                    logger.info(f"{prefix}Sending {len(prepared['turns'])} turns to LLM "
                                f"(attempt {retry_count + 1})")
                    llm_output = _generate(llm, model_name, system_prompt, prepared["turns"], settings)
                    llm_output["_context_turn_ids"] = context_turn_ids
                    actual_generated_tokens = llm_output["num_generated_tokens"]
                    # A reply that spends its entire budget was almost certainly cut off.
                    hit_cap = (actual_generated_tokens >= max_tokens
                               or llm_output.get("finish_reason") == "length")

                    if settings.enable_response_length_management:
                        if hit_cap:
                            logger.warning(f"{prefix}Response at token limit: "
                                           f"{actual_generated_tokens}/{max_tokens} (likely truncated)")
                        elif actual_generated_tokens > max_tokens * settings.response_critical_threshold:
                            logger.warning(f"{prefix}Response approaching token limit: "
                                           f"{actual_generated_tokens}/{max_tokens}")
                        elif actual_generated_tokens > max_tokens * settings.response_warning_threshold:
                            logger.warning(f"{prefix}Response length warning: "
                                           f"{actual_generated_tokens}/{max_tokens}")

                        if hit_cap and retry_count < settings.max_retries:
                            failure_analysis = ContextManager.analyze_response_failure(
                                llm_output["generation"], prepared["turns"], settings.max_seq_length,
                                actual_total_tokens=actual_generated_tokens,
                            )
                            logger.info(f"{prefix}Failure analysis: {failure_analysis}")

                            if settings.inject_length_warnings:
                                # Ask for brevity where it is affordable: on a final turn the
                                # answer itself must shrink, otherwise the reasoning should.
                                if response_type == "final_turn":
                                    warning_msg = (
                                        "Please provide a shorter, more focused answer with concise findings "
                                        "and locations. Include only the most essential bullet points in "
                                        "<findings> without excessive explanation, and directly state the bug "
                                        "locations in <locations>."
                                    )
                                else:
                                    warning_msg = (
                                        "Please be more concise: reduce your thinking/reasoning to only the most "
                                        "essential analysis steps. Skip redundant explanations and focus on the "
                                        "critical path to finding the bug."
                                    )
                                prepared["turns"] = ContextManager.inject_length_warning(
                                    prepared["turns"], warning_msg
                                )
                                data_point["turns"] = copy.deepcopy(prepared["turns"])
                                renumber(data_point["turns"])
                                context_turn_ids = [t.get("turn_id", i) for i, t in enumerate(prepared["turns"])]

                            retry_count += 1
                            continue
                    break

                except Exception as e:
                    if not _is_bad_request(e):
                        raise
                    status = "failed"
                    if _is_context_length_error(e):
                        logger.warning(f"{prefix}Generation failed due to running out of context")
                        reason = "context_length_exceeded"
                    else:
                        logger.warning(f"{prefix}Generation failed with BadRequestError: {e}")
                        reason = f"bad_request_error: {str(e)}"
                    break

            if status == "failed":
                break

            total_generated_tokens += actual_generated_tokens
            if hit_cap:
                llm_output["_likely_truncated"] = True
            chat_history.append(llm_output)

            # Second loop check, now including the reply that was just produced.
            if settings.enable_loop_detection and len(chat_history) >= settings.loop_detection_threshold:
                is_loop, loop_info = ContextManager.detect_repetitive_tool_calls(
                    chat_history, settings.loop_detection_threshold
                )
                if is_loop:
                    logger.warning(f"{prefix}Loop detected: {loop_info}")
                    data_point["turns"] = ContextManager.inject_loop_intervention(data_point["turns"], loop_info)
                    renumber(data_point["turns"])
                    chat_history[-1].update(
                        {"_loop_detected": True, "_loop_info": loop_info, "_intervention_added": True}
                    )

            try:
                extracted_block = DialogProcessor.extract_response(llm_output["generation"], settings)
            except Exception as e:
                logger.error(f"{prefix}Error extracting response from LLM output: {e}")
                status = "failed"
                reason = f"response_extraction_error: {str(e)}"
                break

            if not extracted_block:
                logger.warning(f"{prefix}Model failed to generate a tool use or location. Ending generation.")
                status = "failed"
                reason = ("response_truncated_at_token_limit" if llm_output.get("_likely_truncated")
                          else "no_tool_or_location_generated")
                break

            current_turn = data_point["turns"][-1]
            current_turn["assistant"] = llm_output["generation"]
            current_turn["_llm_tokens"] = actual_generated_tokens
            current_turn["_context_turn_ids"] = context_turn_ids
            current_turn["_retry_count"] = retry_count
            if extracted_block.get("type") == "tool_calls":
                current_turn["tool_call"] = extracted_block.get("tool_call", None)
            elif extracted_block.get("type") == "locations":
                current_turn["locations"] = extracted_block.get("locations", [])
                current_turn["findings"] = extracted_block.get("findings")

            if extracted_block.get("type") == "tool_calls":
                if "tool_call" not in extracted_block:
                    status = "failed"
                    reason = "missing_tool_call_in_extracted_block"
                    break

                tool_name = extracted_block.get("tool_call", {}).get("tool", "unknown")
                logger.info(f"{prefix}Executing tool: {tool_name}")
                tool_output, tool_tokens = tool_executor.execute_tool(extracted_block["tool_call"], repo_dict)

                current_turn["tool_output"] = tool_output
                current_turn["_tool_tokens"] = tool_tokens
                # The tool output opens the next turn: it is what the model reads next.
                data_point["turns"].append({
                    "turn_id": len(data_point["turns"]),
                    "inputs": tool_output,
                    "assistant": "",
                    "tool_call": None,
                    "tool_output": "",
                    "_retry_count": 0,
                })
            elif extracted_block.get("type") == "locations":
                if "locations" not in extracted_block:
                    status = "failed"
                    reason = "missing_locations_in_extracted_block"
                    break
                # The model committed to an answer, which ends the episode.
                data_point["locations"] = extracted_block["locations"]
                data_point["findings"] = extracted_block.get("findings")
                status = "success"
                reason = None
                break

            if cur_step == total_steps - 1 and status is None:
                status = "failed"
                reason = "max_steps_exceeded"
                break

        if status is None:
            status = "failed"
            if reason is None:
                reason = "unknown_failure"
    except Exception as e:
        logger.exception(f"{prefix}Error in SHERLOC episode: {e}")
        status = "failed"
        reason = f"exception: {str(e)}"

    logger.info(f"{prefix}SHERLOC completed (status={status}, reason={reason})")
    return {
        "status": status,
        "reason": reason,
        "locations": data_point.get("locations"),
        "findings": data_point.get("findings"),
        "num_turns": len(chat_history),
        "total_generated_tokens": total_generated_tokens,
        "turns": data_point.get("turns", []),
    }


def format_sherloc_final_output(findings: Optional[str], locations: Optional[List[Dict]]) -> str:
    """Render SHERLOC's final answer in its own <findings>/<locations> format."""
    location_lines = []
    # The reference parser returns dicts from <locations> blocks but passes Python-dict
    # replies through as-is, so a location can also be a plain string.
    for loc in locations or []:
        if isinstance(loc, str):
            line = loc.strip()
        elif isinstance(loc, dict):
            line = loc.get("raw") or (
                f"{loc['file_path']}:L{loc.get('start_line')}-L{loc.get('end_line')}"
                if loc.get("file_path") else ""
            )
        else:
            line = str(loc)
        if line:
            location_lines.append(line)
    return (
        f"<findings>\n{findings or ''}\n</findings>\n\n"
        f"<locations>\n" + "\n".join(location_lines) + "\n</locations>"
    )


# ---------------------------------------------------------------------------
# Instance orchestration
# ---------------------------------------------------------------------------

REPORT_KEYS = ("Title", "Description", "RootCause", "StepsToReproduce", "ExpectedBehavior", "ObservedBehavior")
REPORT_ATTEMPTS = 3


def run_for_instance(instance: Dict[str, Any], settings: SherlocSettings, explorer_llm,
                     system_prompt: str, tool_executor: ToolExecutor, out_summary_file: str) -> dict:
    """Orchestrate a single instance: SHERLOC exploration -> fixed report schema -> save."""
    instance_id = instance.get("instance_id")
    logger.info(f"Processing instance: {instance_id}")
    problem = instance.get("problem_statement", "") or ""

    instance_summary = {
        "instance_id": instance_id,
        "repo": instance.get("repo"),
        "base_commit": instance.get("base_commit"),
    }

    try:
        repo_dict = build_repo_snapshot(
            state.config.repo_local_path, instance.get("base_commit"), instance_id, settings
        )
    except Exception as e:
        logger.error(f"Error loading repository for {instance_id}: {e}")
        instance_summary["sherloc"] = {"status": "failed", "reason": f"repository_loading_error: {e}"}
        save_instance_result(instance_summary, out_summary_file)
        return instance_summary

    # =====================================================================
    # SHERLOC exploration — diagnostic findings for candidate code locations
    # =====================================================================
    episode = run_sherloc_episode(
        problem, repo_dict, explorer_llm, state.config.openai_model,
        system_prompt, settings, tool_executor, instance_id,
    )
    instance_summary["sherloc"] = episode

    if not episode.get("findings") and not episode.get("locations"):
        # No final findings: leave bug_report out so the merge keeps the original report.
        logger.warning(f"SHERLOC produced no final findings for {instance_id} "
                       f"({episode.get('reason')}); no report generated")
        save_instance_result(instance_summary, out_summary_file)
        return instance_summary

    # =====================================================================
    # Original report + SHERLOC's final findings -> fixed report schema
    # =====================================================================
    sherloc_output = format_sherloc_final_output(episode.get("findings"), episode.get("locations"))
    instance_summary["sherloc_final_output"] = sherloc_output
    raw_reports = []
    for attempt in range(REPORT_ATTEMPTS):
        try:
            final_bug_report = _call_with_api_retries(lambda: generate_final_bug_report(
                problem, sherloc_output,
                prompt_name="final_report_sherloc.txt",
            ))
        except Exception as e:
            logger.error(f"generate_final_bug_report failed for {instance_id}: {e}")
            instance_summary["error"] = str(e)
            break
        raw_reports.append(final_bug_report)
        parsed_report = parse_json_best_effort(
            final_bug_report, preferred_keys=["revised_report", "title", "bug_location"]
        )
        if isinstance(parsed_report, dict) and parsed_report.keys() & set(REPORT_KEYS):
            instance_summary["bug_report"] = parsed_report
            break
        logger.warning(f"Could not parse final bug report JSON for {instance_id} "
                       f"(attempt {attempt + 1}/{REPORT_ATTEMPTS})")
    if "bug_report" not in instance_summary and raw_reports:
        # An unusable report would merge as an empty problem statement; keep the original instead.
        instance_summary["bug_report_unparsed"] = raw_reports

    save_instance_result(instance_summary, out_summary_file)
    return instance_summary


# ---------------------------------------------------------------------------
# Pipeline entry point
# ---------------------------------------------------------------------------

def run_pipeline(cfg):
    """Run the SHERLOC baseline pipeline."""
    state.config = cfg
    state.llm = make_chat_llm(cfg.openai_model, cfg.llm_temperature, cfg.openai_api_base, cfg.openai_api_key_env)

    settings = SherlocSettings(
        total_steps=cfg.sherloc_total_steps,
        max_seq_length=cfg.sherloc_max_seq_length,
    )
    settings.inference.tokens_to_generate = cfg.sherloc_tokens_to_generate

    explorer_llm = make_chat_llm(cfg.openai_model, settings.inference.temperature,
                                 cfg.openai_api_base, cfg.openai_api_key_env)
    system_prompt = load_prompt("sherloc_system.txt", cfg.prompts_dir)
    tool_executor = ToolExecutor(settings, _TiktokenCounter(cfg.openai_model))

    out_file = cfg.output_file
    if not out_file:
        logger.error("No output file specified (--output)")
        return
    if not cfg.repo_local_path or not os.path.isdir(cfg.repo_local_path):
        logger.error(f"--repo-local-path must point to a local git clone: {cfg.repo_local_path!r}")
        return

    mkdirp(os.path.dirname(out_file) or ".")
    logger.info(f"Output: {out_file}")

    instances = load_json_safe(cfg.repo_instances_json)
    if not instances:
        logger.error(f"No instances found: {cfg.repo_instances_json}")
        return

    if cfg.instance_id_filter:
        want = set(str(x) for x in cfg.instance_id_filter)
        before_n = len(instances)
        instances = [i for i in instances if str(i.get("instance_id")) in want]
        logger.info(f"Instance filter: {len(instances)}/{before_n} selected")

    for inst in instances:
        instance_id = inst.get("instance_id")
        logger.info(f"\n{'='*60}\nHandling instance {instance_id}\n{'='*60}")
        try:
            run_for_instance(inst, settings, explorer_llm, system_prompt, tool_executor, out_file)
        except Exception as e:
            logger.error(f"Error processing {instance_id}: {e}")
            error_entry = {
                "instance_id": instance_id,
                "repo": inst.get("repo"),
                "base_commit": inst.get("base_commit"),
                "error": str(e),
            }
            all_entries = load_json_safe(out_file)
            all_entries.append(error_entry)
            save_json_atomic(all_entries, out_file)

    # Instances without a bug_report fall back to the original report at merge time.
    want_ids = {i.get("instance_id") for i in instances}
    entries = [e for e in load_json_safe(out_file) if e.get("instance_id") in want_ids]
    outcomes = Counter((e.get("sherloc") or {}).get("reason") or (e.get("sherloc") or {}).get("status", "error")
                       for e in entries)
    with_report = sum(1 for e in entries if "bug_report" in e)
    unparsed = sum(1 for e in entries if "bug_report_unparsed" in e)
    logger.info(f"SHERLOC summary: {with_report}/{len(entries)} instances with a generated report "
                f"({unparsed} unparsable after {REPORT_ATTEMPTS} attempts); episode outcomes: {dict(outcomes)}")
