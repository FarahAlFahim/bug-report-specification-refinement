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
    │   ├── ExploreSpec_Paired_Gain_Manual_Study.xlsx
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

## Paired-Gain Manual Study

`mini_swe_agent_v2/gpt_5_mini/ExploreSpec_Paired_Gain_Manual_Study.xlsx` contains the manual analysis of why refined reports help. It covers the 56 instances in the GPT-5-mini setting where Mini-SWE-Agent V2 fails with the original report but succeeds with the ExploreSpec report (`original` is `false` and `explorespec` is `true` in `variants_resolved_comparison` of `combined_eval_summary.json`). Because the repair agent, model, and experimental setting are unchanged, these cases compare the information available to the same agent before and after refinement.

For each instance, the original and refined reports, the corresponding repair trajectories and submitted patches, the relevant pre-fix source code, and the developer repair were compared. The analysis examines whether ExploreSpec adds or clarifies information about the failure mechanism, the behavioral requirement, and the implementation scope, and assigns each instance one primary repair-relevant information difference:

| Primary pattern | Report-level difference | Instances |
|---|---|---|
| Missing implementation behavior | The original report omitted an implementation behavior needed for the repair. ExploreSpec made this behavior explicit. | 15 (26.8%) |
| Incomplete repair scope | The original report covered the visible failure but omitted another required location, case, or execution path. ExploreSpec identified the additional scope. | 12 (21.4%) |
| Missing root cause | The original report described the symptom or failure location without identifying the source behavior responsible for it. ExploreSpec clarified the underlying cause. | 10 (17.9%) |
| Missing component interaction | The original report omitted how behavior in one component affects another. ExploreSpec clarified the relevant interaction between components. | 6 (10.7%) |
| Ambiguous requirement | The expected behavior in the original report was unclear or too narrowly specified. ExploreSpec clarified what behavior should hold. | 5 (8.9%) |
| Overly broad repair scope | The original report did not identify the responsible local code, leading repair toward broader shared logic. ExploreSpec narrowed the relevant implementation scope. | 4 (7.1%) |
| Other effects | The refined report provided clearer repair information, but the observed outcome also depended on patch generation or evaluation effects and could not be attributed solely to the report difference. | 4 (7.1%) |
| **Total** | | **56 (100%)** |

In 52 of the 56 cases (92.9%), the refined report added or clarified repair-relevant information that was missing or unclear in the original report. The remaining four cases are labeled Other effects.

The workbook contains:

| Sheet | Contents |
|---|---|
| `Summary` | Study scope, the analysis procedure, label definitions and counts, evidence-level counts, and per-repository case counts. Counts are formulas over the repository sheets. |
| One sheet per repository (`astropy`, `django`, …, `sympy`) | One row per instance with the original bug report, the ExploreSpec report, the developer (gold) patch, the failure mechanism and developer fix, observations on each report, the paired trajectory evidence, the evidence strength, and the final label. |

Evidence strength records how directly the paired trajectories support the report difference: `Strong` (35 cases) and `Moderate` (17 cases) together form the 52 cases above, and `Limited` (4 cases) corresponds to the four Other effects cases. The repair trajectories and submitted patches referenced by the study are in `mini_swe_agent_v2/gpt_5_mini/original/` and `mini_swe_agent_v2/gpt_5_mini/explorespec/` under `<repository>/<instance_id>/`.
