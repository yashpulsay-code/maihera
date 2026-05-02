"""
MAIHERA Voice Routes
Handles audio transcription via Whisper.
Whisper is optional — endpoint degrades gracefully if not installed.
"""

import logging
import tempfile
import os
from pathlib import Path
from fastapi import APIRouter, UploadFile, File

logger = logging.getLogger(__name__)

router = APIRouter(prefix='/voice', tags=['voice'])

# Try to load whisper once at import time
_whisper = None
try:
    import whisper as _whisper_module
    _whisper = _whisper_module
    logger.info("Whisper loaded successfully.")
except ImportError:
    logger.warning(
        "Whisper not installed — voice transcription disabled. "
        "Install with: pip install openai-whisper --no-cache-dir"
    )


@router.post('/transcribe')
async def transcribe_audio(file: UploadFile = File(...)):
    """
    Accepts audio upload, transcribes via Whisper base model.
    Returns { text: string }.
    Degrades gracefully if Whisper is not installed.
    """
    if _whisper is None:
        logger.warning("Transcription requested but Whisper not available.")
        return {'text': '', 'error': 'whisper_not_installed'}

    suffix = Path(file.filename or 'audio.webm').suffix or '.webm'
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    try:
        model = _whisper.load_model('base')
        result = model.transcribe(tmp_path)
        text = result.get('text', '').strip()
        logger.info('Transcribed: %.60s', text)
        return {'text': text}

    except Exception as e:
        logger.error('Transcription failed: %s', e)
        return {'text': '', 'error': 'transcription_failed'}

    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


@router.get('/status')
async def voice_status():
    """Check if voice transcription is available."""
    return {
        'whisper_available': _whisper is not None,
        'message': (
            'Transcription ready.'
            if _whisper is not None
            else 'Whisper not installed. Voice input disabled.'
        )
    }