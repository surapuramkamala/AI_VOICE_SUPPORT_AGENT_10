
# import os
# import tempfile
# from functools import lru_cache
# from pathlib import Path
# import logging
# import edge_tts
# from fastapi import (
#     APIRouter,
#     Depends,
#     File,
#     Form,
#     Header,
#     HTTPException,
#     UploadFile,
# )
# from fastapi.responses import StreamingResponse
# from pydantic import BaseModel, Field
# from sqlalchemy.orm import Session

# from app.database import get_db
# from app.agent.nvidia_agent import chat_with_agent
# logger = logging.getLogger(__name__)


# router = APIRouter(prefix="/voice", tags=["Voice Support"])

# MAX_AUDIO_BYTES = 15 * 1024 * 1024
# MAX_TRANSCRIPT_LENGTH = 8000

# ALLOWED_AUDIO_EXTENSIONS = {
#     ".wav",
#     ".mp3",
#     ".m4a",
#     ".webm",
#     ".ogg",
#     ".mp4",
#     ".mpeg",
#     ".mpga",
#     ".flac",
# }

# ALLOWED_TTS_VOICES = {
#     "en-IN-NeerjaNeural",
#     "en-IN-PrabhatNeural",
#     "en-US-AriaNeural",
# }


# class SpeakRequest(BaseModel):
#     text: str = Field(min_length=1, max_length=4000)
#     voice: str = "en-IN-NeerjaNeural"


# @lru_cache(maxsize=1)
# def get_whisper_model():
#     """Load the local speech recognition model once per process."""

#     from faster_whisper import WhisperModel

#     model_name = os.getenv("WHISPER_MODEL", "small")

#     return WhisperModel(
#         model_name,
#         device=os.getenv("WHISPER_DEVICE", "cpu"),
#         compute_type=os.getenv("WHISPER_COMPUTE_TYPE", "int8"),
#     )


# def transcribe_audio_file(
#     audio_path: str,
#     language: str | None = None,
# ) -> dict:
#     """Transcribe an audio file using local Whisper inference."""

#     model = get_whisper_model()
#     print("model: ", model)
#     segments, info = model.transcribe(
#         audio_path,
#         language=language or None,
#         vad_filter=True,
#     )
#     print("segments: ", segments)
#     transcript = " ".join(
#         segment.text.strip()
#         for segment in segments
#         if segment.text.strip()
#     ).strip()

#     if not transcript:
#         raise HTTPException(
#             status_code=422,
#             detail="No speech could be recognized in the audio.",
#         )

#     if len(transcript) > MAX_TRANSCRIPT_LENGTH:
#         raise HTTPException(
#             status_code=422,
#             detail="The recognized transcript is too long.",
#         )

#     return {
#         "text": transcript,
#         "language": info.language,
#         "language_probability": round(
#             float(info.language_probability),
#             3,
#         ),
#     }


# def extract_assistant_text(result) -> str:
#     """Handle common response shapes from the existing agent."""

#     if isinstance(result, str):
#         response = result

#     elif isinstance(result, dict):
#         response = (
#             result.get("response")
#             or result.get("message")
#             or result.get("reply")
#             or result.get("answer")
#         )

#     else:
#         response = None

#     if not isinstance(response, str) or not response.strip():
#         raise HTTPException(
#             status_code=502,
#             detail=(
#                 "The agent returned an unexpected response. "
#                 "Check chat_with_agent()'s return structure."
#             ),
#         )

#     return response.strip()


# @router.post("/transcribe")
# def transcribe_audio(
#     audio: UploadFile = File(...),
#     language: str | None = Form(default=None),
# ):
#     """
#     Convert uploaded speech to text.

#     Supported formats depend on the audio decoder available to
#     faster-whisper. The upload size is limited to 15 MB.
#     """

#     suffix = Path(audio.filename or "").suffix.lower()

#     if suffix not in ALLOWED_AUDIO_EXTENSIONS:
#         raise HTTPException(
#             status_code=415,
#             detail="Unsupported audio file extension.",
#         )

#     temp_path = None

#     try:
#         content = audio.file.read(MAX_AUDIO_BYTES + 1)

#         if not content:
#             raise HTTPException(
#                 status_code=400,
#                 detail="The uploaded audio file is empty.",
#             )

