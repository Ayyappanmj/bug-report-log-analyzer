# Testing (Phase 10)

Run everything: `pytest` · quick run: `pytest -m "not slow"` · with coverage: `pip install -r requirements-dev.txt` then
`pytest --cov=. --cov-report=term-missing` (or `.\scripts\run_tests.ps1 -Coverage`).
No coverage percentage is claimed anywhere in this project: measure it on your machine.
Machines without pytest can use the fallback runner: `python scripts\run_basic_checks.py` (set `SKIP_SLOW=1` to skip slow tests).

## What each requirement is tested by
The test `tests/test_testing_matrix.py` fails if any test named here no longer exists.

| Area | Tests |
|---|---|
| Log parser | `tests/test_parser.py::test_bracketed_line_fields`, `tests/test_parser.py::test_json_lines_with_alternate_keys`, `tests/test_parser.py::test_java_style_stack_trace_attached` |
| Log normalization | `tests/test_normalizer.py::test_normalize_message_masks_volatile_parts`, `tests/test_normalizer.py::test_timestamp_formats` |
| Error extraction | `tests/test_extractor.py::test_python_chain_root_and_surfaced`, `tests/test_extractor.py::test_java_chain_root_is_last_cause` |
| Stack-trace parsing | `tests/test_extractor.py::test_python_311_caret_lines_are_skipped`, `tests/test_extractor.py::test_javascript_frames` |
| Error grouping | `tests/test_grouper.py::test_same_exception_different_values_is_one_group`, `tests/test_grouper.py::test_ranking_severity_and_frequency`, `tests/test_grouper.py::test_numbers_in_exception_messages_never_split_groups` |
| Code scanner | `tests/test_scanner.py::test_scans_supported_languages_and_excludes_directories`, `tests/test_scanner.py::test_symlinks_are_not_followed` |
| Code search | `tests/test_search.py::test_bm25_ranks_relevant_chunk_first`, `tests/test_chunker.py::test_python_functions_classes_and_qualnames` |
| Source-code retrieval | `tests/test_retriever.py::test_verified_exact_by_code_text`, `tests/test_demo_retrieval.py::test_every_frame_in_the_demo_log_is_verified_against_real_source`, `tests/test_retriever.py::test_line_moved_is_not_verified` |
| Root-cause analysis | `tests/test_rca.py::test_basic_fields_and_separation_of_evidence_and_inference`, `tests/test_demo_rca.py::test_root_incident_report_is_grounded_in_real_log_and_code` |
| Root-cause schema | `tests/test_error_handling.py::test_report_schema_stays_in_sync_with_the_pydantic_model`, `tests/test_schemas.py::test_valid_analysis_defaults` |
| Jira report generation | `tests/test_jira_ticket.py::test_root_incident_ticket_has_every_required_section`, `tests/test_jira_ticket.py::test_wiki_markup_escapes_and_code_blocks` |
| Invalid AI output | `tests/test_enhancer.py::test_two_invalid_replies_fall_back_to_deterministic_report`, `tests/test_llm_validation.py::test_invalid_payloads_are_rejected` |
| Large-file handling | `tests/test_large_files.py::test_5mb_log_parses_and_groups_exactly`, `tests/test_large_files.py::test_reading_a_huge_file_is_streamed_not_loaded`, `tests/test_large_files.py::test_one_giant_line_is_truncated_with_bounded_memory` |
| Missing source file | `tests/test_error_handling.py::test_source_file_missing_or_renamed_is_reported_not_invented`, `tests/test_retriever.py::test_symbol_fallback_when_file_missing` |
| Malformed logs | `tests/test_robustness.py::test_parser_and_grouper_survive_random_input_and_keep_invariants`, `tests/test_error_handling.py::test_malformed_and_binary_inputs_produce_a_valid_empty_run` |
| Empty logs | `tests/test_ingest.py::test_empty_file`, `tests/test_parser.py::test_empty_input`, `tests/test_error_handling.py::test_log_with_only_info_events_has_no_groups` |
| Timeouts | `tests/test_providers.py::test_timeout_is_retriable_error`, `tests/test_error_handling.py::test_slow_llm_times_out_and_falls_back_end_to_end`, `tests/test_error_handling.py::test_jira_timeout_is_a_clean_error_without_leaking_the_token` |
| Error handling | `tests/test_error_handling.py::test_one_failing_group_is_contained_and_reported`, `tests/test_error_handling.py::test_enhancer_never_raises_even_for_misbehaving_providers`, `tests/test_error_handling.py::test_history_failure_does_not_break_the_ui_flow` |
| Security | `tests/test_redaction.py::test_common_secrets_are_masked_and_counted`, `tests/test_ingest.py::test_safe_join_blocks_traversal`, `tests/test_robustness.py::test_regexes_do_not_blow_up_on_adversarial_lines`, `tests/test_security.py::test_every_secret_family_is_redacted`, `tests/test_security.py::test_exports_do_not_contain_live_links_images_or_html`, `tests/test_security.py::test_api_key_is_never_forwarded_to_a_redirect_target`, `tests/test_security.py::test_path_policy_blocks_roots_sensitive_dirs_and_escapes`, `tests/test_security.py::test_retriever_never_opens_paths_taken_from_a_log`, `tests/test_security.py::test_application_code_has_no_dynamic_execution_or_unsafe_deserialization`, `tests/test_security.py::test_a_hostile_log_end_to_end_stays_inert` |
| Benchmark tooling | `tests/test_benchmarks.py::test_generator_counts_match_what_the_pipeline_finds`, `tests/test_benchmarks.py::test_bullets_use_only_measured_numbers`, `tests/test_benchmarks.py::test_bullets_refuse_without_data_and_say_what_is_missing`, `tests/test_benchmarks.py::test_manual_trial_is_timed_checked_and_recorded` |
| Documentation honesty | `tests/test_readme.py::test_readme_makes_no_unbacked_claims`, `tests/test_readme.py::test_every_relative_link_and_path_exists`, `tests/test_readme.py::test_documents_contain_no_invented_urls`, `tests/test_readme.py::test_media_is_referenced_only_if_it_exists` |
| Demo recording tools | `tests/test_demo_tools.py::test_every_label_in_the_plan_is_clickable_in_the_real_ui`, `tests/test_demo_tools.py::test_demo_guide_table_is_the_plan`, `tests/test_demo_tools.py::test_gif_markdown_is_printed_only_for_a_valid_recording`, `tests/test_demo_tools.py::test_rehearsal_flags_an_overrun` |
| UI | `tests/test_ui_pages.py::test_demo_flow_load_analyze_and_dashboard_metrics`, `tests/test_ui_apptest.py::test_demo_flow_end_to_end` |

