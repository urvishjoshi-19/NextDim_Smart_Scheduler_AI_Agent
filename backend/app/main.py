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
    allow_origins=[settings.frontend_url, "http://localhost:3000"],
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


# ============================================================================
# OAuth 2.0 Authentication Endpoints
# ============================================================================

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
async def auth_callback(code: str, state: str):
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
        
        # Redirect to frontend with success
        return RedirectResponse(
            url=f"{settings.frontend_url}/chat?auth=success&user_id={user_id}"
        )
    
    except Exception as e:
        logger.error(f"Error in OAuth callback: {e}")
        return RedirectResponse(
            url=f"{settings.frontend_url}?auth=error&message={str(e)}"
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


# ============================================================================
# WebSocket Voice Interface
# ============================================================================

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
    
    # ============================================================================
    # LOAD CALENDAR CONTEXT FOR SESSION (before greeting)
    # ============================================================================
    # Load calendar events (-20 to +20 days, IST) ONCE at session start
    # This gives the LLM full calendar awareness for intelligent scheduling
    logger.info("⏳ Loading calendar context for new session...")
    state = load_calendar_context(state)
    logger.info(f"✅ Session initialized with calendar context ({len(state.get('calendar_events_raw', []))} events)")
    # ============================================================================
    
    active_sessions[session_id] = state
    user_sessions[session_id] = user_id
    
    # Accumulated transcript buffer (only send to agent when user clicks Stop)
    transcript_buffer = ""
    is_currently_speaking = False  # Track if user is actively speaking
    
    # Deepgram callbacks
    async def on_transcript(text: str, is_final: bool):
        """Handle transcript from Deepgram."""
        nonlocal transcript_buffer, is_currently_speaking
        
        if is_final:
            # Final transcript segment - add to buffer but DON'T process yet
            if text.strip():  # Only add non-empty segments
                if transcript_buffer:
                    transcript_buffer += " " + text
                else:
                    transcript_buffer = text
                
                full_text = transcript_buffer.strip()
                
                if full_text:
                    logger.info(f"Transcript segment: {text}")
                    is_currently_speaking = True
                    
                    # Send transcript to user for display (but don't process with agent yet)
                    await websocket.send_json({
                        "type": "transcript",
                        "text": full_text,
                        "is_final": True
                    })
                    
                    # NOTE: We do NOT call process_with_agent here!
                    # Wait for user to click "Stop Speaking"
        else:
            # Interim transcript - just display, don't add to buffer
            current_display = (transcript_buffer + " " + text).strip()
            if current_display:
                await websocket.send_json({
                    "type": "transcript",
                    "text": current_display,
                    "is_final": False
                })
    
    async def on_error(error: str):
        """Handle Deepgram errors."""
        logger.error(f"Deepgram error: {error}")
        await websocket.send_json({
            "type": "error",
            "message": f"Speech recognition error: {error}"
        })
    
    # Start Deepgram session
    deepgram_client = await deepgram_manager.create_session(
        session_id=session_id,
        on_transcript=on_transcript,
        on_error=on_error
    )
    
    # Track connection health
    last_audio_sent = None
    connection_check_interval = 0
    
    async def check_and_reconnect_if_needed():
        """Check if Deepgram connection is healthy and reconnect if needed."""
        nonlocal deepgram_client
        
        if not deepgram_client.is_healthy:
            logger.warning("⚠️ Deepgram connection lost - attempting to reconnect...")
            await websocket.send_json({
                "type": "log",
                "level": "warning",
                "message": "🔄 Reconnecting to speech recognition service..."
            })
            
            try:
                # End old session
                await deepgram_manager.end_session(session_id)
                
                # Create new session with same callbacks
                deepgram_client = await deepgram_manager.create_session(
                    session_id=session_id,
                    on_transcript=on_transcript,
                    on_error=on_error
                )
                
                logger.info("✅ Deepgram connection restored")
                await websocket.send_json({
                    "type": "log",
                    "level": "success",
                    "message": "✅ Speech recognition reconnected successfully"
                })
            except Exception as e:
                logger.error(f"Failed to reconnect Deepgram: {e}")
                await websocket.send_json({
                    "type": "error",
                    "message": "Speech recognition connection failed. Please refresh the page."
                })
    
    try:
        # Prepare welcome message (but wait for frontend to be ready)
        welcome_text = "Hello! I'm your scheduling assistant. How can I help you schedule a meeting today?"
        greeting_sent = False
        
        # Main WebSocket loop
        while True:
            # Receive message
            data = await websocket.receive()
            
            if "bytes" in data:
                # Audio data from client
                audio_data = data["bytes"]
                
                # Check connection health before sending (reconnect if needed)
                await check_and_reconnect_if_needed()
                
                # Send audio to Deepgram
                await deepgram_client.send_audio(audio_data)
            
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
                            
                            # Then send audio
                            await send_voice_response(websocket, welcome_text)
                            logger.info("✅ Greeting audio sent successfully")
                            
                            greeting_sent = True
                        except Exception as e:
                            logger.error(f"❌ Error sending greeting: {e}")
                            await websocket.send_json({
                                "type": "error",
                                "message": "Failed to send greeting"
                            })
                elif message.get("type") == "stop_speaking":
                    # User released spacebar - process accumulated transcript
                    final_transcript = transcript_buffer.strip()
                    if final_transcript:
                        logger.info(f"Processing complete transcript: {final_transcript}")
                        
                        # Send confirmation that we're processing
                        await websocket.send_json({
                            "type": "transcript_processing",
                            "text": final_transcript
                        })
                        
                        # Process with agent
                        await process_with_agent(websocket, session_id, final_transcript)
                        
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
            
            # Then send voice response
            await send_voice_response(websocket, agent_response)
        else:
            # No response found - send status
            await websocket.send_json({
                "type": "status",
                "status": "idle"
            })
        
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
    try:
        # Send audio start indicator (text response already sent in process_with_agent)
        await websocket.send_json({
            "type": "audio_start",
            "format": "pcm16",
            "sample_rate": 16000
        })
        
        await websocket.send_json({
            "type": "log",
            "level": "info",
            "message": f"🎙️ Starting TTS synthesis: {text[:30]}..."
        })
        
        logger.debug(f"Starting streaming TTS for: {text[:50]}...")
        
        # Stream audio chunks as they arrive from Deepgram Aura
        chunk_count = 0
        try:
            async for audio_chunk in deepgram_tts_manager.synthesize_streaming(text):
                chunk_count += 1
                
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
            
            logger.debug(f"Streamed {chunk_count} audio chunks for response")
            await websocket.send_json({
                "type": "log",
                "level": "success",
                "message": f"🔊 Audio streaming complete ({chunk_count} chunks)"
            })
        
        except Exception as streaming_error:
            # Fallback to Google TTS if Deepgram fails
            logger.warning(f"Deepgram streaming failed, falling back to Google TTS: {streaming_error}")
            
            import base64
            audio_bytes = await asyncio.to_thread(
                tts_manager.client.synthesize_speech,
                text
            )
            audio_base64 = base64.b64encode(audio_bytes).decode('utf-8')
            
            await websocket.send_json({
                "type": "audio",
                "audio": audio_base64,
                "format": "pcm16",
                "fallback": True
            })
        
        # Send audio end indicator
        await websocket.send_json({
            "type": "audio_end"
        })
    
    except (WebSocketDisconnect, RuntimeError) as e:
        # Client disconnected while sending - this is normal, just log it
        logger.info(f"Client disconnected during voice response: {e}")
        # Don't try to send error message - connection is closed
    
    except Exception as e:
        logger.error(f"Error sending voice response: {e}")
        # Try to send error message, but don't fail if connection is closed
        try:
            await websocket.send_json({
                "type": "error",
                "message": "Failed to generate voice response"
            })
        except (WebSocketDisconnect, RuntimeError):
            # Connection already closed, can't send error message
            pass


# ============================================================================
# REST API Endpoints (for testing without voice)
# ============================================================================

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


# ============================================================================
# Debug Dashboard
# ============================================================================

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


# ============================================================================
# Application Startup
# ============================================================================

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