#         if len(content) > MAX_AUDIO_BYTES:
#             raise HTTPException(
#                 status_code=413,
#                 detail="Audio file exceeds the 15 MB limit.",
#             )

#         with tempfile.NamedTemporaryFile(
#             suffix=suffix,
#             delete=False,
#         ) as temp_file:
#             temp_file.write(content)
#             temp_path = temp_file.name

#         try:
#             result = transcribe_audio_file(
#                 temp_path,
#                 language=language,
#             )
#         except HTTPException:
#             raise
#         except Exception as exc:
#             logger.exception("Whisper transcription failed")
#             raise HTTPException(
#                 status_code=500,
#                 detail=f"Speech recognition failed: {type(exc).__name__}: {exc}",
#             ) from exc

#         return {
#             "transcript": result["text"],
#             "language": result["language"],
#             "language_probability": result["language_probability"],
#         }

#     finally:
#         if temp_path and os.path.exists(temp_path):
#             os.remove(temp_path)

#         audio.file.close()


# @router.post("/chat")
# def voice_chat(
#     audio: UploadFile = File(...),
#     session_id: str = Form(..., min_length=1, max_length=128),
#     language: str | None = Form(default=None),
#     customer_id: int = Header(
#         ...,
#         alias="X-Demo-Customer-Id",
#         gt=0,
#     ),
#     db: Session = Depends(get_db),
# ):
#     """
#     Speech -> Whisper transcription -> existing AI agent.

#     Returns text for the client to display and send to /voice/speak.
#     """

#     session_id = session_id.strip()

#     if not session_id:
#         raise HTTPException(
#             status_code=422,
#             detail="A valid session ID is required.",
#         )

#     transcription = transcribe_audio(
#         audio=audio,
#         language=language,
#     )

#     message = transcription["transcript"]

#     # Call the existing agent; do not duplicate its refund logic here.
#     result = chat_with_agent(
#         message=message,
#         db=db,
#         customer_id=customer_id,
#         session_id=session_id,
#     )

#     assistant_text = extract_assistant_text(result)

#     return {
#         "session_id": session_id,
#         "transcript": message,
#         "response_text": assistant_text,
#         "speech_endpoint": "/voice/speak",
#     }


# @router.post("/speak")
# async def speak_text(payload: SpeakRequest):
#     """Convert an agent response to MP3 audio using Edge TTS."""

#     text = payload.text.strip()

#     if not text:
#         raise HTTPException(
#             status_code=422,
#             detail="Text to speak cannot be empty.",
#         )

#     if payload.voice not in ALLOWED_TTS_VOICES:
#         raise HTTPException(
#             status_code=422,
#             detail="The requested TTS voice is not allowed.",
#         )

#     async def audio_stream():
#         communicate = edge_tts.Communicate(
#             text=text,
#             voice=payload.voice,
#         )

#         async for chunk in communicate.stream():
#             if chunk["type"] == "audio":
#                 yield chunk["data"]

#     return StreamingResponse(
#         audio_stream(),
#         media_type="audio/mpeg",
#         headers={
#             "Content-Disposition": 'inline; filename="voice-response.mp3"',
#             "Cache-Control": "no-store",
#             "X-Content-Type-Options": "nosniff",
#         },
#     )
#---------------------------------------------------------

# import logging
# import os
# from functools import lru_cache
# from pathlib import Path

# import edge_tts
# from groq import Groq
# from fastapi import (
#     APIRouter,
#     Depends,
#     File,
#     Form,
#     Header,
#     HTTPException,
#     UploadFile,
# )
# from fastapi.responses import StreamingResponse
# from pydantic import BaseModel, Field
# from sqlalchemy.orm import Session

# from app.database import get_db
# from app.agent.nvidia_agent import chat_with_agent


# logger = logging.getLogger(__name__)

# router = APIRouter(prefix="/voice", tags=["Voice Support"])

# MAX_AUDIO_BYTES = 15 * 1024 * 1024
# MAX_TRANSCRIPT_LENGTH = 8000

# ALLOWED_AUDIO_EXTENSIONS = {
#     ".wav",
#     ".mp3",
#     ".m4a",
#     ".webm",
#     ".ogg",
#     ".mp4",
#     ".mpeg",
#     ".mpga",
#     ".flac",
# }

