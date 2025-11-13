"""Voice processing components: STT and TTS."""

from .deepgram_client import deepgram_manager, DeepgramSTTClient, DeepgramSTTManager
from .deepgram_tts_client import deepgram_tts_manager, DeepgramTTSClient, DeepgramTTSManager
from .tts_client import tts_manager, GoogleTTSClient, GoogleTTSManager

__all__ = [
    "deepgram_manager",
    "DeepgramSTTClient",
    "DeepgramSTTManager",
    "deepgram_tts_manager",
    "DeepgramTTSClient",
    "DeepgramTTSManager",
    "tts_manager",
    "GoogleTTSClient",
    "GoogleTTSManager"
]

