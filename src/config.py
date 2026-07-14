"""Centralized CLI configuration for the artifact pipelines."""

import argparse
from dataclasses import dataclass, field
from typing import List


@dataclass
class Config:
    # --- Phase selection ---
    phase: str = "enhance"

    # --- Paths ---
    repo_instances_json: str = ""
    repo_codegraph_index: str = ""
    repo_local_path: str = ""
    original_instances_json: str = ""
    output_file: str = ""
    single_enhanced_file: str = ""

    # --- Data dirs ---
    data_dir: str = "data"
    output_dir: str = "data/output"
    code_graph_base_dir: str = "data/code_graph"
    prompts_dir: str = "prompts"
    log_dir: str = "logs"
    embeddings_cache_dir: str = "embeddings_cache"

    # --- Model ---
    openai_model: str = "gpt-5-mini-2025-08-07"
    openai_api_key_env: str = "OPENAI_API_KEY"
    openai_api_base: str = ""
    embed_model: str = "text-embedding-3-large"
    llm_temperature: float = 1.0

    # --- Features ---
    use_llm_classifier: bool = True
    use_bm25_ranking: bool = False

    # --- Limits ---
    embed_top_k: int = 5
    embed_max_tokens: int = 120000
    embed_batch_char_trunc: int = 30000
    agent_max_iterations: int = 20
    subgraph_hops: int = 2
    subgraph_max_nodes: int = 40
    token_est_per_line: int = 3
    max_context_tokens: int = 250000

    # --- Filtering ---
    instance_id_filter: List[str] = field(default_factory=list)
    exclude_tests: bool = True
    exclude_dirs: List[str] = field(default_factory=lambda: [
        "tests", "test", "third_party", "vendor", "dist", "build", "__pycache__"
    ])

    # --- Merge ---
    merge_original: str = ""
    merge_enhanced: str = ""
    merge_output: str = ""
    merge_strict: bool = False


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Bug Report Specification Refinement Artifact",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Phases:
  enhance            Generate TrajSpec reports
  vanilla_baseline   Generate Agentic-Base reports
  raw_traj_ablation  Ablation: raw Thoughts instead of compressed analysis
  merge              Merge original + generated reports

Examples:
  python run.py enhance --repo-instances data/by_repo/django__django.json \\
      --repo-codegraph-index data/code_graph/django__django.json \\
      --repo-local-path /path/to/django \\
      --output data/output/trajspec/django__django.json

  python run.py vanilla_baseline --repo-instances data/by_repo/django__django.json \\
      --repo-codegraph-index data/code_graph/django__django.json \\
      --repo-local-path /path/to/django \\
      --output data/output/agentic_base/django__django.json

  python run.py raw_traj_ablation \\
      --repo-instances data/output/wo_reviewer/django__django.json \\
      --original-instances data/by_repo/django__django.json \\
      --repo-codegraph-index data/code_graph/django__django.json \\
      --repo-local-path /path/to/django \\
      --output data/output/wo_hierarchy/django__django.json

  python run.py merge --merge-original data/by_repo/django__django.json \\
      --merge-enhanced data/output/trajspec/django__django.json \\
      --merge-output data/output/merged/django__django.json
"""
    )

    p.add_argument("phase", nargs="?", default="enhance",
                   choices=["enhance", "vanilla_baseline", "raw_traj_ablation", "merge"],
                   help="Pipeline phase to run (default: enhance)")

    # --- Paths ---
    p.add_argument("--repo-instances", dest="repo_instances_json", default="",
                   help="Path to SWE-bench per-repo JSON instances")
    p.add_argument("--repo-codegraph-index", dest="repo_codegraph_index", default="",
                   help="Path to codegraph index JSON")
    p.add_argument("--repo-local-path", dest="repo_local_path", default="",
                   help="Path to local git clone of the repo")
    p.add_argument("--original-instances", dest="original_instances_json", default="",
                   help="Path to original SWE-bench instances for raw_traj_ablation")
    p.add_argument("--output", dest="output_file", default="",
                   help="Output file path")
    p.add_argument("--single-enhanced-file", dest="single_enhanced_file", default="",
                   help="Pre-reviewer output file for the enhance phase")

    # --- Data dirs ---
    p.add_argument("--data-dir", dest="data_dir", default="data")
    p.add_argument("--output-dir", dest="output_dir", default="data/output")
    p.add_argument("--prompts-dir", dest="prompts_dir", default="prompts")
    p.add_argument("--log-dir", dest="log_dir", default="logs")

    # --- Model ---
    defaults = Config()
    p.add_argument("--model", dest="openai_model", default=defaults.openai_model)
    p.add_argument("--embed-model", dest="embed_model", default=defaults.embed_model)
    p.add_argument("--temperature", dest="llm_temperature", type=float,
                   default=defaults.llm_temperature)
    p.add_argument("--api-base", dest="openai_api_base", default=defaults.openai_api_base,
                   help="Custom API base URL")
    p.add_argument("--api-key-env", dest="openai_api_key_env",
                   default=defaults.openai_api_key_env,
                   help="Environment variable containing the API key")

    # --- Features ---
    p.add_argument("--use-regex-classifier", dest="use_llm_classifier",
                   action="store_false", help="Use regex instead of LLM classification")
    p.add_argument("--use-bm25", dest="use_bm25_ranking", action="store_true",
                   help="Use BM25 ranking instead of embeddings")

    # --- Limits ---
    p.add_argument("--embed-top-k", dest="embed_top_k", type=int, default=5)
    p.add_argument("--agent-max-iter", dest="agent_max_iterations", type=int, default=20)
    p.add_argument("--subgraph-hops", dest="subgraph_hops", type=int, default=2)
    p.add_argument("--max-context-tokens", dest="max_context_tokens", type=int,
                   default=defaults.max_context_tokens)

    # --- Filtering ---
    p.add_argument("--instance-ids", dest="instance_id_filter", nargs="*", default=[],
                   help="Only process these instance IDs")

    # --- Merge ---
    p.add_argument("--merge-original", dest="merge_original", default="")
    p.add_argument("--merge-enhanced", dest="merge_enhanced", default="")
    p.add_argument("--merge-output", dest="merge_output", default="")
    p.add_argument("--merge-strict", dest="merge_strict", action="store_true")

    return p


def load_config(argv=None) -> Config:
    """Parse CLI args and return a Config dataclass."""
    parser = build_parser()
    args = parser.parse_args(argv)

    cfg = Config()
    for k, v in vars(args).items():
        if hasattr(cfg, k):
            setattr(cfg, k, v)
    return cfg