# ALLOWED_TTS_VOICES = {
#     "en-IN-NeerjaNeural",
#     "en-IN-PrabhatNeural",
#     "en-US-AriaNeural",
# }


# class SpeakRequest(BaseModel):
#     text: str = Field(min_length=1, max_length=4000)
#     voice: str = "en-IN-NeerjaNeural"


# @lru_cache(maxsize=1)
# def get_groq_client() -> Groq:
#     """Create and reuse the Groq API client."""

#     api_key = os.getenv("GROQ_API_KEY")

#     if not api_key:
#         raise HTTPException(
#             status_code=500,
#             detail="GROQ_API_KEY is not configured.",
#         )

#     return Groq(api_key=api_key)


# def transcribe_audio_content(
#     content: bytes,
#     filename: str,
#     language: str | None = None,
# ) -> dict:
#     """Transcribe uploaded audio using Groq-hosted Whisper."""

#     client = get_groq_client()
#     model_name = os.getenv(
#         "GROQ_WHISPER_MODEL",
#         "whisper-large-v3-turbo",
#     )

#     try:
#         request_args = {
#             "file": (filename, content),
#             "model": model_name,
#             "response_format": "verbose_json",
#         }

#         if language:
#             request_args["language"] = language.strip()

#         result = client.audio.transcriptions.create(**request_args)

#     except HTTPException:
#         raise

#     except Exception as exc:
#         logger.exception("Groq Whisper transcription failed")

#         # Do not expose API keys, request details, or raw provider errors.
#         raise HTTPException(
#             status_code=502,
#             detail="Speech recognition failed. Check the Groq API key, "
#                    "model availability, network connection, and audio format.",
#         ) from exc

#     transcript = (result.text or "").strip()
#     detected_language = getattr(result, "language", None)

#     if not transcript:
#         raise HTTPException(
#             status_code=422,
#             detail="No speech could be recognized in the audio.",
#         )

#     if len(transcript) > MAX_TRANSCRIPT_LENGTH:
#         raise HTTPException(
#             status_code=422,
#             detail="The recognized transcript is too long.",
#         )

#     return {
#         "text": transcript,
#         "language": detected_language or language,
#         # Groq's transcription response does not necessarily provide
#         # the language probability returned by local faster-whisper.
#         "language_probability": None,
#     }


# def extract_assistant_text(result) -> str:
#     """Handle common response shapes from the existing agent."""

#     if isinstance(result, str):
#         response = result

#     elif isinstance(result, dict):
#         response = (
#             result.get("response")
#             or result.get("message")
#             or result.get("reply")
#             or result.get("answer")
#         )

#     else:
#         response = None

#     if not isinstance(response, str) or not response.strip():
#         raise HTTPException(
#             status_code=502,
#             detail=(
#                 "The agent returned an unexpected response. "
#                 "Check chat_with_agent()'s return structure."
#             ),
#         )

#     return response.strip()


# def read_audio_upload(audio: UploadFile) -> tuple[bytes, str]:
#     """Validate and read an uploaded audio file."""

#     suffix = Path(audio.filename or "").suffix.lower()

#     if suffix not in ALLOWED_AUDIO_EXTENSIONS:
#         raise HTTPException(
#             status_code=415,
#             detail="Unsupported audio file extension.",
#         )

#     content = audio.file.read(MAX_AUDIO_BYTES + 1)

#     if not content:
#         raise HTTPException(
#             status_code=400,
#             detail="The uploaded audio file is empty.",
#         )

#     if len(content) > MAX_AUDIO_BYTES:
#         raise HTTPException(
#             status_code=413,
#             detail="Audio file exceeds the 15 MB limit.",
#         )

#     filename = audio.filename or f"audio{suffix}"

#     return content, filename


# @router.post("/transcribe")
# def transcribe_audio(
#     audio: UploadFile = File(...),
#     language: str | None = Form(default=None),
# ):
#     """
#     Convert uploaded speech to text using Groq Whisper.

#     Audio is sent to Groq for transcription.
#     """

#     try:
#         content, filename = read_audio_upload(audio)

#         result = transcribe_audio_content(
#             content=content,
#             filename=filename,
#             language=language,
#         )

#         return {
#             "transcript": result["text"],
#             "language": result["language"],
#             "language_probability": result["language_probability"],
#         }

