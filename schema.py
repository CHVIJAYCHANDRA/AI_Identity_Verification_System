from __future__ import annotations
import re
import unicodedata
from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, Field


# --------------------------------------------------------------- extraction
class DocumentFields(BaseModel):
    """What the vision model reads off the document. No judgement, only reading."""

    is_id_document: bool = Field(
        description="True only if this is a government or institutional identity "
        "document (passport, national ID, driving licence, residence permit)."
    )
    document_type: Optional[str] = Field(
        default=None, description="e.g. 'passport', 'driving licence', 'national ID'."
    )
    full_name: Optional[str] = Field(
        default=None,
        description="Name exactly as printed, including middle names and "
        "original spelling. Do not correct or reorder it.",
    )
    date_of_birth: Optional[str] = Field(
        default=None,
        description="Date of birth exactly as printed, preserving the document's "
        "format, e.g. '14/03/2001' or '14 MAR 2001'.",
    )
    dob_iso: Optional[str] = Field(
        default=None,
        description="The same date normalised to YYYY-MM-DD. Null if the printed "
        "date is ambiguous or unreadable.",
    )
    legibility: float = Field(
        ge=0.0, le=1.0,
        description="How clearly the name and date fields are readable. Below 0.5 "
        "if blurred, cropped, glared or partially covered.",
    )
    issues: list[str] = Field(
        default_factory=list,
        description="Observed problems: blur, glare, crop, obstruction, screen "
        "photo, visible editing. Empty if none.",
    )


EXTRACTION_SYSTEM_PROMPT = """You read fields from photographs of identity documents.

Transcribe only what is printed. Do not correct spelling, do not expand
abbreviations, do not reorder names, and do not infer missing characters. If a
character is unclear, treat the field as unreadable rather than guessing.

You are not deciding whether anything matches. Another system does that.

Set is_id_document to false for anything that is not a government or
institutional identity document.

Rate legibility honestly. Below 0.5 when blur, glare, cropping or obstruction
would make a careful human reader hesitate. Note every quality problem you see
in issues, including signs the image is a photo of a screen or has been edited.

Never invent a name or a date. Null is the correct answer when you cannot read
a field."""

EXTRACTION_USER_TEXT = (
    "Read the name and date of birth from this document. Transcribe exactly."
)


# --------------------------------------------------------------- comparison
def normalise_name(name: str) -> str:
    """Fold case, accents, punctuation and spacing - nothing else.

    Deliberately does NOT do fuzzy matching. Accent folding and punctuation are
    transcription artefacts; a different spelling is a different name.
    """
    if not name:
        return ""
    decomposed = unicodedata.normalize("NFKD", name)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    cleaned = re.sub(r"[^\w\s]", " ", stripped.lower())
    return " ".join(cleaned.split())


def name_tokens(name: str) -> set[str]:
    return set(normalise_name(name).split())


def compare_names(entered: str, on_document: str) -> tuple[str, str]:
    """Return (status, explanation).

    Three outcomes rather than two: an exact match and a middle-name difference
    are genuinely different situations, and collapsing them either rejects
    legitimate users or accepts wrong ones.
    """
    a, b = normalise_name(entered), normalise_name(on_document)
    if not b:
        return "unreadable", "Name could not be read from the document."
    if a == b:
        return "exact", "Entered name matches the document exactly."

    ta, tb = name_tokens(entered), name_tokens(on_document)
    if ta == tb:
        return "exact", "Same name components in a different order."
    if ta and tb and (ta <= tb or tb <= ta):
        extra = sorted((tb - ta) or (ta - tb))
        return "partial", f"All shared components match; differs by: {', '.join(extra)}."
    overlap = ta & tb
    if overlap:
        return "mismatch", (
            f"Only {len(overlap)} of {len(tb)} document name components match "
            f"({', '.join(sorted(overlap))})."
        )
    return "mismatch", "No name components in common."


def compare_dob(entered: date, dob_iso: Optional[str], printed: Optional[str]) -> tuple[str, str]:
    """Compare on the ISO form only.

    The user's date arrives as a date object; the document may print
    14/03/2001, 03/14/2001 or 14 MAR 2001. Parsing ambiguous formats in code
    guesses at day/month order, so the model normalises and this compares.
    """
    if not dob_iso:
        shown = f" (printed: {printed})" if printed else ""
        return "unreadable", f"Date of birth could not be normalised{shown}."
    if dob_iso == entered.isoformat():
        return "exact", f"Date of birth matches ({dob_iso})."
    return "mismatch", f"Entered {entered.isoformat()}, document shows {dob_iso}."


# ------------------------------------------------------------------ verdict
Verdict = Literal["match", "partial_match", "mismatch", "inconclusive"]


class VerificationResult(BaseModel):
    """The decision. Produced by code, not by the model."""

    verdict: Verdict
    name_status: str
    name_detail: str
    dob_status: str
    dob_detail: str
    fields: DocumentFields
    notes: list[str] = Field(default_factory=list)


def decide(
    entered_name: str,
    entered_dob: date,
    fields: DocumentFields,
    min_legibility: float,
) -> VerificationResult:
    """Deterministic rules, in priority order.

    Reading this function tells you exactly why any verdict was reached, which
    is not true of a paragraph of model prose.
    """
    notes: list[str] = list(fields.issues)

    if not fields.is_id_document:
        return VerificationResult(
            verdict="inconclusive",
            name_status="not_checked", name_detail="Not an identity document.",
            dob_status="not_checked", dob_detail="Not an identity document.",
            fields=fields,
            notes=notes + ["Upload does not appear to be an identity document."],
        )

    name_status, name_detail = compare_names(entered_name, fields.full_name or "")
    dob_status, dob_detail = compare_dob(entered_dob, fields.dob_iso, fields.date_of_birth)

    if fields.legibility < min_legibility:
        notes.append(
            f"Legibility {fields.legibility:.0%} is below the "
            f"{min_legibility:.0%} threshold; a clearer image is needed."
        )
        verdict: Verdict = "inconclusive"
    elif "unreadable" in (name_status, dob_status):
        verdict = "inconclusive"
    elif name_status == "mismatch" or dob_status == "mismatch":
        verdict = "mismatch"
    elif name_status == "partial":
        verdict = "partial_match"
        notes.append("Name differs by one or more components; manual review advised.")
    else:
        verdict = "match"

    return VerificationResult(
        verdict=verdict,
        name_status=name_status, name_detail=name_detail,
        dob_status=dob_status, dob_detail=dob_detail,
        fields=fields, notes=notes,
    )
  