## Bugs found by this phase's tests (and fixed)
- Redaction regexes were quadratic: one 20,000-character line such as `a.a.a.…` took about 19 s; now under 0.1 s in the same sandbox. Email, URL-credential, token and private-key patterns are bounded.
- Deeply nested JSON (a log line, a model reply or a `.json` array file) raised `RecursionError` and crashed parsing; it is now rejected cleanly.
- One failing incident analysis aborted the whole run; failures are now contained and listed (`run.errors`).
- An unexpected error inside the LLM layer could escape; the enhancer now never raises.
- A history-database failure after a successful analysis surfaced as a page error; it is now a warning.
- When the innermost stack frame's file is missing from the repository, the report now says so instead of silently showing a caller.

## Mutation smoke check
`python scripts\mutation_smoke.py` deliberately breaks 22 behaviours in a temporary copy (severity mapping, root-cause choice, verification logic, size limits, symlink handling, redaction, Jira confirmation, history redaction, …) and checks the tests fail.
The first 15 mutants (Phase 10): 12 were caught on the first run; the 3 survivors exposed weak tests that were strengthened. The 7 added in Phase 12 (ANSI stripping, Markdown escaping, redirect handling, path policy, group cap, Luhn check, project-root containment) were all caught on their first run. The full set was not re-run together after the last edits. This is a sample of hand-picked mutations, not a proof of completeness.

## Known gaps (not tested in the build environment)
- The Pydantic-dependent tests (`test_schemas.py`, validator parity) and the real-Streamlit `AppTest` run only where those packages are installed.
- No real Ollama model, real Jira instance or real OpenAI-compatible server was used; fake local HTTP servers stand in.
- No visual/layout review of the UI. No Windows-specific CI result is claimed (the workflow exists but was not run here).
- Speed and memory limits are not asserted as numbers (see Phase 11 for benchmarks).