#     finally:
#         audio.file.close()


# @router.post("/chat")
# def voice_chat(
#     audio: UploadFile = File(...),
#     session_id: str = Form(..., min_length=1, max_length=128),
#     language: str | None = Form(default=None),
#     customer_id: int = Header(
#         ...,
#         alias="X-Demo-Customer-Id",
#         gt=0,
#     ),
#     db: Session = Depends(get_db),
# ):
#     """
#     Audio -> Groq Whisper -> existing AI agent.

#     Returns text for the client to display and send to /voice/speak.
#     """

#     session_id = session_id.strip()

#     if not session_id:
#         raise HTTPException(
#             status_code=422,
#             detail="A valid session ID is required.",
#         )

#     try:
#         content, filename = read_audio_upload(audio)

#         transcription = transcribe_audio_content(
#             content=content,
#             filename=filename,
#             language=language,
#         )

#     finally:
#         audio.file.close()

#     message = transcription["text"]

#     # Keep existing agent, database, and refund-safety logic unchanged.
#     result = chat_with_agent(
#         message=message,
#         db=db,
#         customer_id=customer_id,
#         session_id=session_id,
#     )

#     assistant_text = extract_assistant_text(result)

#     return {
#         "session_id": session_id,
#         "transcript": message,
#         "response_text": assistant_text,
#         "speech_endpoint": "/voice/speak",
#     }


# @router.post("/speak")
# async def speak_text(payload: SpeakRequest):
#     """Convert an agent response to MP3 using Edge TTS."""

#     text = payload.text.strip()

#     if not text:
#         raise HTTPException(
#             status_code=422,
#             detail="Text to speak cannot be empty.",
#         )

#     if payload.voice not in ALLOWED_TTS_VOICES:
#         raise HTTPException(
#             status_code=422,
#             detail="The requested TTS voice is not allowed.",
#         )

#     async def audio_stream():
#         try:
#             communicate = edge_tts.Communicate(
#                 text=text,
#                 voice=payload.voice,
#             )

#             async for chunk in communicate.stream():
#                 if chunk["type"] == "audio":
#                     yield chunk["data"]

#         except Exception:
#             logger.exception("Edge TTS generation failed")
#             raise

#     return StreamingResponse(
#         audio_stream(),
#         media_type="audio/mpeg",
#         headers={
#             "Content-Disposition": 'inline; filename="voice-response.mp3"',
#             "Cache-Control": "no-store",
#             "X-Content-Type-Options": "nosniff",
#         },
#     )
#-----------------------------------------

# import base64
# import logging
# import os
# from functools import lru_cache
# from pathlib import Path

# import edge_tts
# from groq import Groq
# from fastapi import (
#     APIRouter,
#     Depends,
#     File,
#     Form,
#     Header,
#     HTTPException,
#     UploadFile,
# )
# from fastapi.concurrency import run_in_threadpool
# from fastapi.responses import StreamingResponse
# from pydantic import BaseModel, Field
# from sqlalchemy.orm import Session

# from app.database import get_db
# from app.agent.nvidia_agent import chat_with_agent

# logger = logging.getLogger(__name__)

# router = APIRouter(prefix="/voice", tags=["Voice"])

# MAX_AUDIO_BYTES = 15 * 1024 * 1024
# MAX_TRANSCRIPT_LENGTH = 8000

# ALLOWED_AUDIO_EXTENSIONS = {
#     ".wav",
#     ".mp3",
#     ".m4a",
#     ".webm",
#     ".ogg",
#     ".mp4",
#     ".mpeg",
#     ".mpga",
#     ".flac",
# }

# ALLOWED_TTS_VOICES = {
#     "en-IN-NeerjaNeural",
#     "en-IN-PrabhatNeural",
#     "en-US-AriaNeural",
# }


# class SpeakRequest(BaseModel):
#     text: str = Field(..., min_length=1, max_length=4000)
#     voice: str = Field(default="en-IN-NeerjaNeural")


# @lru_cache(maxsize=1)
# def get_groq_client() -> Groq:
#     api_key = os.getenv("GROQ_API_KEY")

#     if not api_key:
#         raise HTTPException(
#             status_code=500,
#             detail="GROQ_API_KEY is not configured.",
#         )

