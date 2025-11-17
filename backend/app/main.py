"""
Smart Scheduler AI Agent - Main FastAPI Application
Handles OAuth, WebSocket voice interface, and agent orchestration.
"""

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, JSONResponse
from typing import Dict, Optional
import asyncio
import json
import uuid
import time

from .auth.oauth import oauth_manager
from .agent.graph import run_agent, create_initial_state
from .agent.state import SchedulerState
from .agent.nodes import load_calendar_context
from .voice.deepgram_client import deepgram_manager
from .voice.deepgram_tts_client import deepgram_tts_manager
from .voice.tts_client import tts_manager  # Fallback to Google TTS if needed
from .utils.config import settings
from .utils.logger import logger
from .utils.debug_events import debug_emitter, emit_message
from .utils.websocket_logger import attach_websocket_logger, detach_websocket_logger

# Initialize FastAPI app
app = FastAPI(
    title="Smart Scheduler AI Agent",
    description="Voice-enabled AI scheduling assistant with Google Calendar integration",
    version="1.0.0"
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        settings.frontend_url,
        "http://localhost:3000",
        "https://nextdimensionai-jolyvhrdn-urvishs-projects-06d78642.vercel.app",  # Vercel production
        "https://*.vercel.app",  # All Vercel preview deployments
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory session storage (use Redis in production)
active_sessions: Dict[str, SchedulerState] = {}
user_sessions: Dict[str, str] = {}  # Maps session_id to user_id

@app.get("/")
async def root():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": "Smart Scheduler AI Agent",
        "version": "1.0.0"
    }

@app.get("/health")
async def health_check():
    """Detailed health check."""
    return {
        "status": "healthy",
        "components": {
            "api": "operational",
            "oauth": "configured",
            "voice": "ready"
        }
    }

# OAuth 2.0 Authentication Endpoints

@app.get("/auth/login")
async def login():
    """
    Initiate OAuth 2.0 login flow.
    Redirects user to Google consent screen.
    """
    try:
        auth_url, state = oauth_manager.get_authorization_url()
        logger.info(f"Redirecting to OAuth with state: {state}")
        return RedirectResponse(url=auth_url)
    except Exception as e:
        logger.error(f"Error initiating OAuth: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/auth/callback")
async def auth_callback(request: Request, code: str, state: str):
    """
    OAuth 2.0 callback endpoint.
    Exchanges authorization code for credentials.
    """
    try:
        # Exchange code for credentials
        credentials = oauth_manager.exchange_code_for_credentials(code, state)
        
        # Get user info
        user_info = oauth_manager.get_user_info(credentials)
        user_id = user_info["user_id"]
        
        # Save credentials
        oauth_manager.save_credentials(user_id, credentials)
        
        logger.info(f"User authenticated: {user_info['email']}")
        
        # Determine which frontend to redirect to (support both local and Vercel)
        referer = request.headers.get("referer", "")
        if "vercel.app" in referer:
            # Extract the Vercel domain from referer
            frontend_url = "/".join(referer.split("/")[:3])  # Gets https://your-app.vercel.app
        else:
            frontend_url = settings.frontend_url
        
        # Redirect to frontend with success
        return RedirectResponse(
            url=f"{frontend_url}/chat?auth=success&user_id={user_id}"
        )
    
    except Exception as e:
        logger.error(f"Error in OAuth callback: {e}")
        
        # Determine which frontend to redirect to (support both local and Vercel)
        referer = request.headers.get("referer", "")
        if "vercel.app" in referer:
            frontend_url = "/".join(referer.split("/")[:3])
        else:
            frontend_url = settings.frontend_url
        
        return RedirectResponse(
            url=f"{frontend_url}?auth=error&message={str(e)}"
        )

@app.get("/auth/status/{user_id}")
async def auth_status(user_id: str):
    """Check if user is authenticated."""
    credentials = oauth_manager.load_credentials(user_id)
    
    return {
        "authenticated": credentials is not None,
        "user_id": user_id if credentials else None
    }

@app.post("/auth/logout/{user_id}")
async def logout(user_id: str):
    """Revoke user credentials."""
    success = oauth_manager.revoke_credentials(user_id)
    
    return {
        "success": success,
        "message": "Logged out successfully" if success else "User not found"
    }

# WebSocket Voice Interface

