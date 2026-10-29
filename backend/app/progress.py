"""Live progress of a report being generated, for the kiosk's waiting screen.

Kept in memory: it describes work in flight and means nothing after a
restart. Everything recorded here is what the pipeline is actually doing;
the screen must not show more than this says.
"""

import time
from collections import OrderedDict

from .panel import SPECIALISTS

# understanding -> evidence -> panel -> chair -> precautions -> done
# "writing" replaces the panel stages when the report is written by one
# model (offline, or the panel unreachable); "failed" ends any of them.
STAGES = ("understanding", "evidence", "panel", "chair", "precautions", "writing", "done", "failed")


class ReportProgress:
    def __init__(self) -> None:
        self.stage = "understanding"
        self.asked: list[str] = []
        # specialist -> "took_part" | "stepped_aside" | "unavailable"
        self.answers: dict[str, str] = {}
        self.updated = time.monotonic()

    def at(self, stage: str) -> None:
        assert stage in STAGES, stage
        self.stage = stage
        self.updated = time.monotonic()

    def panel(self, asked: list[str]) -> None:
        self.asked = list(asked)
        self.at("panel")

    def answered(self, specialist: str, outcome: str) -> None:
        self.answers[specialist] = outcome
        self.updated = time.monotonic()

    def to_json(self) -> dict:
        return {
            "stage": self.stage,
            # Every case is screened against the whole roster first.
            "roster": list(SPECIALISTS),
            "specialists": [
                {"name": name, "state": self.answers.get(name, "thinking")}
                for name in self.asked
            ],
        }


class ProgressBoard:
    """The reports in flight, newest last; old entries fall off."""

    def __init__(self, keep: int = 200) -> None:
        self._items: OrderedDict[str, ReportProgress] = OrderedDict()
        self._keep = keep

    def start(self, session_id: str) -> ReportProgress:
        progress = self._items[session_id] = ReportProgress()
        self._items.move_to_end(session_id)
        while len(self._items) > self._keep:
            self._items.popitem(last=False)
        return progress

    def get(self, session_id: str) -> ReportProgress | None:
        return self._items.get(session_id)