#     return Groq(api_key=api_key)


# def validate_audio_filename(filename: str | None) -> str:
#     safe_filename = Path(filename or "audio.wav").name
#     extension = Path(safe_filename).suffix.lower()

#     if extension not in ALLOWED_AUDIO_EXTENSIONS:
#         raise HTTPException(
#             status_code=415,
#             detail="Unsupported audio format.",
#         )

#     return safe_filename


# async def read_audio_upload(
#     audio: UploadFile,
# ) -> tuple[bytes, str]:
#     filename = validate_audio_filename(audio.filename)

#     content = await audio.read(MAX_AUDIO_BYTES + 1)

#     if not content:
#         raise HTTPException(
#             status_code=400,
#             detail="The uploaded audio file is empty.",
#         )

#     if len(content) > MAX_AUDIO_BYTES:
#         raise HTTPException(
#             status_code=413,
#             detail="Audio file exceeds the 15 MB limit.",
#         )

#     return content, filename


# def transcribe_audio_content(
#     content: bytes,
#     filename: str,
#     language: str | None = None,
# ) -> dict:
#     options = {
#         "file": (filename, content),
#         "model": os.getenv(
#             "GROQ_WHISPER_MODEL",
#             "whisper-large-v3-turbo",
#         ),
#         "response_format": "verbose_json",
#     }

#     if language:
#         options["language"] = language

#     try:
#         result = get_groq_client().audio.transcriptions.create(
#             **options
#         )
#     except HTTPException:
#         raise
#     except Exception as exc:
#         logger.exception("Groq Whisper transcription failed")

#         raise HTTPException(
#             status_code=502,
#             detail="Speech transcription failed. Please try again.",
#         ) from exc

#     transcript = (getattr(result, "text", None) or "").strip()

#     if not transcript:
#         raise HTTPException(
#             status_code=422,
#             detail="No speech could be detected in the audio.",
#         )

#     if len(transcript) > MAX_TRANSCRIPT_LENGTH:
#         raise HTTPException(
#             status_code=413,
#             detail="Transcript exceeds the 8000-character limit.",
#         )

#     return {
#         "text": transcript,
#         "language": getattr(result, "language", None) or language,
#         "language_probability": None,
#     }


# def extract_assistant_text(result) -> str:
#     if isinstance(result, str):
#         return result.strip()

#     if isinstance(result, dict):
#         for key in ("response", "message", "reply", "answer"):
#             value = result.get(key)

#             if isinstance(value, str) and value.strip():
#                 return value.strip()

#     return str(result).strip()


# async def generate_speech_bytes(
#     text: str,
#     voice: str,
# ) -> bytes:
#     if voice not in ALLOWED_TTS_VOICES:
#         raise HTTPException(
#             status_code=422,
#             detail=(
#                 "Unsupported voice. Allowed voices: "
#                 + ", ".join(sorted(ALLOWED_TTS_VOICES))
#             ),
#         )

#     try:
#         communicator = edge_tts.Communicate(
#             text=text,
#             voice=voice,
#         )

#         chunks = []

#         async for chunk in communicator.stream():
#             if chunk.get("type") == "audio":
#                 chunks.append(chunk["data"])

#         audio_bytes = b"".join(chunks)

#         if not audio_bytes:
#             raise RuntimeError("Edge TTS returned no audio.")

#         return audio_bytes

#     except HTTPException:
#         raise
#     except Exception as exc:
#         logger.exception("Edge TTS synthesis failed")

#         raise HTTPException(
#             status_code=502,
#             detail="Text-to-speech generation failed.",
#         ) from exc


# @router.post("/transcribe")
# async def transcribe_audio(
#     audio: UploadFile = File(...),
#     language: str | None = Form(default=None),
# ):
#     content, filename = await read_audio_upload(audio)

#     return await run_in_threadpool(
#         transcribe_audio_content,
#         content,
#         filename,
#         language,
#     )


# @router.post("/chat")
# async def voice_chat(
#     audio: UploadFile = File(...),
#     session_id: str = Form(..., min_length=1, max_length=100),
#     language: str | None = Form(default=None),
#     customer_id: int = Header(
#         ...,
#         alias="X-Demo-Customer-Id",
#         gt=0,
#     ),
#     db: Session = Depends(get_db),
# ):
#     content, filename = await read_audio_upload(audio)

