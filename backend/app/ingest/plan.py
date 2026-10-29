"""The Plan: what the AI decides about a file, in a form code can execute."""

import re
from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator

from ..knowledge_models import ENTITY_FIELDS
from .sniff import Sniffed


class Col(BaseModel):
    """Where a value comes from. `sources` are column names or JSON paths;
    the first one with a value wins. `split` breaks a multi-valued cell."""

    sources: list[str] = Field(min_length=1)
    split: str | None = None


class EntityOutput(BaseModel):
    kind: Literal["entity"]
    table: Literal["diseases", "symptoms", "drugs"]
    # enrich_only: add aliases/descriptions to rows that already exist, never
    # create new ones. For dictionaries far larger than the knowledge we hold.
    mode: Literal["upsert", "enrich_only"] = "upsert"
    name: Col
    aliases: Col | None = None
    fields: dict[str, Col] = {}

    @model_validator(mode="after")
    def _known_fields(self):
        unknown = set(self.fields) - set(ENTITY_FIELDS[self.table])
        if unknown:
            raise ValueError(
                f"{self.table} has no column(s) {sorted(unknown)}; "
                f"allowed: {list(ENTITY_FIELDS[self.table])}"
            )
        return self


class LinkOutput(BaseModel):
    """Disease -> symptom or disease -> drug. Missing names are created."""

    kind: Literal["link"]
    disease: Col
    symptom: Col | None = None
    drug: Col | None = None

    @model_validator(mode="after")
    def _one_target(self):
        if (self.symptom is None) == (self.drug is None):
            raise ValueError("a link output needs exactly one of `symptom` or `drug`")
        return self


class PrecautionOutput(BaseModel):
    kind: Literal["precaution"]
    disease: Col | None = None
    symptom: Col | None = None
    text: Col

    @model_validator(mode="after")
    def _has_subject(self):
        if self.disease is None and self.symptom is None:
            raise ValueError("a precaution output needs a `disease` or a `symptom`")
        return self


Output = Annotated[
    EntityOutput | LinkOutput | PrecautionOutput, Field(discriminator="kind")
]


class Plan(BaseModel):
    # records: rows/objects mapped by `outputs`.  article: free text about one
    # disease, handled by AI extraction.  none: nothing to ingest.
    content: Literal["records", "article", "none"]
    verdict: Literal["usable", "junk", "not_data"]
    # One line on what the file contains.
    summary: str = ""
    # Why the verdict, and anything a reviewer should know.
    reason: str = ""
    confidence: float = Field(ge=0, le=1)
    outputs: list[Output] = []
    # Filled in by the pipeline, not the model.
    model: str = ""

    @model_validator(mode="after")
    def _consistent(self):
        if self.verdict == "usable" and self.content == "records" and not self.outputs:
            raise ValueError("a usable records plan needs at least one output")
        if self.verdict != "usable":
            self.outputs = []
        return self

    def cols(self) -> list[Col]:
        found: list[Col] = []
        for output in self.outputs:
            for value in output.__dict__.values():
                if isinstance(value, Col):
                    found.append(value)
                elif isinstance(value, dict):
                    found += [v for v in value.values() if isinstance(v, Col)]
        return found

    def check_against(self, sniffed: Sniffed) -> list[str]:
        """Problems that make the plan unexecutable on this file."""
        if self.verdict != "usable" or self.content != "records":
            return []
        known = set(sniffed.columns)
        problems = []
        for col in self.cols():
            for source in col.sources:
                # "Concept[0].X" (the first one only) is as valid as the
                # listed "Concept[].X" or "Concept.X".
                general = re.sub(r"\[\d+\]", "[]", source)
                if source not in known and general not in known and general.replace("[]", "") not in {
                    k.replace("[]", "") for k in known
                }:
                    problems.append(
                        f"source {source!r} is not one of the available fields"
                    )
        return sorted(set(problems))
