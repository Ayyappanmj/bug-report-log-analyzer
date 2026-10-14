"""The 60-second demo plan: one source of truth for docs\\demo.md, the rehearsal timer and the tests.
Text between ** ** must be a real label in the UI (a test checks this)."""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Segment:
    start: int
    end: int
    title: str
    action: str
    say: str

    @property
    def length(self) -> int:
        return self.end - self.start

    def labels(self) -> list[str]:
        return re.findall(r"\*\*([^*]+)\*\*", self.action)


SEGMENTS = [
    Segment(0, 5, "Open the dashboard", "The app is already open on the **Dashboard** (empty state). Keep the mouse still.",
            "This tool turns a messy log into evidence and a bug report."),
    Segment(5, 10, "Load the demo", "Click **Log Analyzer** in the sidebar, click **Load demo**, and open the preview.",
            "A synthetic production log: thousands of lines, errors buried in noise."),
    Segment(10, 20, "Analyze the log", "Click **Analyze**. The progress bar runs and the result counts appear. Then click **Investigate error groups →**.",
            "One click parses, groups the errors, finds the code and builds the analysis. All numbers are measured."),
    Segment(20, 30, "Show the detected incident", "On the Error Groups page G001 is selected: point at its severity, its count and the timeline.",
            "Thousands of events collapse into a few incidents. G001 is a burst of database timeouts."),
    Segment(30, 40, "Show the root cause", "Click **Open root-cause analysis →**, show **1 · Observed evidence**, then click **2 · Hypothesis**.",
            "Measured evidence stays separate from the hypothesis, which is labeled as not confirmed."),
    Segment(40, 50, "Show the source code", "Click **View code →**. The verified snippet is already open; point at the verified badge.",
            "The real file and line, verified against the stack trace."),
    Segment(50, 60, "Generate the Jira report", "Click **Bug Report** in the sidebar, tick **I have reviewed this report**, show **Copy for Jira**, click **⬇ Markdown**.",
            "A Jira-ready draft, reviewed by a human, ready to copy or download."),
]
TOTAL_SECONDS = SEGMENTS[-1].end


def plain(text: str) -> str:
    return text.replace("**", "")