#     transcription = await run_in_threadpool(
#         transcribe_audio_content,
#         content,
#         filename,
#         language,
#     )

#     answer = await run_in_threadpool(
#         chat_with_agent,
#         message=transcription["text"],
#         db=db,
#         customer_id=customer_id,
#         session_id=session_id,
#     )

#     return {
#         "session_id": session_id,
#         "transcript": transcription["text"],
#         "language": transcription["language"],
#         "response_text": extract_assistant_text(answer),
#         "speech_endpoint": "/voice/speak",
#     }


# @router.post("/speak")
# async def speak(request: SpeakRequest):
#     audio_bytes = await generate_speech_bytes(
#         request.text,
#         request.voice,
#     )

#     from fastapi.responses import Response

#     return Response(
#         content=audio_bytes,
#         media_type="audio/mpeg",
#         headers={
#             "Content-Disposition": 'inline; filename="response.mp3"'
#         },
#     )


# @router.post("/assistant")
# async def voice_assistant(
#     audio: UploadFile = File(...),
#     session_id: str = Form(..., min_length=1, max_length=100),
#     language: str | None = Form(default=None),
#     voice: str = Form(default="en-IN-NeerjaNeural"),
#     customer_id: int = Header(
#         ...,
#         alias="X-Demo-Customer-Id",
#         gt=0,
#     ),
#     db: Session = Depends(get_db),
# ):
#     """
#     Complete voice flow:
#     audio -> Groq Whisper -> NVIDIA agent -> Edge TTS -> MP3.
#     """

#     content, filename = await read_audio_upload(audio)

#     # Step 1: Convert speech to text.
#     transcription = await run_in_threadpool(
#         transcribe_audio_content,
#         content,
#         filename,
#         language,
#     )

#     # Step 2: Process the transcript using the existing agent.
#     try:
#         agent_result = await run_in_threadpool(
#             chat_with_agent,
#             message=transcription["text"],
#             db=db,
#             customer_id=customer_id,
#             session_id=session_id,
#         )
#     except Exception as exc:
#         logger.exception("NVIDIA support agent failed")

#         raise HTTPException(
#             status_code=502,
#             detail="The support agent could not process the request.",
#         ) from exc

#     response_text = extract_assistant_text(agent_result)

#     if not response_text:
#         raise HTTPException(
#             status_code=502,
#             detail="The support agent returned an empty response.",
#         )

#     # Step 3: Convert the agent's response to speech.
#     audio_bytes = await generate_speech_bytes(
#         response_text,
#         voice,
#     )

#     # Step 4: Return the transcript, text answer, and playable MP3 data.
#     return {
#         "session_id": session_id,
#         "transcript": transcription["text"],
#         "language": transcription["language"],
#         "response_text": response_text,
#         "audio_content_type": "audio/mpeg",
#         "audio_base64": base64.b64encode(
#             audio_bytes
#         ).decode("ascii"),
#     }
#--------------------------------------------------------
import asyncio
import base64
import logging
import os
import re
from functools import lru_cache
from pathlib import Path

import edge_tts
from groq import Groq
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.auth import get_current_customer_id
from app.agent.nvidia_agent import chat_with_agent

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/voice", tags=["Voice"])

MAX_AUDIO_BYTES = 15 * 1024 * 1024
MAX_TRANSCRIPT_LENGTH = 8000
MAX_MESSAGE_LENGTH = 4000
MAX_TTS_TEXT_LENGTH = 4000
MAX_TTS_AUDIO_BYTES = 8 * 1024 * 1024
GROQ_TIMEOUT_SECONDS = 35.0
TTS_TIMEOUT_SECONDS = 30.0

ALLOWED_AUDIO_EXTENSIONS = {
    ".wav", ".mp3", ".m4a", ".webm", ".ogg",
    ".mp4", ".mpeg", ".mpga", ".flac",
}
ALLOWED_TTS_VOICES = {
    "en-IN-NeerjaNeural",
    "en-IN-PrabhatNeural",
    "en-US-AriaNeural",
}
# Keep this narrow: provider language codes should be short ISO-style tags.
LANGUAGE_CODE_RE = re.compile(r"^[a-z]{2,3}(?:-[A-Za-z]{2,8})?$")


