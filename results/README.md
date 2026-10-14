# Downstream Repair Results

This directory contains downstream repair artifacts used to evaluate the report variants. Results are organized by repair agent, model, and report variant.

```text
.
├── auto_code_rover/
│   └── gpt_5_mini/
│       ├── combined_eval_summary.json
│       ├── original/
│       ├── sherloc/
│       └── explorespec/
├── agentless/
│   └── gpt_5_mini/
│       ├── combined_eval_summary.json
│       ├── original/
│       ├── sherloc/
│       └── explorespec/
└── mini_swe_agent_v2/
    ├── gpt_5_mini/
    │   ├── combined_eval_summary.json
    │   ├── original/
    │   ├── sherloc/
    │   ├── explorespec/
    │   ├── wo_reviewer/
    │   └── wo_hierarchy/
    └── minimax2.5/
        ├── combined_eval_summary.json
        ├── original/
        ├── sherloc/
        └── explorespec/
```

Each report-variant directory follows this structure:

```text
<report_variant>/
├── evaluation_results.jsonl
└── <repository>/
    └── <instance_id>/
        ├── <instance_id>.patch
        └── <instance_id>.traj.json.gz
```

Each `combined_eval_summary.json` reports aggregate, per-repository, and per-instance results across the available report variants. Each variant's `evaluation_results.jsonl` indexes its resolved statuses, patches, and compressed trajectories.

Mini-SWE-Agent V2 uses all 300 canonical SWE-bench Lite instances. AutoCodeRover and Agentless use the same 100-instance subset recorded in `data/evaluation_subset_100.json`. AutoCodeRover trajectories retain its native structured trajectory data. Agentless trajectories are JSON containers holding the corresponding localization and repair stage logs.

The MiniMax M2.5 evaluation includes Original Reports, SHERLOC Reports, and ExploreSpec Reports. The w/o Reviewer and w/o Hierarchy ablations were evaluated only with GPT-5-mini and therefore do not appear under `minimax2.5/`.
