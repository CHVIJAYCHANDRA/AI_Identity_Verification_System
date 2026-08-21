# ID Document Field Matcher

Extracts the name and date of birth from a photograph of an identity document
and compares them with details the user entered.

**This is one step of a KYC pipeline, not a KYC system.** See
[What this is not](#what-this-is-not) before drawing conclusions about it.

---

## The design decision

The obvious implementation is to hand the model the document and the entered
details and ask "do these match?" That fails in a specific way: language models
normalise. `Jon Smith` and `John Smith` read as the same person to a language
model and as a mismatch to a verification system, and no amount of prompting
removes that tendency reliably.

So the responsibilities are split:

document image ──► [model: read the fields] ──► [code: compare] ──► verdict

- **The model extracts.** Transcribe the printed name and date exactly. Do not
  correct spelling, expand abbreviations, or reorder names. Rate legibility.
  Never guess a character.
- **Code decides.** Case folding, accent folding and punctuation stripping are
  transcription artefacts and are normalised. Beyond that, a different spelling
  is a different name. No fuzzy matching.

Perception belongs to the model. Rules belong in code, where they can be read,
reviewed and unit-tested without an API key.
python
schema.py - the entire matching rule, inspectable and deterministic

if a == b:                      return "exact"
if name_tokens(a) == name_tokens(b):  return "exact"      # reordered
if ta <= tb or tb <= ta:        return "partial"          # missing middle name

---

## Verdicts

Four, not two:

| Verdict | Meaning |
|---|---|
| `match` | Name and date both agree after artefact normalisation |
| `partial_match` | All shared name components agree but one side has extra — typically a missing middle name. Flagged for manual review, not auto-approved |
| `mismatch` | A name component or the date disagrees |
| `inconclusive` | Not an identity document, a field is unreadable, or legibility is below threshold |

`partial_match` exists because `John Smith` vs `John Michael Smith` is common and
genuinely ambiguous. Folding it into `match` accepts wrong people; folding it
into `mismatch` rejects legitimate ones. Real systems escalate; so does this.

`inconclusive` exists because a blurred document that happens to match is luck,
not verification.

---

## Date handling

The user's date arrives as a `date` object and renders as `2001-03-14`. Indian
PAN cards print `14/03/2001`. US licences print `03/14/2001`. Passports print
`14 MAR 2001`.

Parsing those in Python means guessing day/month order. So the **model**
normalises to ISO — it can see which country issued the document — and **code**
compares ISO to ISO. Ambiguous or unreadable dates return null, which becomes
`inconclusive` rather than a coin flip.

---

## Results

<fill in: run the 12 cases below and complete this table>

| Case type | Cases | Correct verdict | Notes |
|---|---|---|---|
| Exact match | 3 | <n> | |
| Name off by one character | 2 | <n> | |
| DOB off by one digit | 2 | <n> | |
| Different person | 2 | <n> | |
| Blurred / partial document | 2 | <n> | |
| Not an ID document | 1 | <n> | |

Extraction accuracy (fields read correctly): <fill in>
Observed failure mode: <fill in>

Build the cases from a template document image in any image editor — no real
documents required, and none should be used.

### Free test of the decision logic

The comparison layer needs no API key, which is the point of putting it in code:
bash
python -c "
from datetime import date
from schema import DocumentFields, decide
f = DocumentFields(is_id_document=True, document_type='passport',
                   full_name='John Smith', date_of_birth='14/03/2001',
                   dob_iso='2001-03-14', legibility=0.9)
for n in ['John Smith','JOHN SMITH','John Michael Smith','Jon Smith']:
    print(f'{n:22} -> {decide(n, date(2001,3,14), f, 0.6).verdict}')
"

John Smith             -> match
JOHN SMITH             -> match
John Michael Smith     -> partial_match
Jon Smith              -> mismatch

The last line is the behaviour this architecture exists to guarantee.

---

## What this is not

Identity verification is a regulated process. This project implements document
field extraction and text comparison — one component. Production KYC under
AML/CFT additionally requires:

| Requirement | Status here |
|---|---|
| Liveness detection / selfie-to-document biometric match | Not implemented |
| Document security features — MRZ checksum, hologram, microprint, UV | Not implemented |
| Tamper and deepfake detection, screen-photo detection | Model flags visible issues only; no forensic analysis |
| Sanctions, PEP and watchlist screening | Not implemented |
| Immutable audit trail with retention policy | Not implemented |
| Certified data handling under GDPR / DPDP | Not implemented |
| Issuing-authority or database validation | Not implemented |

The extraction step is the easy part of KYC. Treating it as the whole problem is
the mistake this section exists to avoid.

---

## Privacy

- The image is held **in memory only** for the request. Not written to disk, not
  logged, not stored.
- It is **transmitted to the OpenAI API** for extraction. Do not upload a
  document you are unwilling to send to a third-party provider.
- Extracted fields are shown to you and discarded with the session.
- Uploads capped at `MAX_UPLOAD_MB` (default 8 MB), checked before any API call.
- Use synthetic or template documents when testing.

---

## Setup
bash
git clone https://github.com/CHVIJAYCHANDRA/AI_Identity_Verification_System
cd AI_Identity_Verification_System
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env        # add your OPENAI_API_KEY
streamlit run kyc_verification.py

| Variable | Default | Purpose |
|---|---|---|
| `OPENAI_API_KEY` | — | required |
| `OPENAI_VISION_MODEL` | `gpt-4o` | extraction; needs image input |
| `MAX_UPLOAD_MB` | `8` | upload cap, enforced pre-API |
| `MIN_EXTRACTION_CONFIDENCE` | `0.6` | legibility floor for a verdict |

---

## Cost decisions

**`detail: "low"`** — a fixed ~85 tokens instead of tiling the image into
high-resolution patches. Printed name and date fields stay legible at this
setting, so high detail buys nothing here.

**Submit button.** Streamlit re-runs the script on every interaction. The
original version fired a vision call on each keystroke in the name field —
typing a full name cost roughly ten calls. Nothing is now sent until Verify is
pressed.

**Size check before the call.** An oversized image is rejected locally rather
than uploaded and billed.

**`temperature=0`.** A verdict that varies between identical runs is not a
verdict.

---

## Stack

OpenAI GPT-4o vision · LangChain prompt layer (`langchain-core`,
`langchain-openai`) · Pydantic · Streamlit

Only LangChain's prompt templating and model wrapper are used — no chains,
agents or vector stores, so the dependency list is five lines.

---

## Limitations

- Legibility is model self-reported and not calibrated against a labelled set.
- No forensic tamper detection. A well-made forgery that photographs cleanly
  will extract cleanly.
- Exact-match comparison rejects legitimate transliteration differences —
  `Muhammad` / `Mohammed`, or non-Latin scripts romanised differently. Correct
  for the strict case, wrong for a real onboarding flow, which would need a
  reviewed transliteration policy.
- Two fields only: name and date of birth. No address, document number or expiry.
- Single document per session; no cross-document consistency checks.
- Tested on synthetic documents only.

## Planned

- Labelled synthetic set with adversarial name and date perturbations
- Legibility calibration: does low legibility actually predict extraction error?
- Document number and expiry extraction, with MRZ checksum validation where present
- Transliteration policy for the exact-match limitation above

## License

MIT
