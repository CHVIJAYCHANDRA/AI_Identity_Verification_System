from __future__ import annotations

import base64
import os
from datetime import date

import streamlit as st
from dotenv import load_dotenv
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from schema import (
    EXTRACTION_SYSTEM_PROMPT,
    EXTRACTION_USER_TEXT,
    DocumentFields,
    decide,
)

load_dotenv()

MAX_UPLOAD_MB = float(os.getenv("MAX_UPLOAD_MB", "8"))
MIN_LEGIBILITY = float(os.getenv("MIN_EXTRACTION_CONFIDENCE", "0.6"))

VERDICT_DISPLAY = {
    "match": ("Match", "success"),
    "partial_match": ("Partial match - manual review advised", "warning"),
    "mismatch": ("Mismatch", "error"),
    "inconclusive": ("Inconclusive - cannot verify", "warning"),
}


def encode_image(uploaded_file) -> tuple[str, str, float]:
    """Return (base64, mime, size_mb). Seeks to 0 so the file can be previewed
    too - Streamlit hands back a stream and a consumed one reads empty."""
    uploaded_file.seek(0)
    data = uploaded_file.read()
    uploaded_file.seek(0)
    mime = uploaded_file.type or "image/jpeg"
    return base64.b64encode(data).decode(), mime, len(data) / (1024 * 1024)


@st.cache_resource(show_spinner=False)
def get_extraction_chain(model: str, api_key: str):
    """Vision model constrained to DocumentFields.

    with_structured_output means the result is validated fields rather than
    prose that has to be parsed or trusted.
    """
    llm = ChatOpenAI(model=model, api_key=api_key, temperature=0)
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", EXTRACTION_SYSTEM_PROMPT),
            (
                "human",
                [
                    {"type": "text", "text": EXTRACTION_USER_TEXT},
                    {
                        "type": "image_url",
                        "image_url": {
                            # mime comes from the upload; the original code
                            # hardcoded jpeg while accepting png.
                            "url": "data:{mime};base64,{image}",
                            # "low" is a deliberate cost choice: a fixed ~85
                            # tokens rather than tiling the image. Printed name
                            # and date fields remain legible at this setting.
                            "detail": "low",
                        },
                    },
                ],
            ),
        ]
    )
    return prompt | llm.with_structured_output(DocumentFields)


st.set_page_config(page_title="ID Document Matcher", layout="wide")
st.title("ID Document Field Matcher")
st.caption(
    "Extracts the name and date of birth from an identity document and compares "
    "them with entered details. One step of a KYC pipeline, not a KYC system."
)

api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    st.error("OPENAI_API_KEY is not set. Copy `.env.example` to `.env` and add your key.")
    st.stop()

with st.expander("How your document is handled", expanded=False):
    st.markdown(
        f"""
- The image is held **in memory only** for the duration of the request. It is
  not written to disk, logged, or stored.
- It is **transmitted to the OpenAI API** for text extraction. Do not upload a
  document you are not willing to send to a third-party provider.
- Uploads are limited to **{MAX_UPLOAD_MB:.0f} MB**.
- Extracted fields are displayed to you and discarded when the session ends.
- This is a demonstration project. It is not certified for regulated identity
  verification, and it performs no liveness, tamper or security-feature checks.
"""
    )

with st.sidebar:
    st.header("Configuration")
    model = st.selectbox("Vision model", ["gpt-4o", "gpt-4o-mini"], index=0)
    min_legibility = st.slider(
        "Minimum legibility", 0.0, 1.0, MIN_LEGIBILITY, 0.05,
        help="Below this the result is inconclusive rather than a verdict.",
    )
    st.divider()
    st.caption("Image detail: low (~85 tokens)")
    st.caption("Comparison runs in code, not in the model")

left, right = st.columns([1, 1])

with left:
    uploaded_file = st.file_uploader(
        "Identity document", type=["jpg", "jpeg", "png", "webp"]
    )
    if uploaded_file:
        st.image(uploaded_file, caption=uploaded_file.name, use_container_width=True)

with right:
    entered_name = st.text_input("Full name", placeholder="As printed on the document")
    entered_dob = st.date_input(
        "Date of birth",
        value=None,
        min_value=date(1900, 1, 1),
        max_value=date.today(),
        format="YYYY-MM-DD",
        help="Document date formats vary; the model normalises before comparison.",
    )
    submitted = st.button("Verify", type="primary", use_container_width=True)
    st.caption(
        "Nothing is sent until you press Verify - the API is not called while "
        "you type."
    )

if submitted:
    if not uploaded_file:
        st.error("Upload a document.")
        st.stop()
    if not entered_name.strip():
        st.error("Enter the full name.")
        st.stop()
    if entered_dob is None:
        st.error("Enter the date of birth.")
        st.stop()

    image_b64, mime, size_mb = encode_image(uploaded_file)
    if size_mb > MAX_UPLOAD_MB:
        st.error(
            f"Image is {size_mb:.1f} MB, above the {MAX_UPLOAD_MB:.0f} MB limit. "
            "Compress it and retry."
        )
        st.stop()

    try:
        with st.spinner("Reading document..."):
            fields: DocumentFields = get_extraction_chain(model, api_key).invoke(
                {"image": image_b64, "mime": mime}
            )
    except Exception as e:
        st.error(f"Extraction failed: {e}")
        st.stop()

    result = decide(entered_name.strip(), entered_dob, fields, min_legibility)

    st.divider()
    label, level = VERDICT_DISPLAY[result.verdict]
    getattr(st, level)(f"**{label}**")

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Name**")
        st.caption(f"Entered: `{entered_name.strip()}`")
        st.caption(f"On document: `{fields.full_name or '—'}`")
        st.caption(f"{result.name_status}: {result.name_detail}")
    with c2:
        st.markdown("**Date of birth**")
        st.caption(f"Entered: `{entered_dob.isoformat()}`")
        st.caption(f"On document: `{fields.date_of_birth or '—'}`")
        st.caption(f"{result.dob_status}: {result.dob_detail}")

    m1, m2, m3 = st.columns(3)
    m1.metric("Document type", fields.document_type or "unknown")
    m2.metric("Legibility", f"{fields.legibility:.0%}")
    m3.metric("Identity document", "yes" if fields.is_id_document else "no")

    if result.notes:
        st.markdown("**Notes**")
        for note in result.notes:
            st.caption(f"- {note}")

    with st.expander("Extracted fields (raw)"):
        st.json(result.model_dump(exclude={"fields"}) | {"fields": fields.model_dump()})
    