@app.websocket("/ws/voice/{user_id}")
async def voice_websocket(websocket: WebSocket, user_id: str):
    """
    WebSocket endpoint for voice interaction.
    Handles bidirectional audio streaming: STT -> Agent -> TTS.
    """
    await websocket.accept()
    logger.info(f"WebSocket connection established for user: {user_id}")
    
    # Attach WebSocket logger to send ALL backend logs to frontend
    ws_log_handler = attach_websocket_logger(websocket)
    
    # Check authentication
    credentials = oauth_manager.load_credentials(user_id)
    if not credentials:
        await websocket.send_json({
            "type": "error",
            "message": "User not authenticated. Please login first."
        })
        await websocket.close()
        return
    
    # Create session
    session_id = str(uuid.uuid4())
    state = create_initial_state(user_id, timezone="Asia/Kolkata")  # IST timezone
    
        # LOAD CALENDAR CONTEXT FOR SESSION (before greeting)
        # Load calendar events (-20 to +20 days, IST) ONCE at session start
    # This gives the LLM full calendar awareness for intelligent scheduling
    logger.info("⏳ Loading calendar context for new session...")
    state = load_calendar_context(state)
    logger.info(f"✅ Session initialized with calendar context ({len(state.get('calendar_events_raw', []))} events)")
        
    active_sessions[session_id] = state
    user_sessions[session_id] = user_id
    
    # Accumulated transcript buffer
    transcript_buffer = ""
    is_currently_speaking = False  # Track if user is actively speaking
    is_ai_active = False  # Track if AI is thinking OR speaking (blocks user input)
    is_processing_utterance = False  # Prevent double-processing
    
    last_transcript_time = 0.0  # Track when last transcript arrived
    transcript_timeout_task: Optional[asyncio.Task] = None  # Timeout task handle
    safety_timeout_task: Optional[asyncio.Task] = None  # Safety timeout for audio playback
    TRANSCRIPT_TIMEOUT_SECONDS = 3.0  # Process after 3 seconds of no transcripts
    SPEECH_STARTED_TIMEOUT_SECONDS = 10.0  # Reset if no transcripts within 10 seconds of SpeechStarted
    
    async def trigger_speech_started_timeout():
        """Safety net: Reset state if no transcripts arrive within 10 seconds of SpeechStarted."""
        nonlocal is_currently_speaking, transcript_buffer
        
        await asyncio.sleep(SPEECH_STARTED_TIMEOUT_SECONDS)
        
        # If we reach here and still no transcript buffer, something's wrong
        if not transcript_buffer.strip():
            logger.warning("⚠️ [SPEECH TIMEOUT] SpeechStarted fired but no transcripts received in 10 seconds")
            logger.warning("   Possible causes: Audio too quiet, background noise, or microphone issues")
            logger.warning("   Resetting state to idle...")
            
            is_currently_speaking = False
            
            # Notify frontend
            await websocket.send_json({
                "type": "state_change",
                "state": "idle"
            })
            
            await websocket.send_json({
                "type": "log",
                "level": "warning",
                "message": "⚠️ No speech detected. Please speak louder or check your microphone."
            })
    
    async def trigger_utterance_end_by_timeout():
        """Trigger utterance end when no transcripts received for 3 seconds."""
        nonlocal is_processing_utterance, is_ai_active, transcript_buffer, is_currently_speaking
        
        await asyncio.sleep(TRANSCRIPT_TIMEOUT_SECONDS)
        
        # Only process if we have a transcript and aren't already processing
        if transcript_buffer.strip() and not is_processing_utterance and not is_ai_active:
            logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            logger.info("⏰ [TRANSCRIPT TIMEOUT] No new transcripts for 3 seconds - processing utterance")
            
            # Block user input immediately
            is_ai_active = True
            is_currently_speaking = False
            is_processing_utterance = True
            
            full_transcript = transcript_buffer.strip()
            logger.info(f"📝 Processing transcript: {full_transcript}")
            logger.info("🚫 [BLOCKING USER INPUT] AI is now thinking/speaking")
            
            # Notify frontend: user stopped speaking, AI is thinking
            await websocket.send_json({
                "type": "state_change",
                "state": "thinking"
            })
            
            try:
                # Process with AI agent (handles thinking + speaking + voice response internally)
                logger.info("🤖 Sending to AI agent...")
                response = await process_with_agent(websocket, session_id, full_transcript)
                
                # Clear transcript buffer for next utterance
                transcript_buffer = ""
                logger.info("✅ Utterance processing complete")
                
                                # This prevents user from speaking while AI audio is still playing
                logger.info("⏸️ Waiting for frontend to confirm audio playback complete...")
                
                # Safety timeout: if frontend doesn't confirm within 10 seconds, auto-unblock
                async def safety_timeout():
                    await asyncio.sleep(10.0)
                    nonlocal is_ai_active
                    if is_ai_active:
                        logger.warning("⚠️ [SAFETY TIMEOUT] Frontend didn't confirm audio complete - auto-unblocking")
                        is_ai_active = False
                        await websocket.send_json({
                            "type": "state_change",
                            "state": "idle"
                        })
                
                safety_timeout_task = asyncio.create_task(safety_timeout())
                
            except Exception as e:
                logger.error(f"❌ Error processing utterance: {e}")
                import traceback
                logger.error(f"Stack trace: {traceback.format_exc()}")
                await websocket.send_json({
                    "type": "error",
                    "message": f"Error processing request: {str(e)}"
                })
                await websocket.send_json({
                    "type": "state_change",
                    "state": "idle"
                })
            finally:
                is_processing_utterance = False
                # Note: is_ai_active remains True until frontend confirms audio playback complete
                logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    
    # Deepgram callbacks
    async def on_transcript(text: str, is_final: bool):
        """Handle transcript from Deepgram."""
        nonlocal transcript_buffer, is_currently_speaking, last_transcript_time, transcript_timeout_task
        
        if is_ai_active:
            logger.debug("🚫 [TRANSCRIPT BLOCKED] AI is active - ignoring transcript")
            return
        
        last_transcript_time = time.time()
        
        if is_final:
            # Final transcript segment - add to buffer
            if text.strip():  # Only add non-empty segments
                if transcript_buffer:
                    transcript_buffer += " " + text
                else:
                    transcript_buffer = text
                
                full_text = transcript_buffer.strip()
                
                if full_text:
                    logger.info(f"Transcript segment: {text}")
                    is_currently_speaking = True
                    
                    # Send transcript to user for display
                    await websocket.send_json({
                        "type": "transcript",
                        "text": full_text,
                        "is_final": True
                    })
                    
                    if transcript_timeout_task and not transcript_timeout_task.done():
                        transcript_timeout_task.cancel()
                        logger.debug("⏱️ Cancelled safety timeout, starting transcript timeout (final text)")
                    
                    # Start 3-second countdown
                    transcript_timeout_task = asyncio.create_task(trigger_utterance_end_by_timeout())
                    logger.debug("⏱️ Started 3-second transcript timeout")
        else:
            # Interim transcript - just display, don't add to buffer
            current_display = (transcript_buffer + " " + text).strip()
            if current_display:
                await websocket.send_json({
                    "type": "transcript",
                    "text": current_display,
                    "is_final": False
                })
                
                # Also reset timeout on interim results (user is still speaking)
                if transcript_timeout_task and not transcript_timeout_task.done():
                    transcript_timeout_task.cancel()
                    logger.debug("⏱️ Reset transcript timeout (interim text)")
                
                transcript_timeout_task = asyncio.create_task(trigger_utterance_end_by_timeout())
                logger.debug("⏱️ Started 3-second transcript timeout (interim)")
    
    async def on_utterance_end():
        """🎯 Deepgram detected end of utterance - process transcript!"""
        nonlocal transcript_buffer, is_processing_utterance, is_ai_active, is_currently_speaking, transcript_timeout_task
        
        logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        logger.info("🎯 [UTTERANCE END] Deepgram detected end of speech")
        
        # Cancel timeout task if it exists (Deepgram detected end before timeout)
        if transcript_timeout_task and not transcript_timeout_task.done():
            transcript_timeout_task.cancel()
            logger.debug("⏱️ Cancelled transcript timeout (Deepgram UtteranceEnd fired)")
        
        # 🚨 CRITICAL: Block user input IMMEDIATELY when utterance ends
        # This prevents the user's speech from being processed while AI is thinking/speaking
        is_ai_active = True
        is_currently_speaking = False
        
        # Prevent double-processing
        if is_processing_utterance:
            logger.info("⏭️ Already processing, skipping")
            logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            return
        
        full_transcript = transcript_buffer.strip()
        
        if not full_transcript:
            logger.warning("⚠️ Empty transcript buffer on utterance end")
            is_ai_active = False  # Reset flag if nothing to process
            logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            return
        
        logger.info(f"📝 Processing transcript: {full_transcript}")
        logger.info("🚫 [BLOCKING USER INPUT] AI is now thinking/speaking")
        is_processing_utterance = True
        
        # Notify frontend: user stopped speaking, AI is thinking
        await websocket.send_json({
            "type": "state_change",
            "state": "thinking"
        })
        
        try:
            # Process with AI agent (handles thinking + speaking + voice response internally)
            logger.info("🤖 Sending to AI agent...")
            response = await process_with_agent(websocket, session_id, full_transcript)
            
            # Clear transcript buffer for next utterance
            transcript_buffer = ""
            logger.info("✅ Utterance processing complete")
            
                        # This prevents user from speaking while AI audio is still playing
            logger.info("⏸️ Waiting for frontend to confirm audio playback complete...")
            
        except Exception as e:
            logger.error(f"❌ Error processing utterance: {e}")
            import traceback
            logger.error(f"Stack trace: {traceback.format_exc()}")
            await websocket.send_json({
                "type": "error",
                "message": f"Error processing request: {str(e)}"
            })
            await websocket.send_json({
                "type": "state_change",
                "state": "idle"
            })
        finally:
            is_processing_utterance = False
            # Note: is_ai_active remains True until frontend confirms audio playback complete
            logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    
    async def on_speech_started():
        """🎤 Deepgram detected speech started."""
        nonlocal is_currently_speaking, is_ai_active, transcript_timeout_task
        
        if is_ai_active:
            logger.info("🚫 [SPEECH BLOCKED] AI is active - ignoring user speech detection")
            return
        
        logger.info("🎤 [SPEECH STARTED] Deepgram detected user speaking")
        is_currently_speaking = True
        
        if transcript_timeout_task and not transcript_timeout_task.done():
            transcript_timeout_task.cancel()
        
        transcript_timeout_task = asyncio.create_task(trigger_speech_started_timeout())
        logger.debug("⏱️ Started 10-second safety timeout (waiting for transcripts)")
        
        # Notify frontend: show listening state
        await websocket.send_json({
            "type": "state_change",
            "state": "listening"
        })
    
    async def on_error(error: str):
        """Handle Deepgram errors."""
        logger.error(f"Deepgram error: {error}")
        await websocket.send_json({
            "type": "error",
            "message": f"Speech recognition error: {error}"
        })
    
    # Start Deepgram session with endpointing callbacks
    deepgram_client = await deepgram_manager.create_session(
        session_id=session_id,
        on_transcript=on_transcript,
        on_utterance_end=on_utterance_end,
        on_speech_started=on_speech_started,
        on_error=on_error
    )
    
    # Track connection health
    last_health_check = time.time()
    health_check_interval = 5.0  # Check every 5 seconds
    reconnection_in_progress = False
    
    async def check_and_reconnect_if_needed():
        """Check if Deepgram connection is healthy and reconnect if needed."""
        nonlocal deepgram_client, reconnection_in_progress
        
        # Prevent multiple simultaneous reconnection attempts
        if reconnection_in_progress:
            return
        
        if not deepgram_client.is_healthy:
            reconnection_in_progress = True
            logger.warning("⚠️ Deepgram connection lost - attempting to reconnect...")
            
            try:
                await websocket.send_json({
                    "type": "log",
                    "level": "warning",
                    "message": "🔄 Reconnecting to speech recognition service..."
                })
            except Exception:
                pass  # WebSocket might be closed
            
            try:
                # End old session (but don't fail if it errors)
                try:
                    await deepgram_manager.end_session(session_id)
                except Exception as e:
                    logger.debug(f"Error ending old session: {e}")
                
                # Small delay before reconnecting
                await asyncio.sleep(0.5)
                
                # Create new session with same callbacks
                deepgram_client = await deepgram_manager.create_session(
                    session_id=session_id,
                    on_transcript=on_transcript,
                    on_error=on_error
                )
                
                logger.info("✅ Deepgram connection restored")
                try:
                    await websocket.send_json({
                        "type": "log",
                        "level": "success",
                        "message": "✅ Speech recognition reconnected successfully"
                    })
                except Exception:
                    pass  # WebSocket might be closed
                
            except Exception as e:
                logger.error(f"Failed to reconnect Deepgram: {e}")
                try:
                    await websocket.send_json({
                        "type": "error",
                        "message": "Speech recognition connection failed. Please refresh the page."
                    })
                except Exception:
                    pass  # WebSocket might be closed
            finally:
                reconnection_in_progress = False
    
    try:
        # Prepare welcome message (but wait for frontend to be ready)
        welcome_text = "Hello! I'm your scheduling assistant. How can I help you schedule a meeting today?"
        greeting_sent = False
        
        # Main WebSocket loop
        while True:
            # Periodic health check (every 5 seconds)
            current_time = time.time()
            if current_time - last_health_check > health_check_interval:
                last_health_check = current_time
                await check_and_reconnect_if_needed()
            
            # Receive message with timeout to allow periodic health checks
            try:
                data = await asyncio.wait_for(websocket.receive(), timeout=1.0)
            except asyncio.TimeoutError:
                # No message received - continue to next iteration for health check
                continue
            
            if "bytes" in data:
                # Audio data from client
                audio_data = data["bytes"]
                audio_size = len(audio_data)
                
                logger.debug(f"📦 [BACKEND] Received audio chunk: {audio_size} bytes")
                
                                # Block audio during thinking AND speaking phases
                if not is_ai_active:
                    logger.debug(f"   ✅ AI idle - processing audio")
                    # Check connection health before sending (reconnect if needed)
                    await check_and_reconnect_if_needed()
                    
                    # Send audio to Deepgram
                    await deepgram_client.send_audio(audio_data)
                    logger.debug(f"   ✅ Sent {audio_size} bytes to Deepgram")
                else:
                    logger.debug(f"   🚫 Ignoring audio - AI is thinking/speaking")
            
            elif "text" in data:
                # JSON message from client
                message = json.loads(data["text"])
                
                if message.get("type") == "stop":
                    break
                elif message.get("type") == "ready_for_greeting":
                    # Frontend AudioContext is ready - send greeting now
                    if not greeting_sent:
                        logger.info("🎙️ Frontend ready, sending greeting message")
                        
                        try:
                            # Send text message first
                            await websocket.send_json({
                                "type": "response",
                                "text": welcome_text
                            })
                            logger.info(f"✅ Greeting text sent: {welcome_text[:50]}...")
                            
                            # Small delay to ensure text is received first
                            await asyncio.sleep(0.1)
                            
                            # Then send audio (block user input while greeting plays)
                            is_ai_active = True
                            logger.info("🚫 [BLOCKING USER INPUT] Sending greeting")
                            await send_voice_response(websocket, welcome_text)
                            is_ai_active = False
                            logger.info("✅ [UNBLOCKING USER INPUT] Greeting complete")
                            logger.info("✅ Greeting audio sent successfully")
                            
                            greeting_sent = True
                        except Exception as e:
                            logger.error(f"❌ Error sending greeting: {e}")
                            is_ai_active = False  # Reset flag on error
                            await websocket.send_json({
                                "type": "error",
                                "message": "Failed to send greeting"
                            })
                elif message.get("type") == "stop_speaking":
                    # User released spacebar - process accumulated transcript
                    
                    # Cancel timeout task if it exists
                    if transcript_timeout_task and not transcript_timeout_task.done():
                        transcript_timeout_task.cancel()
                        logger.debug("⏱️ Cancelled transcript timeout (manual stop)")
                    
                    final_transcript = transcript_buffer.strip()
                    if final_transcript:
                        logger.info(f"Processing complete transcript: {final_transcript}")
                        
                        # Send confirmation that we're processing
                        await websocket.send_json({
                            "type": "transcript_processing",
                            "text": final_transcript
                        })
                        
                        # Process with agent (block user input)
                        is_ai_active = True
                        logger.info("🚫 [BLOCKING USER INPUT] Processing user request")
                        await process_with_agent(websocket, session_id, final_transcript)
                        # Note: is_ai_active remains True until frontend confirms audio playback complete
                        logger.info("⏸️ Waiting for frontend to confirm audio playback complete...")
                        
                        # Clear buffer AFTER processing
                        transcript_buffer = ""
                        is_currently_speaking = False
                        logger.info("✅ Transcript buffer cleared")
                    else:
                        logger.info("Stop speaking triggered but no transcript accumulated")
                        
                        # Check if connection is healthy
                        if not deepgram_client.is_healthy:
                            logger.warning("⚠️ No transcript received - Deepgram connection was lost")
                            await websocket.send_json({
                                "type": "log",
                                "level": "warning",
                                "message": "⚠️ Speech recognition connection lost. Reconnecting..."
                            })
                            # Trigger reconnection
                            await check_and_reconnect_if_needed()
                        
                        # Send idle status
                        await websocket.send_json({
                            "type": "status",
                            "status": "idle"
                        })
                elif message.get("type") == "speech_ended":
                    # VAD detected speech end - process accumulated transcript
                    logger.info("=" * 60)
                    logger.info("🛑 [BACKEND] Received speech_ended signal")
                    logger.info(f"   Samples reported: {message.get('samples', 'unknown')}")
                    logger.info(f"   Duration: {message.get('duration_ms', 'unknown')}ms")
                    logger.info(f"   Transcript buffer: '{transcript_buffer}'")
                    logger.info(f"   Buffer length: {len(transcript_buffer)}")
                    
                    # Cancel timeout task if it exists
                    if transcript_timeout_task and not transcript_timeout_task.done():
                        transcript_timeout_task.cancel()
                        logger.debug("⏱️ Cancelled transcript timeout (VAD speech_ended)")
                    
                    final_transcript = transcript_buffer.strip()
                    if final_transcript:
                        logger.info(f"   ✅ Processing transcript: '{final_transcript}'")
                        
                        # Send confirmation that we're processing
                        await websocket.send_json({
                            "type": "transcript_processing",
                            "text": final_transcript
                        })
                        
                        # Process with agent (block user input)
                        is_ai_active = True
                        logger.info("🚫 [BLOCKING USER INPUT] Processing user request")
                        await process_with_agent(websocket, session_id, final_transcript)
                        # Note: is_ai_active remains True until frontend confirms audio playback complete
                        logger.info("⏸️ Waiting for frontend to confirm audio playback complete...")
                        
                        # Clear buffer AFTER processing
                        transcript_buffer = ""
                        is_currently_speaking = False
                        logger.info("   ✅ Transcript processed and cleared")
                    else:
                        logger.warning("   ⚠️ Speech ended but NO TRANSCRIPT in buffer!")
                        logger.warning("   This means Deepgram didn't transcribe anything")
                        logger.warning("   Possible causes:")
                        logger.warning("     1. Audio didn't reach Deepgram")
                        logger.warning("     2. Audio was too quiet/noisy")
                        logger.warning("     3. Deepgram connection issue")
                        
                        # Send idle status
                        await websocket.send_json({
                            "type": "status",
                            "status": "idle"
                        })
                    logger.info("=" * 60)
                elif message.get("type") == "audio_playback_complete":
                    # Frontend notifies that audio playback is complete
                    logger.info("🔊 [AUDIO COMPLETE] Frontend finished playing audio")
                    
                    # Cancel safety timeout if it exists
                    if safety_timeout_task and not safety_timeout_task.done():
                        safety_timeout_task.cancel()
                        logger.debug("Cancelled safety timeout (frontend confirmed)")
                    
                    # Now it's safe to unblock user input
                    is_ai_active = False
                    logger.info("✅ [UNBLOCKING USER INPUT] Audio playback complete, ready for user")
                    
                    # Send idle state
                    await websocket.send_json({
                        "type": "state_change",
                        "state": "idle"
                    })
                    
                elif message.get("type") == "request_greeting":
                    # Client requested initial greeting (for auto-connect flow)
                    logger.info("Client requested greeting message")
                    # The greeting is already sent above, but we can send it again if needed
                    # This ensures the client gets it even if they missed the first one
                    pass  # Welcome message already sent at connection
                elif message.get("type") == "text":
                    # Text message (fallback if voice fails)
                    user_text = message.get("text", "")
                    if user_text:
                        await process_with_agent(websocket, session_id, user_text)
    
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for user: {user_id}")
    
    except Exception as e:
        logger.error(f"Error in WebSocket: {e}")
        # Try to send error message, but don't fail if connection is already closed
        try:
            await websocket.send_json({
                "type": "error",
                "message": str(e)
            })
        except (WebSocketDisconnect, RuntimeError):
            # Connection already closed, can't send error message
            pass
    
    finally:
        # Cancel transcript timeout task if it exists
        if transcript_timeout_task and not transcript_timeout_task.done():
            transcript_timeout_task.cancel()
            logger.debug("⏱️ Cancelled transcript timeout task during cleanup")
        
        # Cancel safety timeout task if it exists
        if safety_timeout_task and not safety_timeout_task.done():
            safety_timeout_task.cancel()
            logger.debug("⏱️ Cancelled safety timeout task during cleanup")
        
        # Cleanup
        await deepgram_manager.end_session(session_id)
        if session_id in active_sessions:
            del active_sessions[session_id]
        if session_id in user_sessions:
            del user_sessions[session_id]
        
        # Detach WebSocket logger
        detach_websocket_logger(ws_log_handler)
        
        logger.info(f"Cleaned up session: {session_id}")

