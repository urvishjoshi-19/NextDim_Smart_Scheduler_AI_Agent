from deepgram import DeepgramClient, SpeakOptions
from typing import Optional, AsyncIterator
import asyncio
import httpx

from ..utils.config import settings
from ..utils.logger import logger

class DeepgramTTSClient:
    def __init__(self):
        self.api_key = settings.deepgram_api_key
        self.client = DeepgramClient(self.api_key)
        
        self.default_options = SpeakOptions(
            model="aura-asteria-en",
            encoding="linear16",
            sample_rate=16000,
            container="none"
        )
        
        logger.info("Initialized Deepgram TTS client")
    
    async def synthesize_streaming(self, text: str, voice_model: Optional[str] = None) -> AsyncIterator[bytes]:
        try:
            options = self.default_options
            if voice_model:
                options = SpeakOptions(
                    model=voice_model,
                    encoding="linear16",
                    sample_rate=16000,
                    container="none"
                )
            
            logger.debug(f"Streaming TTS: {text[:50]}...")
            
            response = self.client.speak.v("1").stream(
                {"text": text},
                options
            )
            
            # Use longer timeout for TTS to prevent hangs
            async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0)) as http_client:
                headers = {
                    "Authorization": f"Token {self.api_key}",
                    "Content-Type": "application/json"
                }
                
                payload = {"text": text}
                
                url = f"https://api.deepgram.com/v1/speak?model={options.model}&encoding={options.encoding}&sample_rate={options.sample_rate}&container={options.container}"
                
                async with http_client.stream(
                    "POST",
                    url,
                    headers=headers,
                    json=payload,
                ) as response:
                    response.raise_for_status()
                    
                    chunk_count = 0
                    # Smaller chunks for lower latency and smoother playback
                    # 4096 bytes = 2048 samples = 128ms at 16kHz (optimal for streaming)
                    async for chunk in response.aiter_bytes(chunk_size=4096):
                        if chunk and len(chunk) > 0:
                            chunk_count += 1
                            if chunk_count == 1:
                                logger.debug("First audio chunk received")
                            
                            yield chunk
                    
                    logger.debug(f"Completed streaming {chunk_count} chunks")
        
        except httpx.TimeoutException as e:
            logger.error(f"TTS request timeout: {e}")
            raise Exception("Speech synthesis timed out")
        except httpx.HTTPError as e:
            logger.error(f"TTS HTTP error: {e}")
            raise Exception(f"Speech synthesis failed: {str(e)}")
        except Exception as e:
            logger.error(f"Error in streaming TTS: {e}")
            raise
    
    def synthesize_sync(self, text: str, voice_model: Optional[str] = None) -> bytes:
        try:
            options = self.default_options
            if voice_model:
                options = SpeakOptions(
                    model=voice_model,
                    encoding="linear16",
                    sample_rate=16000,
                    container="none"
                )
            
            logger.debug(f"TTS: {text[:50]}...")
            
            response = self.client.speak.v("1").save(
                text,
                options,
                filename=None
            )
            
            logger.debug(f"Synthesized speech")
            return response.audio_content if hasattr(response, 'audio_content') else response
        
        except Exception as e:
            logger.error(f"Error in synchronous TTS: {e}")
            raise
    
    def set_voice(self, voice_model: str):
        self.default_options = SpeakOptions(
            model=voice_model,
            encoding="linear16",
            sample_rate=16000,
            container="none"
        )
        logger.info(f"Changed voice to: {voice_model}")

class DeepgramTTSManager:
    def __init__(self):
        self.client = DeepgramTTSClient()
        self.cache = {}
        logger.info("Initialized Deepgram TTS manager")
    
    async def synthesize_streaming(self, text: str, voice_model: Optional[str] = None) -> AsyncIterator[bytes]:
        cache_key = f"{text}:{voice_model or 'default'}"
        if len(text) < 50 and cache_key in self.cache:
            logger.debug("Using cached audio for short phrase")
            yield self.cache[cache_key]
            return
        
        audio_chunks = []
        async for chunk in self.client.synthesize_streaming(text, voice_model):
            audio_chunks.append(chunk)
            yield chunk
        
        if len(text) < 50:
            self.cache[cache_key] = b''.join(audio_chunks)
    
    def synthesize_sync(self, text: str, use_cache: bool = True, voice_model: Optional[str] = None) -> bytes:
        cache_key = f"{text}:{voice_model or 'default'}"
        
        if use_cache and cache_key in self.cache:
            logger.debug("Using cached audio")
            return self.cache[cache_key]
        
        audio = self.client.synthesize_sync(text, voice_model)
        
        if use_cache and len(text) < 100:
            self.cache[cache_key] = audio
        
        return audio
    
    def clear_cache(self):
        self.cache.clear()
        logger.info("Cleared TTS cache")
    
    def set_voice(self, voice_model: str):
        self.client.set_voice(voice_model)

deepgram_tts_manager = DeepgramTTSManager()

