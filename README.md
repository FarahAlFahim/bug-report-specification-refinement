# Bug Report Specification Refinement

This repository contains the artifact code for refining SWE-bench bug reports into more diagnostic reports using tool-augmented LLM agents.

The implementation supports the variants used in the paper:

| Paper name | Repository phase / source | Description |
|---|---|---|
| Original Reports | `data/by_repo/*.json` | Official SWE-bench Lite bug reports, grouped by repository. |
| Agentic-Base Reports | `vanilla_baseline` / `src/agents/vanilla_baseline.py` | A basic tool-augmented agent without protocol-guided exploration, hierarchical compression, or reviewer validation. |
| TrajSpec Reports | `enhance` / `src/agents/multi_agent.py` | The main pipeline: protocol-guided exploration, hierarchical trajectory compression, final report generation, and reviewer validation. |
| w/o Hierarchy | `raw_traj_ablation` / `src/agents/raw_trajectory_ablation.py` | Ablation that replaces the compressed analysis with raw agent thoughts while keeping report generation and reviewer validation. |
| w/o Reviewer | pre-reviewer output from `enhance` | Ablation saved by the main pipeline before the reviewer agent runs. |

### Trajectory-Collection Agent

In this artifact, TrajSpec's unverified trajectory-collection run is implemented by a tool-augmented agent operating on the original bug report and pre-fix repository snapshot. The agent searches and inspects repository code, invokes code-navigation and code-graph tools, reasons about candidate failure explanations, and records the resulting thought-action-observation trajectory. The implementation uses a five-checkpoint investigation procedure to examine the defect, relevant source files, architectural relationships, and assumptions underlying a candidate fix. If the investigation stops prematurely, it resumes from the latest completed checkpoint while preserving the accumulated trajectory. The resulting trajectory is subsequently used for hierarchical specification evidence abstraction.

## Repository Layout

```text
.
├── run.py
├── requirements.txt
├── prompts/
│   ├── agent_instruction_multi_agent.txt
│   ├── agent_instruction_no_protocol.txt
│   ├── classification.txt
│   ├── compress_chat_history.txt
│   ├── final_report.txt
│   └── reviewer_multi_agent.txt
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
    │   ├── vanilla_baseline.py
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

Each generation phase expects:

| Input | Description |
|---|---|
| `--repo-instances` | JSON file containing SWE-bench instances or, for `raw_traj_ablation`, previously generated entries with `chat_history`. |
| `--repo-codegraph-index` | JSON registry pointing to code graph artifacts for the target repository instances. |
| `--repo-local-path` | Local checkout of the target repository. The tools read files at each instance's `base_commit`. |
| `--output` | Output JSON path. Existing instance entries are updated in place. |

`raw_traj_ablation` also requires `--original-instances` so it can recover the original problem statement for each generated entry.

To regenerate reports from scratch, provide a precomputed code graph index with `--repo-codegraph-index` and the corresponding local repository checkout with `--repo-local-path`.

## Running Variants

### TrajSpec Reports

```bash
python run.py enhance \
  --repo-instances data/by_repo/astropy__astropy.json \
  --repo-codegraph-index data/code_graph/astropy__astropy.json \
  --repo-local-path /path/to/astropy \
  --output data/output/gpt_5_mini/trajspec/astropy__astropy.json
```

The `enhance` phase writes two outputs:

| Output | Meaning |
|---|---|
| `data/output/.../wo_reviewer/<repo>.json` | Pre-reviewer report, used as the w/o Reviewer ablation. |
| path passed to `--output` | Post-reviewer TrajSpec report. |

Use `--single-enhanced-file` to choose the pre-reviewer output path explicitly.

### Agentic-Base Reports

```bash
python run.py vanilla_baseline \
  --repo-instances data/by_repo/astropy__astropy.json \
  --repo-codegraph-index data/code_graph/astropy__astropy.json \
  --repo-local-path /path/to/astropy \
  --output data/output/gpt_5_mini/agentic_base/astropy__astropy.json
```

### w/o Hierarchy Ablation

This phase starts from TrajSpec pre-reviewer or post-reviewer entries that contain `chat_history`, then regenerates the report using raw agent thoughts rather than `compressed_analysis`.

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
  --merge-enhanced data/output/gpt_5_mini/trajspec/astropy__astropy.json \
  --merge-output data/output/merged/gpt_5_mini/trajspec/astropy__astropy.json
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
| `agent_instruction_multi_agent.txt` | TrajSpec explorer agent. |
| `agent_instruction_no_protocol.txt` | Agentic-Base explorer agent. |
| `compress_chat_history.txt` | Hierarchical trajectory compression. |
| `final_report.txt` | Final report generation for all active variants. |
| `reviewer_multi_agent.txt` | Reviewer agent for TrajSpec and w/o Hierarchy. |