async def process_with_agent(websocket: WebSocket, session_id: str, user_message: str):
    """
    Process user message with the LangGraph agent.
    
    Args:
        websocket: WebSocket connection
        session_id: Session identifier
        user_message: User's message text
    """
    try:
        # Send log
        await websocket.send_json({
            "type": "log",
            "level": "info",
            "message": f"📨 Processing user message: {user_message[:50]}..."
        })
        
        # Get session state
        state = active_sessions.get(session_id)
        if not state:
            logger.error(f"Session not found: {session_id}")
            await websocket.send_json({
                "type": "log",
                "level": "error",
                "message": f"❌ Session not found: {session_id}"
            })
            return
        
        # Add user message to state
        state["messages"].append({
            "role": "user",
            "content": user_message
        })
        
        # Send thinking indicator
        await websocket.send_json({
            "type": "status",
            "status": "thinking"
        })
        
        await websocket.send_json({
            "type": "log",
            "level": "info",
            "message": "🤖 Invoking LangGraph agent..."
        })
        
        await websocket.send_json({
            "type": "workflow",
            "step": "started",
            "message": "Agent workflow started"
        })
        
        # Run agent synchronously (LangGraph handles its own threading)
        from .agent.graph import scheduling_agent
        result = scheduling_agent.invoke(state)
        
        # Update session state
        active_sessions[session_id] = result
        
        await websocket.send_json({
            "type": "log",
            "level": "success",
            "message": "✅ Agent processing completed"
        })
        
        await websocket.send_json({
            "type": "workflow",
            "step": "completed",
            "message": "Agent workflow completed",
            "booking_confirmed": result.get("booking_confirmed", False),
            "state": {
                "duration": result.get("meeting_duration_minutes"),
                "date": result.get("preferred_date"),
                "slots_found": len(result.get("available_slots") or [])
            },
            "booking_details": result.get("last_completed_booking") if result.get("booking_confirmed") else None
        })
        
        # Get agent's response
        agent_response = None
        messages = result.get("messages") or []
        if messages:
            for msg in reversed(messages):
                if msg.get("role") == "assistant":
                    agent_response = msg.get("content")
                    break
        
        if agent_response:
            await websocket.send_json({
                "type": "log",
                "level": "info",
                "message": f"💬 Agent response: {agent_response[:50]}..."
            })
            
            # CRITICAL: Send text response first (for display)
            await websocket.send_json({
                "type": "response",
                "text": agent_response
            })
            
            # Notify frontend: AI is now speaking
            await websocket.send_json({
                "type": "state_change",
                "state": "speaking"
            })
            
            # Then send voice response
            logger.info(f"🔊 Generating voice response for text: '{agent_response[:100]}...'")
            logger.info(f"📊 Full response length: {len(agent_response)} characters")
            try:
                await send_voice_response(websocket, agent_response)
                logger.info("✅ Voice response completed successfully")
            except Exception as tts_error:
                logger.error(f"❌ CRITICAL TTS Error: {tts_error}")
                import traceback
                logger.error(f"❌ Full Traceback:\n{traceback.format_exc()}")
                # Try to notify frontend of the error
                try:
                    await websocket.send_json({
                        "type": "error",
                        "message": f"Speech synthesis failed: {str(tts_error)}"
                    })
                except:
                    pass
            
            return agent_response
        else:
            # No response found - send status
            await websocket.send_json({
                "type": "status",
                "status": "idle"
            })
            
            return None
        
    except (WebSocketDisconnect, RuntimeError):
        # Client disconnected during processing - just log it
        logger.info("Client disconnected during agent processing")
        raise  # Re-raise to be handled by caller
    
    except Exception as e:
        logger.error(f"Error processing with agent: {e}")
        # Try to send error messages, but don't fail if connection is closed
        try:
            await websocket.send_json({
                "type": "log",
                "level": "error",
                "message": f"❌ Error: {str(e)}"
            })
            await websocket.send_json({
                "type": "error",
                "message": "Sorry, I encountered an error processing your request."
            })
        except (WebSocketDisconnect, RuntimeError):
            # Connection already closed, can't send error message
            pass

