# AI Identity Verification System

This project is an AI-powered Know Your Customer (KYC) verification application built with Python, Streamlit, and OpenAI's GPT-4o Vision model.

## What it does

In many FinTech and banking applications, verifying a user's identity document against their inputted details is a manual, time-consuming process. This tool automates that workflow.
1. The user inputs their Name and Date of Birth.
2. The user uploads an image of their identification document (ID card, passport, etc.).
3. The system securely encodes the image and sends it to a multimodal AI model.
4. The AI cross-references the uploaded ID with the provided text details and returns a verification analysis.

## Technology Stack

- **LangChain**: For prompt templates and model orchestration.
- **OpenAI (GPT-4o Vision)**: For extracting text and verifying information directly from the uploaded ID image.
- **Streamlit**: For providing a clean, interactive user interface.

## How to Run

1. **Install Requirements**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Environment Variables**:
   Export your OpenAI API Key:
   ```bash
   export OPENAI_API_KEY="sk-your-api-key"
   ```

3. **Start the Application**:
   ```bash
   streamlit run kyc_verification.py
   ```
