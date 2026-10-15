# Bug Report Specification Refinement

This repository contains the artifact code for refining SWE-bench bug reports into more diagnostic reports using tool-augmented LLM agents.

The implementation supports the variants used in the paper:

| Paper name | Repository phase / source | Description |
|---|---|---|
| Original Reports | `data/by_repo/*.json` | Official SWE-bench Lite bug reports, grouped by repository. |
| SHERLOC Reports | `sherloc` / `src/agents/sherloc.py` | Independent repository-exploration baseline ([SHERLOC; Tamoyan et al., 2026](https://arxiv.org/abs/2606.24820)). Given the original bug report and the pre-fix repository, it explores the code and produces diagnostic findings for candidate code locations (location explanation, root cause, solution idea, dependencies, testing impact). Because SHERLOC does not natively produce a refined report, its final findings are combined with the original report and presented in the same fixed report schema as ExploreSpec. |
| ExploreSpec Reports | `enhance` / `src/agents/multi_agent.py` | The main pipeline: protocol-guided exploration, hierarchical trajectory compression, final report generation, and reviewer validation. |
| w/o Hierarchy | `raw_traj_ablation` / `src/agents/raw_trajectory_ablation.py` | Ablation that replaces the compressed analysis with raw agent thoughts while keeping report generation and reviewer validation. |
| w/o Reviewer | pre-reviewer output from `enhance` | Ablation saved by the main pipeline before the reviewer agent runs. |

### Trajectory-Collection Agent

In this artifact, ExploreSpec's unverified trajectory-collection run is implemented by a tool-augmented agent operating on the original bug report and pre-fix repository snapshot. The agent searches and inspects repository code, invokes code-navigation and code-graph tools, reasons about candidate failure explanations, and records the resulting thought-action-observation trajectory. The implementation uses a five-checkpoint investigation procedure to examine the defect, relevant source files, architectural relationships, and assumptions underlying a candidate fix. If the investigation stops prematurely, it resumes from the latest completed checkpoint while preserving the accumulated trajectory. The resulting trajectory is subsequently used for hierarchical specification evidence abstraction.

## Repository Layout

```text
.
├── run.py
├── requirements.txt
├── prompts/
│   ├── agent_instruction_multi_agent.txt
│   ├── classification.txt
│   ├── compress_chat_history.txt
│   ├── final_report.txt
│   ├── final_report_sherloc.txt
│   ├── reviewer_multi_agent.txt
│   └── sherloc_system.txt
├── data/
│   ├── by_repo/                  # Official SWE-bench Lite dataset: 300 instances grouped by repository
│   ├── evaluation_subset_100.json # Shared AutoCodeRover and Agentless evaluation subset
│   └── output/
│       ├── gpt_5_mini/           # Generated reports and saved trajectories for GPT-5-mini runs
│       ├── minimax2.5/           # Generated reports and saved trajectories for MiniMax M2.5 runs
│       └── merged/               # Evaluation-ready files with original and generated reports merged
├── results/
│   ├── auto_code_rover/          # 100-instance downstream evaluation
│   ├── agentless/                # 100-instance downstream evaluation
│   └── mini_swe_agent_v2/        # Full 300-instance downstream evaluation
└── src/
    ├── agents/
    │   ├── multi_agent.py
    │   ├── sherloc.py
    │   ├── sherloc_utils/        # SHERLOC tools, response parser, and context management
    │   ├── raw_trajectory_ablation.py
    │   └── common.py
    ├── tools/                    # Agent tools for classification and code navigation
    ├── graph/                    # Code graph loading/filtering utilities
    ├── utils/                    # I/O, LLM, token, JSON, embedding, and BM25 helpers
    ├── config.py
    ├── log.py
    ├── merge.py
    └── state.py
```

## Setup

Use Python 3.10+ and install the dependencies:

```bash
pip install -r requirements.txt
```

Set the API key for the model provider:

```bash
export OPENAI_API_KEY="..."
```

The default model and provider settings are configured in `src/config.py`. You can override them from the command line:

```bash
python run.py enhance --model gpt-5-mini-2025-08-07 --api-key-env OPENAI_API_KEY ...
```

## Required Inputs

The `data/by_repo/` directory contains the official SWE-bench Lite dataset used in the paper: 300 instances split into per-repository JSON files.

The `data/output/` directory contains the generated artifact outputs included with this repository:

| Directory | Contents |
|---|---|
| `data/output/gpt_5_mini/` | Per-variant GPT-5-mini outputs, including saved agent trajectories and intermediate fields. |
| `data/output/minimax2.5/` | Per-variant MiniMax M2.5 outputs, including saved agent trajectories and intermediate fields. |
| `data/output/merged/` | Evaluation-ready files. Each file preserves the original SWE-bench fields and adds the corresponding generated report variant. |

## Downstream Evaluation Artifacts

The `results/` directory contains downstream repair outputs organized by repair agent, model, and report variant. Each `combined_eval_summary.json` reports aggregate, per-repository, and per-instance results across the available report variants. Each variant's `evaluation_results.jsonl` indexes its resolved statuses, patches, and compressed trajectories.

Mini-SWE-Agent V2 was evaluated on all 300 SWE-bench Lite instances. AutoCodeRover and Agentless were evaluated on the same 100-instance subset listed in `data/evaluation_subset_100.json`.

The organization and file formats of the evaluation artifacts are described in `results/README.md`.

The manual analysis of why refined reports help is in `results/mini_swe_agent_v2/gpt_5_mini/ExploreSpec_Paired_Gain_Manual_Study.xlsx`. It covers the 56 GPT-5-mini instances where Mini-SWE-Agent V2 fails with the original report but succeeds with the ExploreSpec report, and assigns each instance its primary repair-relevant information difference. Its contents and label definitions are described in `results/README.md`.

Each generation phase expects:

| Input | Description |
|---|---|
| `--repo-instances` | JSON file containing SWE-bench instances or, for `raw_traj_ablation`, previously generated entries with `chat_history`. |
| `--repo-codegraph-index` | JSON registry pointing to code graph artifacts for the target repository instances. Not used by `sherloc`. |
| `--repo-local-path` | Local checkout of the target repository. The tools read files at each instance's `base_commit`. |
| `--output` | Output JSON path. Existing instance entries are updated in place. |

`raw_traj_ablation` also requires `--original-instances` so it can recover the original problem statement for each generated entry.

To regenerate reports from scratch, provide the local repository checkout with `--repo-local-path` and, for `enhance` and `raw_traj_ablation`, a precomputed code graph index with `--repo-codegraph-index`. The checkout must contain each instance's `base_commit` (a full clone, not a shallow one).

## Running Variants

### ExploreSpec Reports

```bash
python run.py enhance \
  --repo-instances data/by_repo/astropy__astropy.json \
  --repo-codegraph-index data/code_graph/astropy__astropy.json \
  --repo-local-path /path/to/astropy \
  --output data/output/gpt_5_mini/explorespec/astropy__astropy.json
```

The `enhance` phase writes two outputs:

| Output | Meaning |
|---|---|
| `data/output/.../wo_reviewer/<repo>.json` | Pre-reviewer report, used as the w/o Reviewer ablation. |
| path passed to `--output` | Post-reviewer ExploreSpec report. |

Use `--single-enhanced-file` to choose the pre-reviewer output path explicitly.

### SHERLOC Reports

```bash
python run.py sherloc \
  --repo-instances data/by_repo/astropy__astropy.json \
  --repo-local-path /path/to/astropy \
  --output data/output/gpt_5_mini/sherloc/astropy__astropy.json
```

The `sherloc` phase runs in two steps:

1. **SHERLOC exploration.** A port of the [reference SHERLOC implementation](https://github.com/NVIDIA-NeMo/Skills/tree/main/recipes/sherloc) (Copyright NVIDIA, Apache-2.0; license in `src/agents/sherloc_utils/LICENSE`) explores a snapshot of the repository at the instance's `base_commit` using its four read-only tools (`view_file`, `codebase_search`, `repo_tree`, `connected_tree`). It uses the reference system prompt, repository filtering, self-recovery (context truncation, loop detection, implicit tool-call recovery, response-length retries, final-turn prompting), and default budgets. The episode ends with a `<findings>` block of diagnostic findings for candidate code locations and a `<locations>` block of file paths with line ranges. Exploration uses SHERLOC's sampling settings (temperature 0.99, top-p 0.95) rather than `--temperature`, except for GPT-5 models, which only accept their default sampling settings. Transient API errors (rate limits, timeouts, 5xx) are retried with backoff and do not count as exploration steps.
2. **Fixed report schema.** The original report and SHERLOC's final findings are passed to the report generator used by ExploreSpec (`final_report_sherloc.txt`, which differs from `final_report.txt` only in how it describes the second input), producing the same report fields: `Title`, `Description`, `RootCause`, `StepsToReproduce`, `ExpectedBehavior`, `ObservedBehavior`.

Each output entry stores the SHERLOC episode under `sherloc` (`status`, `reason`, `findings`, `locations`, and the full turn-by-turn transcript), the findings passed to the report generator under `sherloc_final_output`, and the generated report under `bug_report`. Report generation is retried up to three times if the output is not valid JSON with report fields. If SHERLOC ends without findings or locations, or no attempt produces a usable report (the raw outputs are kept under `bug_report_unparsed`), no `bug_report` is written, so `merge` keeps the original report for that instance. A summary of these outcomes is logged at the end of each run.

| Option | Default | Description |
|---|---|---|
| `--sherloc-total-steps N` | `20` | Exploration step budget. The final step instructs the model to answer. |
| `--sherloc-max-seq-length N` | `262144` | Context window assumed by SHERLOC's context management. Lower it to the serving model's window. |
| `--sherloc-tokens-to-generate N` | `81920` | Per-call generation cap. |

### w/o Hierarchy Ablation

This phase starts from ExploreSpec pre-reviewer or post-reviewer entries that contain `chat_history`, then regenerates the report using raw agent thoughts rather than `compressed_analysis`.

```bash
python run.py raw_traj_ablation \
  --repo-instances data/output/gpt_5_mini/wo_reviewer/astropy__astropy.json \
  --original-instances data/by_repo/astropy__astropy.json \
  --repo-codegraph-index data/code_graph/astropy__astropy.json \
  --repo-local-path /path/to/astropy \
  --output data/output/gpt_5_mini/wo_hierarchy/astropy__astropy.json
```

### Merge Reports

Use `merge` to put generated reports back into an original SWE-bench-style file.

```bash
python run.py merge \
  --merge-original data/by_repo/astropy__astropy.json \
  --merge-enhanced data/output/gpt_5_mini/explorespec/astropy__astropy.json \
  --merge-output data/output/merged/gpt_5_mini/explorespec/astropy__astropy.json
```

## Common Options

| Option | Description |
|---|---|
| `--instance-ids ID1 ID2 ...` | Process only selected instances. |
| `--model MODEL` | Chat model name. |
| `--temperature T` | Sampling temperature. |
| `--api-base URL` | Optional custom API base. |
| `--api-key-env ENV_VAR` | Environment variable containing the API key. |
| `--use-regex-classifier` | Use the regex classifier fallback instead of the LLM classifier. |
| `--use-bm25` | Use BM25 ranking instead of the embedding ranker. |
| `--max-context-tokens N` | Token threshold used before truncating or chunking prompts. |

## Prompt Files

| Prompt | Used by |
|---|---|
| `classification.txt` | `classify_report` tool. |
| `agent_instruction_multi_agent.txt` | ExploreSpec explorer agent. |
| `compress_chat_history.txt` | Hierarchical trajectory compression. |
| `final_report.txt` | Final report generation for ExploreSpec, w/o Reviewer, and w/o Hierarchy. |
| `final_report_sherloc.txt` | Final report generation for SHERLOC: same schema and guidelines, with SHERLOC's findings as the second input. |
| `reviewer_multi_agent.txt` | Reviewer agent for ExploreSpec and w/o Hierarchy. |
| `sherloc_system.txt` | SHERLOC localization agent (reference system prompt, verbatim). |