async def send_voice_response(websocket: WebSocket, text: str):
    """
    Convert text to speech and stream to client for low latency.
    Uses Deepgram Aura streaming TTS for <300ms first chunk.
    
    Args:
        websocket: WebSocket connection
        text: Text to convert to speech
    """
    logger.info(f"📢 [TTS START] Entering send_voice_response with text length: {len(text)}")
    
    if not text or len(text.strip()) == 0:
        logger.error("❌ [TTS] Empty text provided, cannot generate speech")
        return
    
    try:
        # Send audio start indicator (text response already sent in process_with_agent)
        logger.info("📤 [TTS] Sending audio_start message to frontend")
        try:
            await websocket.send_json({
                "type": "audio_start",
                "format": "pcm16",
                "sample_rate": 16000
            })
            logger.info("✅ [TTS] audio_start message sent successfully")
        except Exception as ws_error:
            logger.error(f"❌ [TTS] Failed to send audio_start: {ws_error}")
            raise
        
        logger.info("📤 [TTS] Sending TTS log message to frontend")
        await websocket.send_json({
            "type": "log",
            "level": "info",
            "message": f"🎙️ Starting TTS synthesis: {text[:30]}..."
        })
        
        logger.info(f"🎙️ [TTS] Calling Deepgram TTS for: {text[:50]}...")
        
        # Stream audio chunks as they arrive from Deepgram Aura
        chunk_count = 0
        try:
            logger.info("🔄 [TTS] Starting Deepgram synthesis stream...")
            async for audio_chunk in deepgram_tts_manager.synthesize_streaming(text):
                logger.debug(f"[TTS] Received chunk {chunk_count + 1}, size: {len(audio_chunk)} bytes")
                chunk_count += 1
                
                try:
                    # Send audio chunk as binary data
                    await websocket.send_bytes(audio_chunk)
                    
                    # Log first chunk for latency monitoring
                    if chunk_count == 1:
                        logger.info(f"First audio chunk sent (streaming started)")
                        await websocket.send_json({
                            "type": "log",
                            "level": "success",
                            "message": f"✅ First audio chunk delivered ({chunk_count} total)"
                        })
                except (WebSocketDisconnect, RuntimeError):
                    # Client disconnected during streaming - stop sending
                    logger.info(f"Client disconnected during audio streaming (sent {chunk_count} chunks)")
                    return
            
            logger.debug(f"Streamed {chunk_count} audio chunks for response")
            await websocket.send_json({
                "type": "log",
                "level": "success",
                "message": f"🔊 Audio streaming complete ({chunk_count} chunks)"
            })
        
        except Exception as streaming_error:
            # Fallback to Google TTS if Deepgram fails
            logger.error(f"❌ [TTS] Deepgram streaming failed: {streaming_error}")
            import traceback
            logger.error(f"[TTS] Traceback: {traceback.format_exc()}")
            logger.info("🔄 [TTS] Falling back to Google TTS...")
            
            try:
                import base64
                audio_bytes = await asyncio.to_thread(
                    tts_manager.client.synthesize_speech,
                    text
                )
                logger.info(f"✅ [TTS] Google TTS generated {len(audio_bytes)} bytes")
                audio_base64 = base64.b64encode(audio_bytes).decode('utf-8')
                
                await websocket.send_json({
                    "type": "audio",
                    "audio": audio_base64,
                    "format": "pcm16",
                    "fallback": True
                })
                logger.info("✅ [TTS] Fallback audio sent successfully")
            except Exception as fallback_error:
                logger.error(f"❌ [TTS] Fallback TTS also failed: {fallback_error}")
                logger.error(f"[TTS] Fallback traceback: {traceback.format_exc()}")
                raise
        
        # Send audio end indicator
        logger.info("📤 [TTS] Sending audio_end message")
        await websocket.send_json({
            "type": "audio_end"
        })
        logger.info("✅ [TTS] audio_end message sent, TTS complete!")
    
    except (WebSocketDisconnect, RuntimeError) as e:
        # Client disconnected while sending - this is normal, just log it
        logger.warning(f"⚠️ [TTS] Client disconnected during voice response: {e}")
        # Don't try to send error message - connection is closed
    
    except Exception as e:
        logger.error(f"❌ [TTS] EXCEPTION in send_voice_response: {e}")
        import traceback
        logger.error(f"❌ [TTS] Exception Traceback:\n{traceback.format_exc()}")
        # Try to send error message, but don't fail if connection is closed
        try:
            await websocket.send_json({
                "type": "error",
                "message": f"Failed to generate voice response: {str(e)}"
            })
        except (WebSocketDisconnect, RuntimeError):
            # Connection already closed, can't send error message
            logger.debug("[TTS] Could not send error message, connection closed")
            pass
        # Re-raise to let caller know TTS failed
        raise

