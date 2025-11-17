from google.cloud import texttospeech
from typing import Optional
import base64

from ..utils.config import settings
from ..utils.logger import logger

class GoogleTTSClient:
    def __init__(self):
        self.client = texttospeech.TextToSpeechClient()
        
        self.voice = texttospeech.VoiceSelectionParams(
            language_code="en-US",
            name="en-US-Neural2-D",
            ssml_gender=texttospeech.SsmlVoiceGender.FEMALE
        )
        
        self.audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.LINEAR16,
            sample_rate_hertz=16000,
            speaking_rate=1.0,
            pitch=0.0
        )
        
        logger.info("Initialized Google TTS client")
    
    def synthesize_speech(self, text: str, voice_name: Optional[str] = None) -> bytes:
        try:
            synthesis_input = texttospeech.SynthesisInput(text=text)
            voice = self.voice
            if voice_name:
                voice = texttospeech.VoiceSelectionParams(
                    language_code="en-US",
                    name=voice_name
                )
            
            response = self.client.synthesize_speech(
                input=synthesis_input,
                voice=voice,
                audio_config=self.audio_config
            )
            
            logger.debug(f"Synthesized speech")
            return response.audio_content
        
        except Exception as e:
            logger.error(f"Error synthesizing speech: {e}")
            raise
    
    def synthesize_speech_base64(self, text: str) -> str:
        audio_bytes = self.synthesize_speech(text)
        return base64.b64encode(audio_bytes).decode('utf-8')
    
    def set_voice(self, language_code: str = "en-US", voice_name: str = "en-US-Neural2-D", gender: str = "FEMALE"):
        gender_map = {
            "MALE": texttospeech.SsmlVoiceGender.MALE,
            "FEMALE": texttospeech.SsmlVoiceGender.FEMALE,
            "NEUTRAL": texttospeech.SsmlVoiceGender.NEUTRAL
        }
        
        self.voice = texttospeech.VoiceSelectionParams(
            language_code=language_code,
            name=voice_name,
            ssml_gender=gender_map.get(gender, texttospeech.SsmlVoiceGender.FEMALE)
        )
        
        logger.info(f"Changed voice to: {voice_model}")
    
    def set_speaking_rate(self, rate: float):
        rate = max(0.25, min(4.0, rate))
        self.audio_config.speaking_rate = rate
        logger.info(f"Set speaking rate: {rate}")
    
    def set_pitch(self, pitch: float):
        pitch = max(-20.0, min(20.0, pitch))
        self.audio_config.pitch = pitch
        logger.info(f"Set pitch: {pitch}")

class GoogleTTSManager:
    def __init__(self):
        self.client = GoogleTTSClient()
        self.cache = {}
        logger.info("Initialized Google TTS manager")
    
    def synthesize(self, text: str, use_cache: bool = True) -> bytes:
        if use_cache and text in self.cache:
            logger.debug("Using cached audio")
            return self.cache[text]
        
        audio = self.client.synthesize_speech(text)
        
        if use_cache and len(text) < 100:
            self.cache[text] = audio
        
        return audio
    
    def clear_cache(self):
        self.cache.clear()
        logger.info("Cleared TTS cache")

# Lazy initialization - only create when needed (allows Cloud Run to use default credentials)
_tts_manager = None

def get_tts_manager():
    global _tts_manager
    if _tts_manager is None:
        try:
            _tts_manager = GoogleTTSManager()
            logger.info("Initialized Google TTS manager")
        except Exception as e:
            logger.warning(f"Failed to initialize Google TTS manager: {e}. TTS will not be available.")
            _tts_manager = None
    return _tts_manager

# For backward compatibility
tts_manager = None  # Will be lazily initialized when first accessed