@lru_cache(maxsize=1)
def get_groq_client() -> Groq:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        logger.error("GROQ_API_KEY is not configured")
        raise HTTPException(status_code=503, detail="Speech transcription is unavailable.")
    # The SDK timeout bounds network waits; one retry avoids unbounded request amplification.
    return Groq(api_key=api_key, timeout=GROQ_TIMEOUT_SECONDS, max_retries=1)


def _validate_audio_signature(content: bytes, extension: str) -> bool:
    """Best-effort signature check; extension and client MIME alone are not trusted."""
    if extension == ".wav":
        return len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WAVE"
    if extension == ".flac":
        return content.startswith(b"fLaC")
    if extension == ".ogg":
        return content.startswith(b"OggS")
    if extension in {".mp4", ".m4a", ".mp4"}:
        return len(content) >= 12 and content[4:8] == b"ftyp"
    if extension == ".webm":
        return content.startswith(b"\x1a\x45\xdf\xa3")
    if extension in {".mp3", ".mpeg", ".mpga"}:
        return content.startswith(b"ID3") or (
            len(content) >= 2 and content[0] == 0xFF and (content[1] & 0xE0) == 0xE0
        )
    # Some m4a/mp4 files use the same ftyp container; unknown container layouts fail closed.
    return False


async def read_audio_upload(audio: UploadFile) -> tuple[bytes, str]:
    try:
        filename = Path(audio.filename or "audio.wav").name
        extension = Path(filename).suffix.lower()
        if extension not in ALLOWED_AUDIO_EXTENSIONS:
            raise HTTPException(status_code=415, detail="Unsupported audio format.")

        content = await audio.read(MAX_AUDIO_BYTES + 1)
        if not content:
            raise HTTPException(status_code=400, detail="The uploaded audio file is empty.")
        if len(content) > MAX_AUDIO_BYTES:
            raise HTTPException(status_code=413, detail="Audio file exceeds the 15 MB limit.")
        if not _validate_audio_signature(content, extension):
            raise HTTPException(status_code=415, detail="The file content does not match a supported audio format.")
        return content, filename
    finally:
        await audio.close()


def _validate_language(language: str | None) -> str | None:
    if language is None or not language.strip():
        return None
    language = language.strip()
    if len(language) > 16 or not LANGUAGE_CODE_RE.fullmatch(language):
        raise HTTPException(status_code=422, detail="Invalid language code.")
    return language


def transcribe_audio_content(content: bytes, filename: str, language: str | None = None) -> dict:
    language = _validate_language(language)
    options = {
        "file": (filename, content),
        "model": os.getenv("GROQ_WHISPER_MODEL", "whisper-large-v3-turbo"),
        "response_format": "verbose_json",
    }
    if language:
        options["language"] = language
    try:
        result = get_groq_client().audio.transcriptions.create(**options)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Whisper transcription failed")
        raise HTTPException(status_code=502, detail="Speech transcription failed. Please try again.") from exc

    transcript = (getattr(result, "text", None) or "").strip()
    if not transcript:
        raise HTTPException(status_code=422, detail="No speech was detected.")
    if len(transcript) > MAX_TRANSCRIPT_LENGTH:
        raise HTTPException(status_code=413, detail="Transcript exceeds the configured length limit.")
    return {"text": transcript, "language": getattr(result, "language", None) or language}


async def _collect_speech(text: str, voice: str) -> bytes:
    communicator = edge_tts.Communicate(text=text, voice=voice)
    chunks: list[bytes] = []
    total_bytes = 0
    async for chunk in communicator.stream():
        if chunk.get("type") == "audio":
            data = chunk.get("data", b"")
            total_bytes += len(data)
            if total_bytes > MAX_TTS_AUDIO_BYTES:
                raise HTTPException(status_code=502, detail="Generated speech exceeded the response size limit.")
            chunks.append(data)
    audio_bytes = b"".join(chunks)
    if not audio_bytes:
        raise RuntimeError("Edge TTS returned no audio.")
    return audio_bytes