# REST API Endpoints (for testing without voice)

@app.post("/api/chat")
async def chat(request: Request):
    """
    Text-based chat endpoint for testing.
    
    Request body:
        {
            "user_id": "string",
            "message": "string",
            "session_id": "string" (optional)
        }
    """
    try:
        body = await request.json()
        user_id = body.get("user_id")
        message = body.get("message")
        session_id = body.get("session_id", str(uuid.uuid4()))
        
        if not user_id or not message:
            raise HTTPException(status_code=400, detail="user_id and message required")
        
        # Check authentication
        credentials = oauth_manager.load_credentials(user_id)
        if not credentials:
            raise HTTPException(status_code=401, detail="User not authenticated")
        
        # Get or create session
        if session_id not in active_sessions:
            state = create_initial_state(user_id, timezone="Asia/Kolkata")
            # Load calendar context for new session
            logger.info("⏳ Loading calendar context for new REST API session...")
            state = load_calendar_context(state)
            active_sessions[session_id] = state
        
        state = active_sessions[session_id]
        
        # Add user message
        state["messages"].append({
            "role": "user",
            "content": message
        })
        emit_message("user", message)
        
        # Run agent
        from .agent.graph import scheduling_agent
        result = scheduling_agent.invoke(state)
        
        # Update session
        active_sessions[session_id] = result
        
        # Get response
        agent_response = None
        messages = result.get("messages") or []
        if messages:
            for msg in reversed(messages):
                if msg.get("role") == "assistant":
                    agent_response = msg.get("content")
                    if agent_response:
                        emit_message("assistant", agent_response)
                    break
        
        return {
            "session_id": session_id,
            "response": agent_response or "I'm here to help you schedule.",
            "state": {
                "duration": result.get("meeting_duration_minutes"),
                "date": result.get("preferred_date"),
                "time": result.get("time_preference"),
                "slots": result.get("available_slots")
            }
        }
    
    except Exception as e:
        logger.error(f"Error in chat endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/sessions/{user_id}")
