from deepgram import DeepgramClient, LiveTranscriptionEvents, LiveOptions, DeepgramClientOptions
from typing import Callable, Optional
import asyncio
import threading
import ssl
import certifi

from ..utils.config import settings
from ..utils.logger import logger


class DeepgramSTTClient:
    def __init__(self):
        import os
        
        os.environ['SSL_CERT_FILE'] = certifi.where()
        os.environ['REQUESTS_CA_BUNDLE'] = certifi.where()
        logger.info(f"SSL certificates configured: {certifi.where()}")
        
        self.api_key = settings.deepgram_api_key
        
        if not self.api_key or len(self.api_key.strip()) == 0:
            logger.error("Deepgram API key is missing or empty")
            raise ValueError("DEEPGRAM_API_KEY environment variable is not set or empty")
        
        logger.info(f"Deepgram API key loaded: {self.api_key[:10]}...")
        
        config = DeepgramClientOptions(
            options={"keepalive": "true"},
            url="wss://api.deepgram.com"
        )
        
        try:
            self.client = DeepgramClient(self.api_key, config)
            self.connection = None
            self.is_connected = False
            self.event_loop = None
            self._close_lock = threading.Lock()
            logger.info("Initialized Deepgram STT client")
        except Exception as e:
            logger.error(f"Failed to initialize Deepgram client: {e}")
            raise
    
    @property
    def is_healthy(self) -> bool:
        return self.is_connected and self.connection is not None
    
    async def start_transcription(
        self,
        on_transcript: Callable[[str, bool], None],
        on_error: Optional[Callable[[str], None]] = None
    ):
        try:
            self.event_loop = asyncio.get_running_loop()
            options = LiveOptions(
                model="nova-2",
                language="en-US",
                smart_format=True,
                interim_results=True,
                punctuate=True,
                diarize=False,
                filler_words=False,
                encoding="linear16",
                sample_rate=16000,
            )
            
            self.connection = self.client.listen.live.v("1")
            event_loop = self.event_loop
            
            def handle_transcript(self, result, **kwargs):
                try:
                    sentence = result.channel.alternatives[0].transcript
                    
                    if sentence:
                        is_final = result.is_final
                        logger.debug(f"Transcript: {sentence}")
                        if asyncio.iscoroutinefunction(on_transcript):
                            asyncio.run_coroutine_threadsafe(
                                on_transcript(sentence, is_final),
                                event_loop
                            )
                        else:
                            on_transcript(sentence, is_final)
                
                except Exception as e:
                    logger.error(f"Error processing transcript: {e}")
                    if on_error and event_loop:
                        if asyncio.iscoroutinefunction(on_error):
                            asyncio.run_coroutine_threadsafe(
                                on_error(str(e)),
                                event_loop
                            )
                        else:
                            on_error(str(e))
            
            def handle_error(self, error, **kwargs):
                error_str = str(error)
                if ("no close frame received or sent" in error_str or 
                    "WebSocketException" in error_str or
                    "connection closed" in error_str.lower() or
                    "_signal_exit" in error_str or
                    "send() failed" in error_str):
                    return
                
                logger.error(f"Deepgram error: {error}")
                if on_error and event_loop:
                    if asyncio.iscoroutinefunction(on_error):
                        asyncio.run_coroutine_threadsafe(
                            on_error(str(error)),
                            event_loop
                        )
                    else:
                        on_error(str(error))
            
            self.connection.on(LiveTranscriptionEvents.Transcript, handle_transcript)
            self.connection.on(LiveTranscriptionEvents.Error, handle_error)
            
            logger.info("Connecting to Deepgram...")
            try:
                result = self.connection.start(options)
                if result:
                    self.is_connected = True
                    logger.info("Deepgram connection started")
                else:
                    logger.error("Deepgram connection.start() returned False")
                    raise Exception("Failed to start Deepgram connection")
            except Exception as conn_error:
                logger.error(f"Deepgram connection failed: {conn_error}")
                raise Exception(f"Cannot connect to Deepgram: {conn_error}")
        
        except Exception as e:
            logger.error(f"Error starting Deepgram transcription: {e}")
            if on_error:
                if asyncio.iscoroutinefunction(on_error):
                    try:
                        await on_error(str(e))
                    except Exception:
                        pass
                else:
                    on_error(str(e))
            raise
    
    async def send_audio(self, audio_data: bytes):
        if not self.is_connected or not self.connection:
            logger.warning("Attempted to send audio while not connected")
            return
        
        try:
            self.connection.send(audio_data)
        except Exception as e:
            error_str = str(e)
            if any(x in error_str for x in ["no close frame", "WebSocketException", "connection closed", "send() failed"]):
                logger.debug(f"Deepgram connection lost: {e}")
                self.is_connected = False
                return
            
            logger.error(f"Error sending audio: {e}")
            self.is_connected = False
            raise
    
    async def stop_transcription(self):
        with self._close_lock:
            if not self.is_connected or not self.connection:
                logger.debug("Connection already closed")
                return
            
            try:
                self.is_connected = False
                
                import sys
                import io
                old_stderr = sys.stderr
                sys.stderr = io.StringIO()
                
                try:
                    await asyncio.to_thread(self.connection.finish)
                    logger.info("Stopped Deepgram transcription")
                finally:
                    sys.stderr = old_stderr
                    
            except Exception as e:
                error_str = str(e)
                if not any(x in error_str for x in ["no close frame", "WebSocketException", "connection closed"]):
                    logger.debug(f"Error stopping transcription: {e}")
            finally:
                self.connection = None


class DeepgramSTTManager:
    def __init__(self):
        self.sessions = {}
        logger.info("Initialized Deepgram STT manager")
    
    async def create_session(
        self,
        session_id: str,
        on_transcript: Callable[[str, bool], None],
        on_error: Optional[Callable[[str], None]] = None
    ) -> DeepgramSTTClient:
        if session_id in self.sessions:
            logger.info(f"Session {session_id} already exists - cleaning up before reconnect")
            await self.end_session(session_id)
        
        client = DeepgramSTTClient()
        await client.start_transcription(on_transcript, on_error)
        self.sessions[session_id] = client
        logger.info(f"Created session: {session_id}")
        return client
    
    async def end_session(self, session_id: str):
        if session_id in self.sessions:
            try:
                await self.sessions[session_id].stop_transcription()
            except Exception as e:
                logger.debug(f"Error stopping session {session_id}: {e}")
            finally:
                del self.sessions[session_id]
                logger.info(f"Ended session: {session_id}")
    
    def get_session(self, session_id: str) -> Optional[DeepgramSTTClient]:
        return self.sessions.get(session_id)


deepgram_manager = DeepgramSTTManager()
