# AI Voice Support Agent

A voice-enabled customer support application built with **FastAPI**, **Whisper speech-to-text**, an **NVIDIA-hosted large language model**, and **Edge TTS**. It allows customers to ask support questions by voice or text, retrieve customer/order information through backend tools, and hear the agent's response as audio.

## Table of Contents

- [Features](#features)
- [Architecture](#architecture)
- [Technology Stack](#technology-stack)
- [Project Structure](#project-structure)
- [Requirements](#requirements)
- [Setup](#setup)
- [Environment Variables](#environment-variables)
- [Run the Application](#run-the-application)
- [Use the Voice UI](#use-the-voice-ui)
- [API Endpoints](#api-endpoints)
- [Voice Processing Flow](#voice-processing-flow)
- [Safety Notes](#safety-notes)
- [Troubleshooting](#troubleshooting)
- [Future Improvements](#future-improvements)

## Features

- Accepts typed messages or recorded audio.
- Converts audio to text using Whisper through Groq.
- Uses an NVIDIA-hosted LLM for conversational responses and tool selection.
- Looks up customer and order information through application tools.
- Supports a controlled refund workflow with explicit confirmation safeguards.
- Converts agent responses to speech using Edge TTS.
- Supports streaming text/audio responses when the streaming endpoint and frontend are enabled.
- Allows a user to interrupt playback/request processing and submit a new query when the frontend's interrupt control is enabled.
- Uses a FastAPI backend and browser-based frontend.

## Architecture

```text
Customer microphone or text
          |
          v
      FastAPI API
          |
          +---- Audio input ----> Groq Whisper
          |                           |
          |                      Transcript text
          |                           |
          +---------------------------+
                                      |
                                      v
                           NVIDIA-hosted LLM
                                      |
                           Tool selection/calls
                                      |
                    +-----------------+------------------+
                    |                 |                  |
                    v                 v                  v
             Customer lookup     Order lookup     Refund preparation
                    |                 |                  |
                    +-----------------+------------------+
                                      |
                              Agent response text
                                      |
                         +------------+------------+
                         |                         |
                         v                         v
                    Stream text             Edge TTS audio
                         |                         |
                         +------------+------------+
                                      |
                                      v
                                Browser UI
```

The LLM proposes tool calls, but the Python backend executes the allowed tools and enforces application-level checks. Refund confirmation should remain controlled by deterministic backend logic rather than relying only on model instructions.

## Technology Stack

| Component | Technology | Responsibility |
|---|---|---|
| API server | FastAPI, Uvicorn | HTTP endpoints and request handling |
| Speech-to-text | `whisper-large-v3-turbo` via Groq | Converts uploaded audio into a transcript |
| Language model | `openai/gpt-oss-20b` via NVIDIA API (configured default) | Understands requests, generates responses, and selects tools |
| Text-to-speech | `edge-tts` | Converts response text into audio |
| Database layer | SQLAlchemy and the project's configured database | Reads customer/order data and stores relevant conversation/refund records |
| Frontend | HTML, CSS, JavaScript | Captures audio, submits requests, displays responses, and plays audio |

The configured model names can be changed through environment variables where supported. The exact available models depend on the provider account and API access.

## Project Structure

The current project layout is:

```text
AI_Voice_Support_Agent_9/
├── main.py
├── .env.example  # copy to .env locally
├── requirements.txt
├── static/
│   ├── index.html
│   └── app.js
└── app/
    ├── voice_api.py
    ├── database.py
    ├── models.py
    ├── schemas.py
    ├── seed.py
    ├── agent/
    │   └── nvidia_agent.py
    └── services/
        ├── support_service.py
        └── support_tools.py
```

Keep the `static/` directory beside `main.py`; the application mounts it relative to the project root.

## Requirements

- Python 3.10 or newer (use the version supported by your installed dependencies).
- A Groq API key for Whisper transcription.
- An NVIDIA API key with access to the configured chat model.
- A working database configuration and any required seeded customer/order records.
- A modern browser with microphone support for recording audio.
- Internet access for provider APIs and Edge TTS.

## Setup

### 1. Open the project directory

In a terminal, change to the folder containing `main.py`:

```bash
cd path/to/AI_Voice_Support_Agent_9
```

### 2. Create and activate a virtual environment

**Windows (Command Prompt):**

```bat
python -m venv .venv
.venv\Scripts\activate
```

**Windows (PowerShell):**

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

**macOS/Linux:**

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install dependencies

If the project includes `requirements.txt`:

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

If it does not, install the packages listed in your source imports and project dependency file. The components discussed in this project include:

```bash
pip install fastapi "uvicorn[standard]" python-multipart sqlalchemy \
  openai groq edge-tts python-dotenv
```

Use your project's existing dependency versions where possible. Do not install packages blindly into a different Python environment from the one used to run the server.

### 4. Configure environment variables

Create a `.env` file beside `main.py` if your application loads environment variables from that location. Add the variables required by your code:

```dotenv
GROQ_API_KEY=your_groq_api_key
NVIDIA_API_KEY=your_nvidia_api_key
NVIDIA_BASE_URL=https://integrate.api.nvidia.com/v1
NVIDIA_MODEL=openai/gpt-oss-20b
```

Replace the placeholders with your own credentials. Do not commit `.env` to source control or paste API keys into issues or screenshots. Check your code for any additional database or application-specific environment variables.

## Run the Application

From the project root—the directory containing `main.py`—start the API:

```bash
uvicorn main:app --reload
```

Common local URLs:

- API root, if implemented: `http://127.0.0.1:8000/`
- Interactive API documentation: `http://127.0.0.1:8000/docs`
- Voice UI, if the `/voice-ui` route is configured: `http://127.0.0.1:8000/voice-ui`

Keep the terminal running while using the app.

### Static frontend setup

Recommended structure:

```text
AI_Voice_Support_Agent_9/
├── main.py
└── static/
    ├── index.html
    └── app.js
```

In `main.py`, configure static files using an absolute path:

```python
from pathlib import Path
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

@app.get("/voice-ui", include_in_schema=False)
def voice_ui():
    return FileResponse(STATIC_DIR / "index.html")
```

Add these lines only if the app does not already configure the same routes. Make sure `static/index.html` exists before starting the server.

You can also open `static/index.html` with VS Code Live Server. In that case, the frontend runs on a different origin from FastAPI; configure CORS in FastAPI to allow only the frontend origin you use. The microphone generally works on `localhost` or `127.0.0.1` in modern browsers.

## Use the Voice UI

1. Start the FastAPI server.
2. Open the configured voice UI in your browser.
3. Enter the customer ID expected by your application and a session ID.
4. Allow microphone access if recording audio.
5. Record a question, then stop recording to submit it; or type a message.
6. Review the transcript and agent response.
7. Enable speech output to hear the response through Edge TTS.
8. Use the interrupt control, if available, to stop the current request/audio and ask a new question.

Example questions:

- “Can you check my latest order?”
- “What is the status of my order?”
- “Am I eligible for a refund?”

Responses depend on the customer/order data present in the configured database. Use test data while developing.

## API Endpoints

The project code discussed includes these endpoints. Verify them in `/docs` because route availability depends on which routers are registered in `main.py`.

### `POST /voice/assistant`

Accepts multipart form data containing either audio or text, processes the request, and returns the response. Depending on the form settings, the response may include a transcript and Base64-encoded audio.

Typical fields:

| Field | Purpose |
|---|---|
| `audio` | Optional audio upload |
| `message` | Optional typed message |
| `session_id` | Conversation/session identifier |
| `enable_transcription` | Whether uploaded audio should be transcribed |
| `enable_speech` | Whether to generate spoken output |
| `language` | Optional transcription language |
| `voice` | Allowed Edge TTS voice |
| `X-Demo-Customer-Id` header | Customer identifier used by the backend |

Supply exactly one of `audio` or `message`. Audio input requires transcription to be enabled.

### `POST /voice/assistant/stream`

If the streaming implementation is installed, this endpoint streams events using Server-Sent Events (SSE). The frontend must parse the stream to update the transcript/answer and play any audio segments.

Potential event types in the implementation discussed:

- `transcript` — recognized text from the audio.
- `text` — response text chunks.
- `audio` — audio segments, often Base64-encoded.
- `complete` — response processing completed.
- `error` — an error occurred.

Use the exact event format implemented in your local `voice_api.py`; this endpoint is not available until the streaming route is added and registered.

## Voice Processing Flow

1. The browser records audio and sends it to FastAPI.
2. The backend validates the file type and size.
3. Groq runs `whisper-large-v3-turbo` to produce text.
4. The transcript is passed to the agent.
5. The NVIDIA-hosted LLM generates a response and may request approved backend tools.
6. The backend executes the allowed tools and returns their results to the agent.
7. The agent produces a final response.
8. If speech is enabled, Edge TTS converts response text into audio.
9. The browser displays the answer and plays the generated audio.

## Safety Notes

- Keep API keys in environment variables; never expose them in frontend JavaScript.
- Restrict customer access on the backend. Do not trust a customer ID supplied by a browser as proof of identity in a real deployment.
- Validate uploads, limit file size, and reject unsupported formats.
- Keep tool execution allowlisted and validate every tool argument.
- Refund preparation and confirmation should have server-side validation, ownership checks, idempotency/concurrency protection where applicable, and explicit confirmation.
- Avoid logging API keys, sensitive customer data, payment information, or full audio/transcripts unless there is a clear need and appropriate retention controls.
- Configure CORS for specific trusted origins instead of allowing every origin in production.
- Use HTTPS and authentication before exposing the application outside a local development environment.
- Test cancellation and interruption behavior. Aborting the browser request stops the client request, but backend/provider work may require explicit cancellation handling.

## Troubleshooting

### `RuntimeError: Directory '.../app/static' does not exist`

The configured static directory path does not match your project layout. If `static/` is beside `main.py`, use:

```python
STATIC_DIR = Path(__file__).resolve().parent / "static"
```

Create `static/index.html` and `static/app.js` if they are missing, or update the path to match where your frontend files actually are.

### `GROQ_API_KEY` or `NVIDIA_API_KEY` missing

- Check that `.env` is beside the file/path from which your application loads it.
- Verify the environment variable spelling.
- Restart the server after changing environment variables.
- Never put API keys in `index.html` or `app.js`.

### Browser CORS error

If the frontend is served by Live Server (often port `5500`) and the backend runs on port `8000`, they are different origins. Add FastAPI `CORSMiddleware` for the exact frontend origin and allow the methods/headers required by your requests.

### Microphone access is blocked

Use a modern browser and serve the UI through `localhost` or `127.0.0.1`. Check the browser's site permissions and ensure the page is using `getUserMedia`/`MediaRecorder` correctly.

### No audio response

- Confirm speech output is enabled.
- Check the selected voice is in the backend's allowed voice list.
- Check the browser console and server logs.
- Verify the frontend decodes Base64 audio correctly or correctly queues streamed audio segments.
- Confirm Edge TTS can reach its service.

### Streaming endpoint returns 404

The streaming endpoint may not have been added to `app/voice_api.py`, or the voice router may not be included in `main.py`. Check `http://127.0.0.1:8000/docs` and verify the route.

### Model/API errors

Check API credentials, provider access, configured model name, network access, usage limits, and the response details in the server logs. Do not return secret values in error messages.

## Future Improvements

- Automatic voice activity detection for hands-free barge-in.
- Better echo cancellation and noise handling.
- Authentication and verified customer identity.
- Automated tests for transcription, tool authorization, refund safety, streaming, and cancellation.
- Structured observability with redaction of sensitive fields.
- Evaluation of transcription accuracy and answer grounding.
- Deployment behind HTTPS with production logging and monitoring.

## License

Add the license appropriate for your project before distributing it.

## Authentication and API security (Step 2)

The API no longer accepts `X-Demo-Customer-Id`. Customer endpoints require a short-lived signed bearer token. The token's customer identity is resolved from the server-side account record; a caller cannot choose another customer by changing a header. Reviewer decisions use a separate `reviewer` role, and the reviewer identity is taken from the authenticated account rather than a request parameter.

### Configure the signing key

Copy `.env.example` to `.env`, then generate a random signing key:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Put the generated value in `JWT_SECRET_KEY`. Never commit `.env`, share it, or reuse a key from another environment. Access tokens expire after 30 minutes by default (`ACCESS_TOKEN_TTL_SECONDS`). Run behind HTTPS in production; `APP_ENV=production` enables HSTS.

### Create a login account

Initialize the sample database first if needed:

```bash
python -m app.seed
```

Create a customer account linked to an existing active customer record (the password is entered interactively, not passed on the command line):

```bash
python scripts_create_user.py --email maya@example.com --role customer --customer-id 1
```

Create a refund reviewer account separately:

```bash
python scripts_create_user.py --email reviewer@example.com --role reviewer
```

Choose a unique password with at least 12 characters. Do not create reviewer accounts for ordinary customers. Provision accounts only from a trusted administrator terminal.

### Sign in and call the API

`POST /auth/login` JSON body:

```json
{"email":"maya@example.com","password":"your-password"}
```

Use the returned `access_token` on protected requests:

```http
Authorization: Bearer <access_token>
```

The browser UI signs in through `/auth/login` and keeps the token in memory only; refreshing the page requires signing in again. The `/auth/me` endpoint shows the authenticated account's role and customer association.

Reviewer decisions are now sent to `POST /reviewer/refunds/{refund_id}/decision` with `{"decision":"approved","comment":"..."}` or `{"decision":"rejected","comment":"..."}`. Only reviewer accounts can call this endpoint. Approval records an approval decision; it does not execute a payment or refund.

### Security controls added

- PBKDF2-HMAC-SHA256 password hashing with a per-password random salt.
- HMAC-SHA256 signed bearer tokens with fixed algorithm, issuer, audience, issue time, and expiry validation.
- Server-side account lookup on each authenticated request, so disabled accounts stop working even if their token has not expired.
- Role-based authorization for customer actions and reviewer decisions.
- Generic login failure messages to avoid disclosing whether an email exists.
- Security response headers, including content-type sniffing and framing protections; HSTS is enabled when `APP_ENV=production`.
- Existing refund amount/eligibility/confirmation checks remain in the service layer.

### Current limitations before public production deployment

This step is not a complete security certification. Add a shared-store rate limiter at the gateway for login and expensive voice endpoints, audit logs for authentication and reviewer actions, secret management in the cloud, TLS termination, and refresh/revocation strategy before public launch. The current database is SQLite and the browser token is held in memory. Do not expose the app publicly until those deployment controls are configured.