async def get_sessions(user_id: str):
    """Get active sessions for a user."""
    user_session_ids = [
        sid for sid, uid in user_sessions.items() if uid == user_id
    ]
    
    return {
        "user_id": user_id,
        "sessions": user_session_ids,
        "count": len(user_session_ids)
    }

# Debug Dashboard

from fastapi.responses import HTMLResponse
from pathlib import Path

@app.get("/debug", response_class=HTMLResponse)
async def debug_dashboard():
    """Serve the debug dashboard."""
    debug_html_path = Path(__file__).parent / "static" / "debug.html"
    if debug_html_path.exists():
        return debug_html_path.read_text()
    return "<h1>Debug dashboard not found</h1>"

@app.get("/voice-test", response_class=HTMLResponse)
async def voice_test_client():
    """Serve the voice test client."""
    voice_test_path = Path(__file__).parent / "static" / "voice_test.html"
    if voice_test_path.exists():
        return voice_test_path.read_text()
    return "<h1>Voice test client not found</h1>"

@app.websocket("/debug/ws")
async def debug_websocket(websocket: WebSocket):
    """WebSocket endpoint for real-time debug events."""
    await websocket.accept()
    logger.info("Debug WebSocket client connected")
    
    # Send session info (use first available user or a test user)
    test_user_id = "100756814331326833034"  # Use the OAuth'd user
    await websocket.send_json({
        "type": "session_info",
        "data": {
            "user_id": test_user_id,
            "session_id": None
        }
    })
    
    # Create listener for debug events
    async def send_event(event):
        try:
            await websocket.send_json(event)
        except:
            pass  # Connection closed
    
    # Register listener
    debug_emitter.add_listener(send_event)
    
    # Send event history
    for event in debug_emitter.get_history():
        try:
            await websocket.send_json(event)
        except:
            break
    
    try:
        # Keep connection alive
        while True:
            # Just receive to keep connection open
            data = await websocket.receive_text()
            # Echo back for testing
            await websocket.send_json({
                "type": "echo",
                "data": {"message": "received"}
            })
    except WebSocketDisconnect:
        logger.info("Debug WebSocket client disconnected")
    finally:
        debug_emitter.remove_listener(send_event)

# Application Startup

@app.on_event("startup")
async def startup_event():
    """Initialize services on startup."""
    logger.info("Starting Smart Scheduler AI Agent")
    logger.info(f"Frontend URL: {settings.frontend_url}")
    logger.info(f"Environment: {settings.environment}")

@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown."""
    logger.info("Shutting down Smart Scheduler AI Agent")
    
    # Close all Deepgram sessions
    for session_id in list(deepgram_manager.sessions.keys()):
        await deepgram_manager.end_session(session_id)

if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.environment == "development",
        log_level="info"
    )
