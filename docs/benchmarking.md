# Benchmarking (Phase 11)

Nothing in this repository claims a performance number. Run the benchmark on your machine and quote only what it writes.

## 1. Performance on large logs
```powershell
python scripts\benchmark.py              # 1, 5, 10 and 25 MB, 3 repeats each (a few minutes at most on a laptop)
python scripts\benchmark.py --quick      # 1 MB, 1 repeat: smoke test
python scripts\benchmark.py --sizes 1 5 --repeats 5
python scripts\benchmark.py --ai ollama  # also times the optional local LLM (needs Ollama running)
```
Output: `benchmarks\results\benchmark-<timestamp>.json` (full data) and `benchmarks\results\latest.md` (tables).

What is measured, per size (median of the repeats, min/max kept in the JSON):
- **Parse**, **Group**, **Index code** (scan + chunk + search index), **Retrieve code**, **Analyze** (root-cause reports) and **Total** wall time, taken from the pipeline's own timers.
- **Peak memory**: peak resident memory of a fresh worker process per size (Linux/macOS `ru_maxrss`; Windows `PeakWorkingSetSize` via ctypes, which was not tested by the author).
- **Correct**: the generator knows exactly how many events of each kind it wrote; a size only counts as correct if the groups found have exactly those sizes and no line was unparsed. A fast wrong answer is flagged.
- **AI analysis time** is measured only with `--ai ollama` and only if the model is reachable. Otherwise the report says "Not measured".

Log generation is not timed. The logs are synthetic (INFO traffic, warnings, chained tracebacks into the demo project, JSON gateway errors, noisy unique errors).
Results record the OS, CPU, RAM, Python and tool versions because the numbers mean nothing without them.

Scaling notes you can verify in your own results: parse time grew roughly linearly with log size and memory roughly linearly too, because all events of a run are held in memory.
The default 50 MB upload limit exists for that reason. Do not claim scalability beyond the largest size you actually ran.

## 2. Scenarios with known root causes
The same run also analyzes 4 synthetic scenarios (the demo plus 3 generated: a null reference, a socket timeout, a missing config file).
Each has a ground truth (exception, file, function, failing line) and the benchmark checks objectively whether the tool: found the group, named the correct raise site,
verified the code at that location, showed the failing line, picked the matching rule, and generated a Jira report.
Caveat: these scenarios were written together with the tool's rules, so passing proves the pipeline works as designed, not that it generalizes.

## 3. Manual baseline versus agent-assisted workflow (you do this part)
A resume claim such as "cut root-cause analysis from 30 minutes to 45 seconds" needs a measured baseline. The tool times you, and only counts correct answers.
```powershell
python scripts\manual_baseline.py prepare                                   # builds the scenario folders, prints the task cards
python scripts\manual_baseline.py run --participant YourName --mode manual    # you investigate with an editor/search, no analyzer
python scripts\manual_baseline.py run --participant YourName --mode assisted  # the agent runs; you verify its report and decide it is ready to file
python scripts\manual_baseline.py status
python scripts\compare_workflows.py
```
Protocol (keeps the comparison honest):
1. Do one practice trial first and delete its line from `benchmarks\results\workflow-times.jsonl`.
2. Manual: use only an editor and search tools; finish when your bug report draft covers the listed items. Assisted: the clock covers only YOUR review time after the report exists; machine time is added.
3. After each trial you type the exception, file and line you found. A trial whose answers do not match the ground truth is recorded as invalid and excluded from the medians.
4. Scenario order is shuffled. Do the manual round on a different day from the assisted round if you can, otherwise you will remember the answers (this still biases the result: say so).
5. Collect at least 3 valid trials per mode on at least 2 common scenarios before using the number.

Limits you should state if asked: a single participant, synthetic scenarios, the participant is the tool's author (who knows the answers), and the human review time is self-timed.

## 4. Resume bullets
`python scripts\compare_workflows.py` prints three bullets and fills them only from your result files:
- **A** (size, error groups, seconds): from the largest benchmark size whose output was verified. "AI-powered" and "LLM-assisted" appear only if an `--ai ollama` run refined at least one report.
- **B** (scenarios): the number of scenarios that passed every ground-truth check and generated a report. "local LLM inference" only if the AI run happened.
- **C** (manual versus assisted): only with enough valid trials on enough common scenarios; otherwise it prints exactly what is missing.

The numbers in a bullet come from the machine that ran the benchmark: run it on the computer you will describe.

## Adding results to your README
Copy the tables from `benchmarks\results\latest.md` into the README together with the "Measured on" line, and commit the JSON.
Results are not committed by default (the folder is empty in this release on purpose).
