# Acceptance criteria

Status legend: **Tested** = automated tests exercise it (run with the fallback runner in the build environment); **Yours to verify** = needs a real
browser, real services or Windows, which the build environment did not have. Nothing here is marked done without evidence.

| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1 | Large log file can be uploaded | Tested (logic) · Yours to verify (browser upload) | `tests/test_large_files.py::test_5mb_log_runs_through_the_whole_pipeline`, `tests/test_ui_pages.py::test_upload_flow_and_validation_errors`; 50 MB limit in `.streamlit/config.toml` |
| 2 | Log is actually parsed | Tested | `tests/test_parser.py::test_bracketed_line_fields`, `tests/test_demo_parse.py::test_demo_log_line_accounting` |
| 3 | Errors are detected | Tested | `tests/test_demo_grouping.py::test_timeout_root_cause_group_matches_raw_counts` |
| 4 | Similar errors are grouped | Tested | `tests/test_grouper.py::test_same_exception_different_values_is_one_group`, `tests/test_grouper.py::test_numbers_in_exception_messages_never_split_groups` |
| 5 | Root cause analysis works | Tested (rule-based; LLM optional) | `tests/test_demo_rca.py::test_root_incident_report_is_grounded_in_real_log_and_code` |
| 6 | Source-code files can be searched | Tested | `tests/test_search.py::test_bm25_ranks_relevant_chunk_first` |
| 7 | Relevant source snippets are retrieved | Tested | `tests/test_demo_retrieval.py::test_every_frame_in_the_demo_log_is_verified_against_real_source` |
| 8 | AI analysis is clearly separated from evidence | Tested | `tests/test_rca.py::test_basic_fields_and_separation_of_evidence_and_inference`, `tests/test_enhancer.py::test_model_cannot_overwrite_observed_evidence_via_extra_keys` |
| 9 | Jira report is generated | Tested | `tests/test_jira_ticket.py::test_root_incident_ticket_has_every_required_section` |
| 10 | Reports can be downloaded | Tested (data and buttons) · Yours to verify (browser download) | `tests/test_exporters_jira.py::test_write_exports_creates_all_files_and_sanitizes_names`, `tests/test_ui_pages.py::test_all_pages_render_with_a_live_run_and_walk_the_incident_flow` |
| 11 | Streamlit UI works | Tested with a stand-in · **Yours to verify** with real Streamlit | `tests/test_ui_pages.py::test_demo_flow_load_analyze_and_dashboard_metrics`, `tests/test_ui_apptest.py::test_demo_flow_end_to_end` (runs only where Streamlit is installed) |
| 12 | Tests pass | 374 passed in the fallback runner · **Yours to verify** with real `pytest` | `python scripts\verify_release.py --tests` |
| 13 | Benchmark can be executed | Tested (ran in the build environment) | `tests/test_benchmarks.py::test_full_benchmark_run_writes_json_and_markdown` |
| 14 | No secrets are included | Tested | `tests/test_security.py::test_repository_contains_no_secrets`, `tests/test_release.py::test_forbidden_files_are_detected_in_a_dirty_tree`, `python scripts\verify_release.py --zip ...` |
| 15 | README is complete | Tested for sections, links and honesty · screenshots/GIF/benchmarks pending (yours) | `tests/test_readme.py::test_required_sections_exist`, `tests/test_readme.py::test_readme_makes_no_unbacked_claims` |
| 16 | Architecture diagram exists | Tested (syntax only) · **Yours to verify** rendering on GitHub | `tests/test_readme.py::test_mermaid_diagrams_are_present_and_balanced` |
| 17 | Demo instructions exist | Tested | `tests/test_demo_tools.py::test_every_label_in_the_plan_is_clickable_in_the_real_ui` |
| 18 | GitHub structure is clean | Tested | `tests/test_structure.py::test_required_paths_exist`, `tests/test_release.py::test_commit_script_covers_the_repository_and_creates_a_clean_history` |
| 19 | Final ZIP is created | Done | `bug-report-log-analyzer-final.zip`, built by `scripts/build_release_zip.py` and checked with `scripts/verify_release.py --zip` |
| 20 | Windows setup instructions are provided | Written · **Yours to verify** on Windows | `README.md` Installation, `docs/release_checklist.md` |

## Not verified by the author (no access in the build environment)
Real `pytest` and Pydantic runs, real Streamlit rendering and browser downloads, real Ollama and Jira, Windows-only code (peak memory and RAM readers, junction handling),
the GitHub Actions workflow, and the rendering of the Mermaid diagrams.

## Not done by design
No fabricated screenshots, GIF, benchmark numbers, coverage percentage, resume metrics or public deployment. Each has a tool and a guide to produce it from your own runs.