async def generate_speech_bytes(text: str, voice: str) -> bytes:
    if voice not in ALLOWED_TTS_VOICES:
        raise HTTPException(status_code=422, detail="Unsupported text-to-speech voice.")
    if not isinstance(text, str) or not text.strip():
        raise HTTPException(status_code=422, detail="Speech text cannot be empty.")
    if len(text) > MAX_TTS_TEXT_LENGTH:
        raise HTTPException(status_code=413, detail="Speech text exceeds the configured length limit.")
    try:
        return await asyncio.wait_for(_collect_speech(text, voice), timeout=TTS_TIMEOUT_SECONDS)
    except asyncio.TimeoutError as exc:
        logger.warning("Edge TTS timed out after %.1f seconds", TTS_TIMEOUT_SECONDS)
        raise HTTPException(status_code=504, detail="Speech generation timed out. Try again without voice output.") from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Edge TTS failed")
        raise HTTPException(status_code=502, detail="Speech generation failed. Try again without voice output.") from exc


def extract_assistant_text(result) -> str:
    if isinstance(result, str):
        response = result
    elif isinstance(result, dict):
        response = result.get("response") or result.get("message") or result.get("reply") or result.get("answer")
    else:
        response = None
    if not isinstance(response, str) or not response.strip():
        raise HTTPException(status_code=502, detail="The agent returned an unexpected response.")
    response = response.strip()
    if len(response) > MAX_TTS_TEXT_LENGTH:
        response = response[:MAX_TTS_TEXT_LENGTH]
    return response


@router.post("/assistant")
async def voice_assistant(
    audio: UploadFile | None = File(default=None),
    message: str | None = Form(default=None, max_length=MAX_MESSAGE_LENGTH),
    session_id: str = Form(..., min_length=1, max_length=100),
    enable_transcription: bool = Form(default=True),
    enable_speech: bool = Form(default=True),
    language: str | None = Form(default=None, max_length=16),
    voice: str = Form(default="en-IN-NeerjaNeural", max_length=64),
    customer_id: int = Depends(get_current_customer_id),
    db: Session = Depends(get_db),
):
    session_id = session_id.strip()
    if not session_id:
        raise HTTPException(status_code=422, detail="A valid session ID is required.")
    message = message.strip() if message else None
    if audio is None and not message:
        raise HTTPException(status_code=400, detail="Provide either a text message or an audio file.")
    if audio is not None and message:
        raise HTTPException(status_code=400, detail="Provide either text or audio, not both.")

    transcript = None
    detected_language = None
    if audio is not None:
        if not enable_transcription:
            raise HTTPException(status_code=400, detail="Audio input requires transcription to be enabled.")
        content, filename = await read_audio_upload(audio)
        transcription = await run_in_threadpool(transcribe_audio_content, content, filename, language)
        message = transcription["text"]
        transcript = message
        detected_language = transcription["language"]
    else:
        _validate_language(language)

    if not message:
        raise HTTPException(status_code=400, detail="No usable message was provided.")
    if len(message) > MAX_MESSAGE_LENGTH:
        raise HTTPException(status_code=413, detail="Message cannot exceed 4000 characters.")

    try:
        result = await run_in_threadpool(
            chat_with_agent,
            message=message,
            db=db,
            customer_id=customer_id,
            session_id=session_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Agent request failed")
        raise HTTPException(status_code=502, detail="The support assistant is temporarily unavailable.") from exc

    response_text = extract_assistant_text(result)
    #new code base addede 03-11-2026
    # audio_base64 = None
    # if enable_speech:
    #     speech_bytes = await generate_speech_bytes(response_text, voice)
    #     audio_base64 = base64.b64encode(speech_bytes).decode("ascii")
    audio_base64 = None
    tts_error = None
    if enable_speech:
        try:
            speech_bytes = await generate_speech_bytes(response_text, voice)
            audio_base64 = base64.b64encode(speech_bytes).decode("ascii")
        except HTTPException as exc:
            tts_error = exc.detail
            logger.warning("TTS failed, returning text only: %s", exc.detail)
    return JSONResponse(content={
        "session_id": session_id,
        "input_type": "audio" if transcript is not None else "text",
        "transcription_enabled": enable_transcription,
        "transcript": transcript,
        "language": detected_language,
        "response_text": response_text,
        "speech_enabled": enable_speech,
        "audio_content_type": "audio/mpeg" if enable_speech else None,
        "tts_error": tts_error,
        "audio_base64": audio_base64,
    })
