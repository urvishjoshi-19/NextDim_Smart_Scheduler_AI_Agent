"""
LangGraph agent nodes - the core functions that make decisions and take actions.
Each node is a function that processes the state and returns updated state.
"""

from typing import Dict, Any, Optional
from datetime import datetime, timedelta
import json
import pytz
from dateutil import parser

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

from .state import SchedulerState
from .prompts import (
    SYSTEM_PROMPT,
    INTENT_ANALYSIS_PROMPT,
    CALENDAR_QUERY_PROMPT,
    SUGGESTION_PROMPT,
    CONFLICT_RESOLUTION_PROMPT,
    CONFIRMATION_PROMPT
)
from ..tools.calendar import GoogleCalendarTool
from ..tools.time_parser import TimeParser, extract_time_components
from ..tools.timezone import TimezoneManager
from ..tools.validation import EdgeCaseValidator
from ..auth.oauth import oauth_manager
from ..utils.config import settings
from ..utils.logger import logger
from ..utils.time_utils import TimeFormat, convert_to_24hr, convert_to_12hr, validate_time
from ..utils.debug_events import (
    emit_node_enter, emit_node_exit, emit_error, emit_message,
    emit_raw_calendar_data, emit_deduction
)


# Initialize Gemini LLM
llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    google_api_key=settings.gemini_api_key,
    temperature=0.3
)


# ============================================================================
# SESSION CALENDAR CONTEXT FUNCTIONS
# ============================================================================

def format_events_for_llm(events: list, timezone_str: str = "Asia/Kolkata") -> str:
    """
    Format calendar events in a human-readable format for LLM context.
    All times are displayed in IST (Indian Standard Time).
    
    Args:
        events: List of Google Calendar event dictionaries
        timezone_str: Timezone string (default: IST)
    
    Returns:
        Formatted string of events for LLM
    """
    if not events:
        return "No events found in this time range"
    
    ist_tz = pytz.timezone("Asia/Kolkata")  # Always use IST
    formatted_events = []
    
    for event in events:
        summary = event.get('summary', 'Untitled Event')
        
        # Parse start time
        try:
            if 'dateTime' in event.get('start', {}):
                # Event with specific time
                start_dt = datetime.fromisoformat(event['start']['dateTime'].replace('Z', '+00:00'))
                # Convert to IST
                start_ist = start_dt.astimezone(ist_tz)
                
                # Format: "Event Name: Monday, November 18, 2025 at 09:00 AM IST"
                start_str = start_ist.strftime('%A, %B %d, %Y at %I:%M %p IST')
                
            elif 'date' in event.get('start', {}):
                # All-day event
                start_date = datetime.fromisoformat(event['start']['date'])
                start_str = start_date.strftime('%A, %B %d, %Y (all-day)')
            else:
                start_str = "Unknown time"
            
            formatted_events.append(f"- {summary}: {start_str}")
            
        except Exception as e:
            logger.warning(f"Could not format event '{summary}': {e}")
            formatted_events.append(f"- {summary}: (time parsing error)")
    
    return "\n".join(formatted_events)


def load_calendar_context(state: SchedulerState) -> SchedulerState:
    """
    Load Google Calendar context for the entire session.
    Queries calendar for -20 to +20 days from current date (IST).
    
    This function is called ONCE at session initialization, before the greeting.
    All times are handled in IST (Indian Standard Time).
    
    Args:
        state: Current scheduler state
    
    Returns:
        Updated state with calendar context loaded
    """
    logger.info("=" * 80)
    logger.info("🗓️  LOADING SESSION CALENDAR CONTEXT")
    logger.info("=" * 80)
    
    try:
        # Load user credentials
        credentials = oauth_manager.load_credentials(state["user_id"])
        calendar = GoogleCalendarTool(credentials)
        
        # Get current time in IST (Indian Standard Time)
        ist_tz = pytz.timezone("Asia/Kolkata")
        now_ist = datetime.now(ist_tz)
        
        # Query range: -20 to +20 days from now (in IST)
        start_time = now_ist - timedelta(days=20)
        end_time = now_ist + timedelta(days=20)
        
        logger.info(f"📅 Calendar Query Range (IST):")
        logger.info(f"   Start: {start_time.strftime('%A, %B %d, %Y %I:%M %p IST')}")
        logger.info(f"   End:   {end_time.strftime('%A, %B %d, %Y %I:%M %p IST')}")
        logger.info(f"   Max Events: 100")
        
        # Query Google Calendar
        events = calendar.list_events(
            start_time=start_time,
            end_time=end_time,
            max_results=100
        )
        
        if events:
            logger.info(f"✅ Retrieved {len(events)} events from Google Calendar")
            
            # Format events for LLM (human-readable)
            formatted_events = format_events_for_llm(events, "Asia/Kolkata")
            
            # Store in state
            state["calendar_context"] = formatted_events
            state["calendar_events_raw"] = events
            state["calendar_loaded"] = True
            state["calendar_date_range"] = {
                "start": start_time.isoformat(),
                "end": end_time.isoformat(),
                "timezone": "Asia/Kolkata"
            }
            
            logger.info(f"✅ Calendar context loaded successfully")
            logger.info(f"📊 Events by date:")
            
            # Log summary by date for debugging
            events_by_date = {}
            for event in events:
                try:
                    if 'dateTime' in event.get('start', {}):
                        start_dt = datetime.fromisoformat(event['start']['dateTime'].replace('Z', '+00:00'))
                        start_ist = start_dt.astimezone(ist_tz)
                        date_key = start_ist.strftime('%Y-%m-%d')
                    elif 'date' in event.get('start', {}):
                        date_key = event['start']['date']
                    else:
                        date_key = "unknown"
                    
                    if date_key not in events_by_date:
                        events_by_date[date_key] = []
                    events_by_date[date_key].append(event.get('summary', 'Untitled'))
                except:
                    pass
            
            for date in sorted(events_by_date.keys())[:5]:  # Show first 5 days
                logger.info(f"   {date}: {len(events_by_date[date])} event(s)")
            
            emit_deduction(
                source="Session Calendar Context Loaded",
                reasoning=f"Loaded {len(events)} calendar events for session (IST: {start_time.strftime('%Y-%m-%d')} to {end_time.strftime('%Y-%m-%d')}). LLM now has full calendar awareness for intelligent date resolution.",
                data={
                    "events_count": len(events),
                    "date_range_start": start_time.isoformat(),
                    "date_range_end": end_time.isoformat(),
                    "timezone": "Asia/Kolkata",
                    "events_by_date_sample": dict(list(events_by_date.items())[:5])
                }
            )
            
        else:
            logger.info("ℹ️  No events found in the specified range")
            state["calendar_context"] = f"No events scheduled between {start_time.strftime('%B %d')} and {end_time.strftime('%B %d, %Y')} (IST)"
            state["calendar_events_raw"] = []
            state["calendar_loaded"] = True
            state["calendar_date_range"] = {
                "start": start_time.isoformat(),
                "end": end_time.isoformat(),
                "timezone": "Asia/Kolkata"
            }
        
        logger.info("=" * 80)
        return state
        
    except Exception as e:
        logger.error(f"❌ Failed to load calendar context: {e}")
        logger.error(f"   Error type: {type(e).__name__}")
        logger.error(f"   Error details: {str(e)}")
        
        state["calendar_context"] = "Calendar temporarily unavailable"
        state["calendar_events_raw"] = []
        state["calendar_loaded"] = False
        state["calendar_date_range"] = None
        
        emit_error({
            "error_type": "CalendarLoadError",
            "message": str(e),
            "user_id": state["user_id"]
        })
        
        logger.info("=" * 80)
        return state


def refresh_calendar_context(state: SchedulerState) -> SchedulerState:
    """
    Refresh calendar context after booking a new event.
    This ensures the LLM sees the newly created event.
    
    Args:
        state: Current scheduler state
    
    Returns:
        Updated state with refreshed calendar context
    """
    logger.info("🔄 Refreshing calendar context after booking...")
    return load_calendar_context(state)


def detect_reference_query_pattern(message: str) -> bool:
    """
    Detect if a message contains reference query patterns.
    Returns True if patterns like "before my", "after the", event names in quotes are found.
    """
    import re
    
    message_lower = message.lower()
    
    logger.info(f"🔍 Checking reference pattern for: '{message}'")
    
    # Check for time-based reference patterns
    if re.search(r'\b(before|after)\s+(my|the)\s+\d', message_lower):
        logger.info("✅ Matched time-based reference pattern")
        return True
    
    # Check for named event patterns (quotes)
    if re.search(r'(before|after)\s+(the|my)?\s*[\'"]', message_lower):
        logger.info("✅ Matched quoted event pattern")
        return True
    
    # Check for day-offset patterns with event names
    if re.search(r'(a\s+day|days?|the\s+day)\s+(before|after)\s+(the|my)', message_lower):
        logger.info("✅ Matched day-offset pattern")
        return True
    
    # Check for capitalized event name patterns
    if re.search(r'(before|after)\s+(the|my)\s+[A-Z][a-z]+\s+(Kick-?off|Meeting|Call|Conference|Session)', message):
        logger.info("✅ Matched capitalized event name pattern")
        return True
    
    logger.info("❌ No reference pattern matched")
    return False


def detect_recurring_meeting_pattern(message: str) -> Optional[str]:
    """
    Detect if user is referring to a recurring/usual meeting type.
    Returns the meeting keyword if detected, None otherwise.
    """
    import re
    
    message_lower = message.lower()
    
    # Patterns for "usual" meetings
    patterns = [
        (r'(?:usual|regular|our|my)\s+(\w+(?:\s+\w+)?)', 1),  # "usual sync-up", "our standup"
        (r'(\w+(?:\s+\w+)?)\s+(?:like usual|as usual)', 1),  # "sync-up like usual"
        (r'schedule (?:a|the) (\w+(?:\s+\w+)?)', 1),  # "schedule a sync-up"
    ]
    
    for pattern, group in patterns:
        match = re.search(pattern, message_lower)
        if match:
            keyword = match.group(group).strip()
            # Common meeting types that make sense to analyze
            if keyword in ['sync-up', 'sync up', 'syncup', 'synch-up', 'standup', 'stand-up', 
                          '1-on-1', 'one-on-one', 'check-in', 'checkin', 'review', 
                          'weekly', 'daily', 'team meeting', 'status update']:
                return keyword
    
    return None


def extract_requirements(state: SchedulerState) -> SchedulerState:
    """
    Extract meeting requirements from user input using LLM-based intent analysis.
    LLM decides what to keep/change based on conversation context.
    """
    logger.info("Node: extract_requirements (LLM-first architecture)")
    emit_node_enter("extract", state)
    
    try:
        # Get latest user message
        messages = state["messages"]
        if not messages:
            return state
        
        latest_message = messages[-1]["content"]
        
        # ============================================================================
        # SOFT RESET: Post-Confirmation Context Management
        # ============================================================================
        # If a previous booking was completed and user is starting a new conversation,
        # give the LLM clear context that this is a fresh booking request.
        # This ONLY activates after a booking is confirmed and won't affect in-progress bookings.
        if state.get("conversation_phase") == "post_confirmation":
            logger.info("🔄 SOFT RESET: Previous booking completed. Preparing context for fresh booking.")
            emit_deduction(
                source="Soft Reset (Post-Confirmation)",
                reasoning=f"A previous booking was completed. Marking this as a fresh start so the LLM doesn't confuse it with the previous booking context. Last booking: {state.get('last_completed_booking', {}).get('title', 'N/A')} on {state.get('last_completed_booking', {}).get('date', 'N/A')}",
                data={
                    "last_completed_booking": state.get("last_completed_booking"),
                    "new_message": latest_message,
                    "conversation_phase_before": "post_confirmation",
                    "conversation_phase_after": "active_booking"
                }
            )
            
            # Reset booking state for fresh start (keep history but clear parameters)
            state["meeting_duration_minutes"] = None
            state["preferred_date"] = None
            state["original_requested_date"] = None
            state["preferred_time"] = None
            state["time_preference"] = None
            state["meeting_title"] = None
            state["meeting_description"] = None
            state["available_slots"] = None
            state["conflicting_events"] = None
            state["ready_to_book"] = False
            state["booking_confirmed"] = False  # Clear the booking confirmation flag
            state["confirmed"] = False
            state["needs_clarification"] = False
            state["clarification_question"] = None
            state["awaiting_title_input"] = False
            
            # Reset reference query flags
            state["is_reference_query"] = False
            state["reference_event_name"] = None
            state["reference_event_time"] = None
            state["reference_event_details"] = None
            state["time_relation"] = None
            
            # Reset constraints (Test 3.4)
            state["negative_days"] = None
            state["earliest_time"] = None
            state["latest_time"] = None
            state["multi_day_search"] = False
            state["date_range_start"] = None
            state["date_range_end"] = None
            
            # Mark phase as active_booking (soft reset complete)
            state["conversation_phase"] = "active_booking"
            
            # Add a subtle context note for the LLM (not shown to user)
            # This helps the LLM understand that a previous booking was completed
            last_booking = state.get("last_completed_booking", {})
            soft_reset_context = f"[CONTEXT: Previous booking completed - {last_booking.get('title', 'Meeting')} on {last_booking.get('date', 'N/A')} at {last_booking.get('time', 'N/A')}. User is now starting a new booking request.]"
            
            logger.info("✅ SOFT RESET complete. Ready for fresh booking. User can still reference previous booking if needed.")
            logger.info(f"📝 Added soft reset context for LLM: {soft_reset_context}")
        # ============================================================================
        
        # ============================================================================
        # TITLE INPUT HANDLING: If we're waiting for user to provide meeting title
        # ============================================================================
        if state.get("awaiting_title_input"):
            logger.info("📝 TITLE INPUT: User is providing meeting title")
            
            # Extract title from user's message (use the entire message as title, cleaned up)
            title_input = latest_message.strip()
            
            # Simple cleanup: capitalize first letter, remove quotes if present
            if title_input.startswith('"') and title_input.endswith('"'):
                title_input = title_input[1:-1]
            if title_input.startswith("'") and title_input.endswith("'"):
                title_input = title_input[1:-1]
            
            # Capitalize first letter
            if title_input:
                title_input = title_input[0].upper() + title_input[1:]
            
            # Set the title
            state["meeting_title"] = title_input if title_input else "Meeting"
            state["awaiting_title_input"] = False
            
            logger.info(f"✅ Meeting title set to: '{state['meeting_title']}'")
            
            # Now proceed to final confirmation and booking
            state["confirmed"] = True
            state["next_action"] = "create_event"
            
            logger.info("✅ Title received - proceeding to create event")
            emit_node_exit("extract", state)
            return state
        # ============================================================================
        
        # Check for recurring meeting patterns (e.g., "usual sync-up")
        meeting_keyword = detect_recurring_meeting_pattern(latest_message)
        if meeting_keyword and not state.get("meeting_duration_minutes"):
            logger.info(f"🔍 Detected recurring meeting pattern: '{meeting_keyword}'")
            emit_deduction(
                source="Recurring Meeting Pattern Detection",
                reasoning=f"User mentioned '{meeting_keyword}' which might be a usual/recurring meeting. Will analyze past calendar events to determine typical duration.",
                data={"keyword": meeting_keyword, "message": latest_message}
            )
            
            # Try to analyze past meetings to learn the duration
            try:
                credentials = oauth_manager.load_credentials(state["user_id"])
                calendar = GoogleCalendarTool(credentials)
                learned_duration = calendar.analyze_recurring_meeting_pattern(meeting_keyword)
                
                if learned_duration:
                    state["meeting_duration_minutes"] = learned_duration
                    logger.info(f"✅ Learned duration from past meetings: {learned_duration} minutes")
                    emit_deduction(
                        source="Learned Duration from Past Meetings",
                        reasoning=f"Analyzed past '{meeting_keyword}' meetings and found the typical duration is {learned_duration} minutes. Using this as default.",
                        data={"keyword": meeting_keyword, "learned_duration": learned_duration}
                    )
                    
                    # Also set the title if not already set
                    if not state.get("meeting_title"):
                        state["meeting_title"] = meeting_keyword.title()
                else:
                    logger.info(f"ℹ️ No past pattern found for '{meeting_keyword}'")
            except Exception as e:
                logger.warning(f"Could not analyze past meetings: {e}")
        
        # Build full conversation history (last 10 messages to keep context reasonable)
        conversation_history = ""
        
        # If this is a fresh booking after a completed one, add context for LLM
        if state.get("conversation_phase") == "active_booking" and state.get("last_completed_booking"):
            last_booking = state["last_completed_booking"]
            conversation_history += f"[SYSTEM CONTEXT: Previous booking was successfully completed - {last_booking.get('title', 'Meeting')} scheduled for {last_booking.get('date', 'N/A')} at {last_booking.get('time', 'N/A')}. User is now starting a NEW booking request. Treat this as a fresh conversation.]\n\n"
        
        recent_messages = messages[-10:] if len(messages) > 10 else messages
        for msg in recent_messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            conversation_history += f"{role.capitalize()}: \"{content}\"\n"
        
        # ============================================================================
        # CALENDAR CONTEXT: Use cached calendar context from session state
        # ============================================================================
        # Calendar was loaded once at session initialization (±20 days, IST)
        calendar_events_context = state.get("calendar_context", "Calendar not loaded")
        
        if state.get("calendar_loaded"):
            date_range = state.get("calendar_date_range", {})
            logger.info(f"📅 Using cached calendar context ({len(state.get('calendar_events_raw', []))} events, IST)")
        else:
            logger.warning("⚠️ Calendar context not loaded in session state")
        # ============================================================================
        
        # Prepare context for LLM intent analysis
        # Build date context (include both specific date and date range)
        date_context = state.get("preferred_date") or "not set"
        if state.get("date_range_start") and state.get("date_range_end"):
            date_context = f"{date_context} (date range: {state.get('date_range_start')} to {state.get('date_range_end')})"
        
        # Build time context (include time preference and constraints)
        time_context = state.get("time_preference") or "not set"
        if state.get("earliest_time") or state.get("latest_time"):
            constraints = []
            if state.get("earliest_time"):
                constraints.append(f"earliest: {state.get('earliest_time')}")
            if state.get("latest_time"):
                constraints.append(f"latest: {state.get('latest_time')}")
            time_context = f"{time_context} (constraints: {', '.join(constraints)})"
        
        prompt = INTENT_ANALYSIS_PROMPT.format(
            current_duration=state.get("meeting_duration_minutes") or "not set",
            current_date=date_context,
            current_time=time_context,
            current_title=state.get("meeting_title") or "not set",
            ready_to_book=state.get("ready_to_book", False),
            confirmed=state.get("confirmed", False),
            cancelled=state.get("cancelled", False),
            cancelled_params=state.get("cancelled_params") or "none",
            calendar_events=calendar_events_context,
            conversation_history=conversation_history.strip(),
            user_message=latest_message
        )
        
        logger.info("Asking LLM to analyze user intent with full conversation context...")
        
        emit_deduction(
            source="LLM Intent Analysis",
            reasoning=f"Analyzing user message '{latest_message}' with {len(recent_messages)} messages of conversation history for better context understanding.",
            data={"conversation_history": conversation_history, "latest_message": latest_message, "history_length": len(recent_messages)}
        )
        
        # Let LLM understand the intent
        response = llm.invoke([HumanMessage(content=prompt)])
        
        # Parse LLM's intent analysis
        try:
            # Strip markdown code fences if present (LLM often wraps JSON in ```json ... ```)
            content = response.content.strip()
            if content.startswith("```"):
                # Remove opening fence
                content = content.split("\n", 1)[1] if "\n" in content else content
                # Remove closing fence
                if content.endswith("```"):
                    content = content.rsplit("\n", 1)[0] if "\n" in content else content[:-3]
            
            intent_data = json.loads(content)
            intent = intent_data.get("intent")
            modifications = intent_data.get("modifications", {})
            
            logger.info(f"🧠 LLM Intent: {intent} - {intent_data.get('reasoning')}")
            logger.info(f"📋 LLM Modifications Decision:")
            logger.info(f"   - Duration: {modifications.get('duration', {}).get('action', 'N/A')}")
            logger.info(f"   - Date: {modifications.get('date', {}).get('action', 'N/A')}")
            logger.info(f"   - Time: {modifications.get('time', {}).get('action', 'N/A')}")
            logger.info(f"   - Title: {modifications.get('title', {}).get('action', 'N/A')}")
            
            # Log current constraint state for debugging
            logger.info(f"🔍 Current Constraint State:")
            logger.info(f"   - multi_day_search: {state.get('multi_day_search', False)}")
            logger.info(f"   - date_range: {state.get('date_range_start')} to {state.get('date_range_end')}")
            logger.info(f"   - negative_days: {state.get('negative_days', [])}")
            logger.info(f"   - earliest_time: {state.get('earliest_time')}")
            logger.info(f"   - latest_time: {state.get('latest_time')}")
            
            # Handle new_request intent - reset state for fresh booking
            if intent == "new_request":
                logger.info("🆕 Detected NEW REQUEST - Resetting state for fresh booking")
                # Reset all meeting parameters (keep user_id, timezone, messages)
                state["meeting_duration_minutes"] = None
                state["preferred_date"] = None
                state["time_preference"] = None
                state["meeting_title"] = None
                state["meeting_description"] = None
                state["available_slots"] = None
                state["ready_to_book"] = False
                state["confirmed"] = False
                state["cancelled"] = False
                state["cancelled_params"] = None
                state["next_action"] = "extract"
                # Reset reference query flags
                state["is_reference_query"] = False
                state["reference_event_details"] = None
                state["time_relation"] = None
                # Now continue to extract the new parameters below
            
            # Handle cancel intent (Test 4.5 - Cancellation and Reschedule)
            if intent == "cancel":
                logger.info("❌ Detected CANCELLATION - User wants to cancel current scheduling request")
                emit_deduction(
                    source="Cancellation Detected (Test 4.5)",
                    reasoning=f"User cancelled the scheduling request with message: '{latest_message}'. Saving current parameters in case they change their mind.",
                    data={
                        "cancelled_message": latest_message,
                        "saved_duration": state.get("meeting_duration_minutes"),
                        "saved_date": state.get("preferred_date"),
                        "saved_time": state.get("time_preference"),
                        "saved_title": state.get("meeting_title")
                    }
                )
                
                # Save current parameters before resetting
                state["cancelled_params"] = {
                    "duration": state.get("meeting_duration_minutes"),
                    "date": state.get("preferred_date"),
                    "time": state.get("time_preference"),
                    "title": state.get("meeting_title"),
                    "description": state.get("meeting_description")
                }
                
                # Reset meeting parameters but mark as cancelled
                state["meeting_duration_minutes"] = None
                state["preferred_date"] = None
                state["time_preference"] = None
                state["meeting_title"] = None
                state["meeting_description"] = None
                state["available_slots"] = None
                state["ready_to_book"] = False
                state["confirmed"] = False
                state["cancelled"] = True
                state["needs_clarification"] = False
                state["next_action"] = "respond"  # Just respond to acknowledge cancellation
                
                logger.info(f"✅ Saved cancelled parameters: duration={state['cancelled_params'].get('duration')}min, time={state['cancelled_params'].get('time')}")
                
                # Add acknowledgment message
                state["messages"].append({
                    "role": "assistant",
                    "content": "No problem."
                })
                
                emit_node_exit("extract", state)
                return state
            
            # Handle confirmation intent
            if intent == "confirm":
                # Check if duration changed during confirmation - if so, we need to re-query
                duration_mod = modifications.get("duration", {})
                if duration_mod.get("action") == "change" and duration_mod.get("new_value"):
                    # Duration changed - extract it but DON'T confirm yet
                    parsed = extract_time_components(
                        duration_mod.get("mentioned_text", latest_message),
                        timezone=state["timezone"]
                    )
                    if parsed.get("duration_minutes"):
                        new_duration = parsed["duration_minutes"]
                        old_duration = state.get("meeting_duration_minutes")
                        if new_duration != old_duration:
                            logger.info(f"🔄 Duration changed during confirmation: {old_duration} → {new_duration} minutes")
                            logger.info(f"⏭️ Will re-query calendar with new duration instead of confirming")
                            logger.info(f"⚠️ TEST 4.3 SCENARIO: User changed duration AFTER selecting time - must re-validate extended slot")
                            
                            # Emit specific deduction for Test 4.3
                            emit_deduction(
                                source="Test 4.3 - Duration Change During Confirmation",
                                reasoning=f"User changed meeting duration from {old_duration} to {new_duration} minutes after a time was selected. Must re-query calendar to verify the extended time slot is still available before confirming.",
                                data={
                                    "old_duration": old_duration,
                                    "new_duration": new_duration,
                                    "selected_time": state.get("time_preference"),
                                    "selected_date": state.get("preferred_date"),
                                    "action": "Will re-query calendar instead of confirming"
                                }
                            )
                            
                            # Don't set confirmed=True, fall through to parameter change handling below
                            intent = "modify"  # Change intent to prevent immediate confirmation
                
                # Check if user specified a particular time in their confirmation
                time_mod = modifications.get("time", {})
                if time_mod.get("action") == "change" and time_mod.get("new_value") and intent == "confirm":
                    confirmed_time = time_mod.get("new_value")
                    state["time_preference"] = confirmed_time
                    logger.info(f"Time confirmed to: {confirmed_time}")
                    
                    # Filter available slots to match the confirmed time
                    slots = state.get("available_slots", [])
                    if slots and confirmed_time:
                        # Parse confirmed hour and minute (handle AM/PM format like 5PM, 5:00PM, 17:00, etc.)
                        try:
                            import re
                            # Remove extra spaces and normalize
                            time_str = confirmed_time.strip().upper()
                            
                            # Extract hour, minute, and AM/PM - supports formats like 5PM, 5:00PM, 17:00
                            match = re.match(r'(\d{1,2}):?(\d{2})?\s*(AM|PM)?', time_str)
                            if match:
                                confirmed_hour = int(match.group(1))
                                confirmed_minute = int(match.group(2)) if match.group(2) else 0
                                am_pm = match.group(3)
                                
                                # Convert to 24-hour format
                                if am_pm == 'PM' and confirmed_hour != 12:
                                    confirmed_hour += 12
                                elif am_pm == 'AM' and confirmed_hour == 12:
                                    confirmed_hour = 0
                                
                                logger.info(f"🕐 Parsed confirmation time: {confirmed_time} → {confirmed_hour}:{confirmed_minute:02d}")
                                
                                # Find matching slot (exact match)
                                matching_slots = []
                                for slot in slots:
                                    slot_time = datetime.fromisoformat(slot['start'])
                                    if slot_time.hour == confirmed_hour and slot_time.minute == confirmed_minute:
                                        matching_slots.append(slot)
                                
                                if matching_slots:
                                    state["available_slots"] = matching_slots
                                    logger.info(f"✅ EXACT MATCH - Filtered to matching slot: {matching_slots[0]['start_formatted']}")
                                else:
                                    # Try fuzzy match (within 15 minutes)
                                    logger.warning(f"⚠️ No EXACT match for {confirmed_hour}:{confirmed_minute:02d}")
                                    
                                    fuzzy_slots = []
                                    slot_times_debug = []
                                    for slot in slots:
                                        slot_time = datetime.fromisoformat(slot['start'])
                                        slot_times_debug.append(slot_time.strftime('%H:%M'))
                                        
                                        # Fuzzy match: within 15 minutes
                                        slot_total_mins = slot_time.hour * 60 + slot_time.minute
                                        confirmed_total_mins = confirmed_hour * 60 + confirmed_minute
                                        if abs(slot_total_mins - confirmed_total_mins) <= 15:
                                            fuzzy_slots.append((slot, abs(slot_total_mins - confirmed_total_mins)))
                                    
                                    logger.warning(f"   Available slot times: {slot_times_debug}")
                                    logger.warning(f"   Trying fuzzy match (±15 min)...")
                                    
                                    if fuzzy_slots:
                                        # Sort by closest time difference
                                        fuzzy_slots.sort(key=lambda x: x[1])
                                        
                                        # DON'T auto-select - ask user to confirm the nearby time
                                        nearest_slots = [slot for slot, dist in fuzzy_slots[:3]]  # Top 3 closest
                                        
                                        # Format alternatives for user (TTS-friendly, no formatting)
                                        alternatives = []
                                        for slot in nearest_slots:
                                            slot_dt = datetime.fromisoformat(slot['start'])
                                            time_str = slot_dt.strftime('%I:%M %p').lstrip('0').replace(':00', '')
                                            alternatives.append(time_str)
                                        
                                        # Format time naturally for TTS
                                        hour_12 = confirmed_hour if confirmed_hour <= 12 else confirmed_hour - 12
                                        if hour_12 == 0:
                                            hour_12 = 12
                                        am_pm = 'AM' if confirmed_hour < 12 else 'PM'
                                        time_spoken = f"{hour_12} {am_pm}" if confirmed_minute == 0 else f"{hour_12} {confirmed_minute:02d} {am_pm}"
                                        
                                        # Join alternatives naturally
                                        if len(alternatives) == 2:
                                            alt_text = f"{alternatives[0]} or {alternatives[1]}"
                                        else:
                                            alt_text = ', '.join(alternatives[:-1]) + f", or {alternatives[-1]}"
                                        
                                        response = f"That time isn't available, but I have {alt_text}. Would any of those work?"
                                        
                                        logger.warning(f"Fuzzy match found but asking user to confirm (no auto-select)")
                                        
                                        state["messages"].append({
                                            "role": "assistant",
                                            "content": response
                                        })
                                        
                                        emit_message("assistant", response)
                                        
                                        # Keep the nearby slots for next iteration
                                        state["available_slots"] = nearest_slots
                                        
                                        # Stay in conversation, don't proceed to booking
                                        state["confirmed"] = False
                                        state["awaiting_title_input"] = False
                                        state["next_action"] = "extract"
                                        
                                        logger.info("✅ Presented fuzzy matches to user, waiting for explicit confirmation")
                                        emit_node_exit("extract", state)
                                        return state
                                    else:
                                        # No match found - ask user to choose from available slots
                                        logger.warning(f"❌ No fuzzy match either. Asking user to select from available slots.")
                                        
                                        # Format available times for display (TTS-friendly)
                                        available_times = []
                                        for slot in slots[:5]:  # Show first 5 slots
                                            slot_dt = datetime.fromisoformat(slot['start'])
                                            time_str = slot_dt.strftime('%I:%M %p').lstrip('0').replace(':00', '')
                                            available_times.append(time_str)
                                        
                                        # Format time naturally for TTS  
                                        hour_12 = confirmed_hour if confirmed_hour <= 12 else confirmed_hour - 12
                                        if hour_12 == 0:
                                            hour_12 = 12
                                        
                                        # Join alternatives naturally
                                        if len(available_times) == 2:
                                            times_text = f"{available_times[0]} or {available_times[1]}"
                                        else:
                                            times_text = ', '.join(available_times[:-1]) + f", or {available_times[-1]}"
                                        
                                        response = f"That time isn't available. I have {times_text}. Which would you prefer?"
                                        
                                        state["messages"].append({
                                            "role": "assistant",
                                            "content": response
                                        })
                                        
                                        emit_message("assistant", response)
                                        
                                        # Stay in conversation, don't proceed to booking
                                        state["confirmed"] = False
                                        state["next_action"] = "extract"
                                        
                                        logger.info("✅ Asked user to choose from available times")
                                        emit_node_exit("extract", state)
                                        return state
                            else:
                                logger.warning(f"⚠️ Could not parse time format: {confirmed_time}")
                        except Exception as e:
                            logger.error(f"❌ CRITICAL: Could not filter slots by confirmed time: {e}")
                            import traceback
                            logger.error(f"Exception details: {traceback.format_exc()}")
                            
                            # ALWAYS ask user to select from available slots when error occurs
                            if slots:
                                available_times = []
                                for slot in slots[:5]:
                                    try:
                                        slot_dt = datetime.fromisoformat(slot['start'])
                                        time_str = slot_dt.strftime('%I:%M %p')
                                        available_times.append(f"**{time_str}**")
                                    except Exception as format_error:
                                        logger.error(f"Error formatting slot: {format_error}")
                                        # Fallback: just show the raw start time
                                        available_times.append(f"**{slot.get('start_formatted', 'Available slot')}**")
                                
                                # Build response with available times
                                if available_times:
                                    response = (
                                        f"I found some available times: {', '.join(available_times)}. "
                                        f"Which one works best for you?"
                                    )
                                else:
                                    response = "I found some available slots. Which time would you prefer?"
                                
                                state["messages"].append({
                                    "role": "assistant",
                                    "content": response
                                })
                                
                                emit_message("assistant", response)
                                
                                # CRITICAL: Stay in conversation, don't proceed to booking
                                state["confirmed"] = False
                                state["awaiting_title_input"] = False  # Reset title flag
                                state["next_action"] = "extract"
                                
                                logger.info("✅ Error occurred, asked user to choose from available times - BLOCKING BOOKING")
                                emit_node_exit("extract", state)
                                return state
                            else:
                                # No slots available at all
                                response = "I couldn't find any available slots. Could you try a different date or time?"
                                state["messages"].append({
                                    "role": "assistant",
                                    "content": response
                                })
                                emit_message("assistant", response)
                                state["confirmed"] = False
                                state["awaiting_title_input"] = False
                                state["next_action"] = "extract"
                                emit_node_exit("extract", state)
                                return state
                
                # Only confirm if intent is still "confirm" (not changed to "modify" due to duration change)
                if intent == "confirm":
                    # ============================================================================
                    # TITLE CONFIRMATION: Ask for meeting title before final booking
                    # ============================================================================
                    # ALWAYS ask for custom title at confirmation step (unless we already asked)
                    # This ensures user explicitly names the meeting, even if LLM auto-extracted a title
                    
                    # Only skip asking if we already went through the title input flow
                    if not state.get("awaiting_title_input"):
                        logger.info("📝 TITLE CONFIRMATION: Asking user for meeting title before final booking")
                        
                        # Get the confirmed slot details for context - use actual slot time, not time_preference
                        slots = state.get("available_slots", [])
                        if slots:
                            # Use the actual formatted time from the selected slot
                            confirmed_time = slots[0]['start_formatted']
                            confirmed_date = slots[0]['date_formatted']
                            formatted_date = confirmed_date
                            logger.info(f"✅ Using actual slot time for confirmation: {confirmed_time} on {confirmed_date}")
                        else:
                            # Fallback to state values if no slots available
                            confirmed_time = state.get("time_preference", "the selected time")
                            confirmed_date = state.get("preferred_date", "the selected date")
                            duration = state.get("meeting_duration_minutes", "")
                            
                            # Format date nicely if available
                            if confirmed_date:
                                try:
                                    date_obj = datetime.fromisoformat(confirmed_date)
                                    formatted_date = date_obj.strftime("%A, %B %d")
                                except:
                                    formatted_date = confirmed_date
                            else:
                                formatted_date = "the selected date"
                            logger.warning(f"⚠️ No slots available, using state time_preference: {confirmed_time}")
                        
                        # Ask user for title with context (TTS-friendly)
                        title_question = f"Great, I can book that for {confirmed_time} on {formatted_date}. What would you like to call this meeting?"
                        
                        state["messages"].append({
                            "role": "assistant",
                            "content": title_question
                        })
                        
                        # Emit the message so it's sent to the user
                        emit_message("assistant", title_question)
                        
                        # Set flag to indicate we're waiting for title
                        state["awaiting_title_input"] = True
                        state["next_action"] = "extract"  # Stay in extract to process their response
                        
                        logger.info("✅ Asked for meeting title. Waiting for user response.")
                        emit_node_exit("extract", state)
                        return state
                    # ============================================================================
                    
                    state["confirmed"] = True
                    state["next_action"] = "create_event"
                    logger.info("✅ User confirmed - proceeding to create event")
                    emit_node_exit("extract", state)
                    return state
            
            # Track if any critical parameters changed (for re-querying logic)
            parameters_changed = False
            duration_changed = False
            old_duration = state.get("meeting_duration_minutes")
            old_date = state.get("preferred_date")
            old_time = state.get("time_preference")
            
            # Handle restoration of cancelled parameters (Test 4.5 - Reschedule after cancellation)
            if state.get("cancelled") and state.get("cancelled_params"):
                logger.info("🔄 Restoring from cancellation - checking for 'restore' actions")
                emit_deduction(
                    source="Reschedule After Cancellation (Test 4.5)",
                    reasoning=f"User wants to reschedule after cancelling. Will restore saved parameters where action='restore' and apply new changes where action='change'.",
                    data={
                        "cancelled_params": state.get("cancelled_params"),
                        "modifications": modifications
                    }
                )
                
                # Restore parameters where action is "restore"
                if modifications.get("duration", {}).get("action") == "restore":
                    restored_duration = state["cancelled_params"].get("duration")
                    if restored_duration:
                        state["meeting_duration_minutes"] = restored_duration
                        logger.info(f"♻️  Restored duration from cancellation: {restored_duration} minutes")
                
                if modifications.get("time", {}).get("action") == "restore":
                    restored_time = state["cancelled_params"].get("time")
                    if restored_time:
                        state["time_preference"] = restored_time
                        logger.info(f"♻️  Restored time from cancellation: {restored_time}")
                
                if modifications.get("title", {}).get("action") == "restore":
                    restored_title = state["cancelled_params"].get("title")
                    if restored_title:
                        state["meeting_title"] = restored_title
                        logger.info(f"♻️  Restored title from cancellation: {restored_title}")
                
                # Mark as no longer cancelled since we're resuming scheduling
                state["cancelled"] = False
                logger.info("✅ Unmarked cancelled flag - resuming scheduling")
            
            # Apply modifications based on LLM's understanding
            # Duration
            if modifications.get("duration", {}).get("action") == "change":
                new_duration_text = modifications["duration"].get("new_value")
                mentioned_text = modifications["duration"].get("mentioned_text", latest_message)
                
                logger.info(f"🔍 Duration modification detected:")
                logger.info(f"   LLM new_value: '{new_duration_text}'")
                logger.info(f"   LLM mentioned_text: '{mentioned_text}'")
                logger.info(f"   Current duration: {old_duration} minutes")
                
                if new_duration_text:
                    # Use Python parser to extract the actual number
                    parsed = extract_time_components(
                        mentioned_text,
                        timezone=state["timezone"]
                    )
                    
                    logger.info(f"   Parser result: {parsed.get('duration_minutes')} minutes")
                    
                    new_duration = None
                    
                    if parsed.get("duration_minutes"):
                        # Parser succeeded
                        new_duration = parsed["duration_minutes"]
                    else:
                        # Parser failed - try to use LLM's extracted numeric value as fallback
                        logger.warning(f"⚠️ Parser failed to extract duration from: '{mentioned_text}'")
                        logger.info(f"🔄 Attempting fallback: Using LLM's extracted value: '{new_duration_text}'")
                        
                        try:
                            # Try to convert LLM's new_value to integer
                            # LLM might return "60", "65", etc. as strings or with units
                            cleaned_value = re.sub(r'[^\d]', '', new_duration_text)
                            if cleaned_value:
                                new_duration = int(cleaned_value)
                                logger.info(f"✅ Fallback SUCCESS: Extracted {new_duration} minutes from LLM value")
                                emit_deduction(
                                    source="Duration Extraction (LLM Fallback)",
                                    reasoning=f"Parser couldn't extract duration from '{mentioned_text}', but LLM provided numeric value '{new_duration_text}'. Using {new_duration} minutes.",
                                    data={
                                        "mentioned_text": mentioned_text,
                                        "llm_new_value": new_duration_text,
                                        "fallback_duration": new_duration
                                    }
                                )
                        except (ValueError, TypeError) as e:
                            logger.error(f"❌ Fallback FAILED: Could not convert LLM value '{new_duration_text}' to integer: {e}")
                            emit_deduction(
                                source="Duration Parsing FAILED",
                                reasoning=f"Both parser and fallback failed. Parser couldn't extract from '{mentioned_text}', and LLM value '{new_duration_text}' couldn't be converted to integer.",
                                data={
                                    "mentioned_text": mentioned_text,
                                    "llm_new_value": new_duration_text,
                                    "parser_result": parsed,
                                    "user_message": latest_message,
                                    "error": str(e)
                                }
                            )
                    
                    # Apply the duration if we successfully got a value
                    if new_duration:
                        if new_duration != old_duration:
                            state["meeting_duration_minutes"] = new_duration
                            parameters_changed = True
                            duration_changed = True
                            logger.info(f"✅ Duration CHANGED: {old_duration} → {new_duration} minutes")
                            
                            emit_deduction(
                                source="Duration Change Detected",
                                reasoning=f"User changed duration from {old_duration} to {new_duration} minutes. Will re-query calendar with new duration.",
                                data={
                                    "old_duration": old_duration,
                                    "new_duration": new_duration,
                                    "mentioned_text": mentioned_text,
                                    "llm_new_value": new_duration_text,
                                    "user_message": latest_message
                                }
                            )
                        else:
                            state["meeting_duration_minutes"] = new_duration
                            logger.info(f"Duration set to: {new_duration} minutes")
            
            # Date
            if modifications.get("date", {}).get("action") == "change":
                new_date_text = modifications["date"].get("new_value")
                mentioned_text = modifications["date"].get("mentioned_text", "")
                
                emit_deduction(
                    source="Date Modification Detected",
                    reasoning=f"LLM extracted date change. new_value='{new_date_text}', mentioned_text='{mentioned_text}', current week_context='{state.get('week_context')}'",
                    data={"new_date_text": new_date_text, "mentioned_text": mentioned_text, "week_context": state.get("week_context")}
                )
                
                # Skip if the date is marked as AMBIGUOUS (needs clarification first)
                if new_date_text == "AMBIGUOUS":
                    logger.info(f"⚠️ Date is marked as AMBIGUOUS, waiting for clarification")
                elif new_date_text and new_date_text != "null":
                    # Safety check: Don't parse if it looks like a time reference
                    if not any(time_word in mentioned_text.lower() for time_word in ["pm", "am", "o'clock"]):
                        # Use Python parser to parse the date
                        parser_instance = TimeParser(state["timezone"])
                        # Add week context if available (e.g., user said "next week" earlier)
                        week_context = state.get("week_context")
                        
                        # ALWAYS apply week context if it exists, regardless of whether "next" is in the text
                        if week_context == "next_week":
                            # If the date text doesn't already contain "next", add it
                            if "next" not in new_date_text.lower():
                                new_date_text_with_context = f"next {new_date_text}"
                                emit_deduction(
                                    source="Week Context Applied",
                                    reasoning=f"Applying stored week context '{week_context}' to date parsing. User said '{new_date_text}', parsing as '{new_date_text_with_context}'",
                                    data={"original": new_date_text, "with_context": new_date_text_with_context, "week_context": week_context}
                                )
                                parsed_date = parser_instance.parse_date(new_date_text_with_context)
                            else:
                                # Already has "next" in it
                                emit_deduction(
                                    source="Week Context (Already Present)",
                                    reasoning=f"Week context exists but date text already contains 'next': '{new_date_text}'",
                                    data={"date_text": new_date_text, "week_context": week_context}
                                )
                                parsed_date = parser_instance.parse_date(new_date_text)
                        else:
                            parsed_date = parser_instance.parse_date(new_date_text)
                        
                        if parsed_date:
                            new_date = parsed_date.strftime("%Y-%m-%d")
                            if new_date != old_date:
                                state["preferred_date"] = new_date
                                parameters_changed = True
                                logger.info(f"🔄 Date CHANGED: {old_date} → {new_date}")
                            else:
                                state["preferred_date"] = new_date
                                logger.info(f"✅ Date set to: {new_date}")
                    else:
                        logger.info(f"⚠️ Skipping date change - detected time reference in: {mentioned_text}")
            elif modifications.get("date", {}).get("action") == "keep":
                logger.info(f"✅ Date KEPT as: {state.get('preferred_date')}")
            
            # Time
            time_just_changed = False
            if modifications.get("time", {}).get("action") == "change":
                new_time_text = modifications["time"].get("new_value")
                if new_time_text:
                    # Use Python parser with context
                    context_time = state.get("time_preference")
                    parsed = extract_time_components(
                        modifications["time"].get("mentioned_text", latest_message),
                        timezone=state["timezone"],
                        context_time=context_time
                    )
                    if parsed.get("time_preference"):
                        new_time = parsed["time_preference"]
                        if new_time != old_time:
                            state["time_preference"] = new_time
                            parameters_changed = True
                            time_just_changed = True
                            logger.info(f"🔄 Time CHANGED: {old_time} → {new_time}")
                        else:
                            state["time_preference"] = new_time
                            time_just_changed = True
                            logger.info(f"Time set to: {new_time}")
            
            # 🔥 IMPORTANT: If time was specified, filter slots to match it (regardless of intent)
            # This ensures we match the user's time even if LLM doesn't classify as "confirm"
            # BUT: Skip filtering if duration changed - we need to re-query with new duration instead
            if time_just_changed and duration_changed:
                logger.info(f"⏭️ Skipping time filtering because duration changed - will re-query with new duration")
            elif time_just_changed and not duration_changed:
                new_time = state.get("time_preference")
                slots = state.get("available_slots", [])
                
                # Only filter if we have slots AND the time is specified (supports formats like 5PM, 5:00PM, 17:00)
                if slots and new_time:
                    try:
                        import re
                        time_str = str(new_time).strip().upper()
                        # Match time formats: 5PM, 5:00PM, 17:00, 5:30 PM, etc.
                        match = re.match(r'(\d{1,2}):?(\d{2})?\s*(AM|PM)?', time_str)
                        
                        if match:
                            requested_hour = int(match.group(1))
                            requested_minute = int(match.group(2)) if match.group(2) else 0
                            am_pm = match.group(3)
                            
                            # Convert to 24-hour format
                            if am_pm == 'PM' and requested_hour != 12:
                                requested_hour += 12
                            elif am_pm == 'AM' and requested_hour == 12:
                                requested_hour = 0
                            
                            logger.info(f"🎯 Filtering slots to match requested time: {new_time} → {requested_hour}:{requested_minute:02d}")
                            
                            # Try exact match first
                            exact_matches = []
                            for slot in slots:
                                slot_time = datetime.fromisoformat(slot['start'])
                                if slot_time.hour == requested_hour and slot_time.minute == requested_minute:
                                    exact_matches.append(slot)
                            
                            if exact_matches:
                                state["available_slots"] = exact_matches
                                logger.info(f"✅ EXACT MATCH - Filtered to {len(exact_matches)} matching slot(s)")
                                # If exact match found, mark as ready to book
                                state["ready_to_book"] = True
                            else:
                                # Try fuzzy match (within 30 minutes)
                                logger.info(f"⚠️ No exact match for {requested_hour}:{requested_minute:02d}, trying fuzzy match...")
                                
                                fuzzy_matches = []
                                for slot in slots:
                                    slot_time = datetime.fromisoformat(slot['start'])
                                    slot_total_mins = slot_time.hour * 60 + slot_time.minute
                                    requested_total_mins = requested_hour * 60 + requested_minute
                                    distance = abs(slot_total_mins - requested_total_mins)
                                    
                                    if distance <= 30:  # Within 30 minutes
                                        fuzzy_matches.append((slot, distance))
                                
                                if fuzzy_matches:
                                    # Sort by distance and keep closest matches
                                    fuzzy_matches.sort(key=lambda x: x[1])
                                    closest_slots = [match[0] for match in fuzzy_matches[:3]]  # Keep top 3
                                    state["available_slots"] = closest_slots
                                    logger.info(f"✅ FUZZY MATCH - Filtered to {len(closest_slots)} closest slot(s)")
                                else:
                                    logger.warning(f"❌ No slots found near {requested_hour}:{requested_minute:02d}")
                                    logger.warning(f"Available slots: {[datetime.fromisoformat(s['start']).strftime('%H:%M') for s in slots]}")
                    except Exception as e:
                        logger.warning(f"❌ Could not filter slots by time: {e}")
            
            # Title
            if modifications.get("title", {}).get("action") == "change":
                new_title = modifications["title"].get("new_value")
                if new_title:
                    state["meeting_title"] = new_title
                    logger.info(f"Title set to: {new_title}")
            
            # ============================================================
            # EDGE CASE VALIDATION (Tests 5.1, 5.2, 5.3)
            # ============================================================
            validator = EdgeCaseValidator(timezone=state["timezone"])
            
            # Prepare validation inputs
            parsed_date_obj = None
            if state.get("preferred_date"):
                try:
                    tz = pytz.timezone(state["timezone"])
                    parsed_date_obj = datetime.strptime(state["preferred_date"], "%Y-%m-%d")
                    parsed_date_obj = tz.localize(parsed_date_obj)
                except Exception as e:
                    logger.warning(f"Could not parse date for validation: {e}")
            
            date_string = modifications.get("date", {}).get("mentioned_text", "") or latest_message
            duration_minutes = state.get("meeting_duration_minutes")
            duration_string = modifications.get("duration", {}).get("mentioned_text", "") or latest_message
            time_string = state.get("time_preference")
            
            # Run all validations
            is_valid, error_type, clarification_question = validator.validate_all(
                date_obj=parsed_date_obj,
                date_string=date_string,
                duration_minutes=duration_minutes,
                duration_string=duration_string,
                time_string=time_string,
                message=latest_message
            )
            
            if not is_valid and clarification_question:
                logger.warning(f"🚫 EDGE CASE DETECTED: {error_type}")
                logger.info(f"💬 Asking user for clarification: {clarification_question}")
                
                emit_deduction(
                    source=f"Edge Case Validation - {error_type}",
                    reasoning=f"Detected {error_type}. Asking user for clarification to ensure correct scheduling.",
                    data={
                        "error_type": error_type,
                        "clarification": clarification_question,
                        "date": state.get("preferred_date"),
                        "duration": duration_minutes,
                        "time": time_string
                    }
                )
                
                # Set needs clarification and return
                state["needs_clarification"] = True
                state["clarification_question"] = clarification_question
                state["next_action"] = "clarify"
                
                # Add clarification message
                state["messages"].append({
                    "role": "assistant",
                    "content": clarification_question
                })
                
                emit_node_exit("extract", state)
                return state
            
            # Buffer requirements (from LLM intent analysis)
            buffer_after = intent_data.get("buffer_after_last_meeting")
            buffer_before = intent_data.get("buffer_before_next_meeting")
            
            if buffer_after is not None:
                state["buffer_after_last_meeting"] = buffer_after
                logger.info(f"Buffer after last meeting set to: {buffer_after} minutes")
            
            if buffer_before is not None:
                state["buffer_before_next_meeting"] = buffer_before
                logger.info(f"Buffer before next meeting set to: {buffer_before} minutes")
            
            # Constraints (Test 3.4 - Multiple Constraints)
            constraints = intent_data.get("constraints", {})
            
            if constraints:
                negative_days = constraints.get("negative_days")
                if negative_days:
                    state["negative_days"] = negative_days
                    logger.info(f"🚫 Negative day constraints: {negative_days}")
                    emit_deduction(
                        source="Constraint Detection - Negative Days",
                        reasoning=f"User specified days to EXCLUDE: {', '.join(negative_days)}",
                        data={"negative_days": negative_days}
                    )
                
                earliest_time = constraints.get("earliest_time")
                if earliest_time:
                    state["earliest_time"] = earliest_time
                    logger.info(f"⏰ Earliest acceptable time: {earliest_time}")
                    emit_deduction(
                        source="Constraint Detection - Earliest Time",
                        reasoning=f"User specified earliest acceptable time: {earliest_time} (e.g., 'not too early')",
                        data={"earliest_time": earliest_time}
                    )
                
                latest_time = constraints.get("latest_time")
                if latest_time:
                    state["latest_time"] = latest_time
                    logger.info(f"⏰ Latest acceptable time: {latest_time}")
                    emit_deduction(
                        source="Constraint Detection - Latest Time",
                        reasoning=f"User specified latest acceptable time: {latest_time} (e.g., 'not too late')",
                        data={"latest_time": latest_time}
                    )
                
                multi_day_search = constraints.get("multi_day_search", False)
                if multi_day_search:
                    state["multi_day_search"] = True
                    logger.info(f"📅 Multi-day search enabled")
                    emit_deduction(
                        source="Constraint Detection - Multi-Day Search",
                        reasoning=f"User requested availability across multiple days (e.g., 'I'm free next week')",
                        data={"multi_day_search": True}
                    )
                
                date_range = constraints.get("date_range")
                if date_range:
                    # Parse date range (e.g., "next week" → calculate start and end dates)
                    parser_instance = TimeParser(state["timezone"])
                    
                    if "next week" in date_range.lower():
                        # Calculate next week's Monday and Friday (use IST timezone)
                        ist_tz = pytz.timezone('Asia/Kolkata')
                        now = datetime.now(ist_tz)
                        days_until_monday = (7 - now.weekday()) % 7 + 7  # Next Monday
                        next_monday = now + timedelta(days=days_until_monday)
                        next_friday = next_monday + timedelta(days=4)
                        
                        state["date_range_start"] = next_monday.strftime("%Y-%m-%d")
                        state["date_range_end"] = next_friday.strftime("%Y-%m-%d")
                        
                        logger.info(f"📅 Date range: {state['date_range_start']} to {state['date_range_end']}")
                        emit_deduction(
                            source="Date Range Calculation",
                            reasoning=f"Parsed 'next week' to date range: {state['date_range_start']} (Mon) to {state['date_range_end']} (Fri)",
                            data={"start": state["date_range_start"], "end": state["date_range_end"]}
                        )
                    elif "this week" in date_range.lower():
                        # Calculate this week's remaining days (use IST timezone)
                        ist_tz = pytz.timezone('Asia/Kolkata')
                        now = datetime.now(ist_tz)
                        # Start from today or tomorrow
                        start_day = now + timedelta(days=1)
                        # End on Friday
                        days_until_friday = (4 - now.weekday()) % 7
                        if days_until_friday == 0:
                            days_until_friday = 7
                        end_day = now + timedelta(days=days_until_friday)
                        
                        state["date_range_start"] = start_day.strftime("%Y-%m-%d")
                        state["date_range_end"] = end_day.strftime("%Y-%m-%d")
                        
                        logger.info(f"📅 Date range: {state['date_range_start']} to {state['date_range_end']}")
                        emit_deduction(
                            source="Date Range Calculation",
                            reasoning=f"Parsed 'this week' to date range: {state['date_range_start']} to {state['date_range_end']}",
                            data={"start": state["date_range_start"], "end": state["date_range_end"]}
                        )
            
            # 🔥 FALLBACK: Auto-calculate date range if multi_day_search is enabled but date_range wasn't provided
            # This handles cases where LLM sets multi_day_search=true but doesn't set date_range
            if state.get("multi_day_search") and not (state.get("date_range_start") and state.get("date_range_end")):
                # Check if there's any "next week" or "this week" mentioned in recent messages
                week_context = None
                messages_to_check = messages[-3:] if len(messages) > 3 else messages
                for msg in reversed(messages_to_check):
                    if msg.get("role") == "user":
                        content_lower = msg.get("content", "").lower()
                        if "next week" in content_lower or "next week's" in content_lower:
                            week_context = "next week"
                            break
                        elif "this week" in content_lower or "this week's" in content_lower:
                            week_context = "this week"
                            break
                
                if week_context:
                    # Auto-calculate date range
                    ist_tz = pytz.timezone('Asia/Kolkata')
                    now = datetime.now(ist_tz)
                    
                    if week_context == "next week":
                        # Calculate next week's Monday to Friday
                        days_until_monday = (7 - now.weekday()) % 7 + 7  # Next Monday
                        next_monday = now + timedelta(days=days_until_monday)
                        next_friday = next_monday + timedelta(days=4)
                        
                        state["date_range_start"] = next_monday.strftime("%Y-%m-%d")
                        state["date_range_end"] = next_friday.strftime("%Y-%m-%d")
                        
                        logger.info(f"🔧 AUTO-CALCULATED date range for '{week_context}': {state['date_range_start']} to {state['date_range_end']}")
                        emit_deduction(
                            source="Auto-Calculate Date Range (Fallback)",
                            reasoning=f"Multi-day search was enabled but no date_range was set. Detected '{week_context}' in conversation and auto-calculated date range.",
                            data={
                                "week_context": week_context,
                                "start": state["date_range_start"],
                                "end": state["date_range_end"]
                            }
                        )
                    elif week_context == "this week":
                        # Calculate this week's remaining days
                        start_day = now + timedelta(days=1)  # Tomorrow
                        # End on Friday
                        days_until_friday = (4 - now.weekday()) % 7
                        if days_until_friday == 0:
                            days_until_friday = 7
                        end_day = now + timedelta(days=days_until_friday)
                        
                        state["date_range_start"] = start_day.strftime("%Y-%m-%d")
                        state["date_range_end"] = end_day.strftime("%Y-%m-%d")
                        
                        logger.info(f"🔧 AUTO-CALCULATED date range for '{week_context}': {state['date_range_start']} to {state['date_range_end']}")
                        emit_deduction(
                            source="Auto-Calculate Date Range (Fallback)",
                            reasoning=f"Multi-day search was enabled but no date_range was set. Detected '{week_context}' in conversation and auto-calculated date range.",
                            data={
                                "week_context": week_context,
                                "start": state["date_range_start"],
                                "end": state["date_range_end"]
                            }
                        )
            
            # 🔥 CONTEXT CHANGE DETECTION: If parameters changed mid-conversation, invalidate old slots
            had_previous_suggestions = state.get("ready_to_book", False) or bool(state.get("available_slots"))
            
            if parameters_changed and had_previous_suggestions:
                logger.info("🔄 PARAMETER CHANGE DETECTED - Invalidating previous suggestions and re-querying calendar")
                logger.info(f"   Changed: Duration={old_duration}→{state.get('meeting_duration_minutes')}, Date={old_date}→{state.get('preferred_date')}, Time={old_time}→{state.get('time_preference')}")
                
                # Invalidate old data
                state["available_slots"] = None
                state["ready_to_book"] = False
                state["confirmed"] = False
                
                # Detect specific test scenarios for better tracking
                scenario_detected = None
                if duration_changed and not (old_date != state.get('preferred_date')) and not (old_time != state.get('time_preference')):
                    scenario_detected = "Test 4.3 - Duration Change (re-validation required)"
                    reasoning = f"User changed duration from {old_duration} to {state.get('meeting_duration_minutes')} minutes while keeping date and time. Must re-query to verify extended slot is available."
                elif (old_date != state.get('preferred_date')) and not duration_changed and not (old_time != state.get('time_preference')):
                    scenario_detected = "Test 4.2 - Day Change (retains duration/time)"
                    reasoning = f"User changed date from {old_date} to {state.get('preferred_date')} while keeping duration ({state.get('meeting_duration_minutes')} min) and time preference ({state.get('time_preference')}). Searching same time on different day."
                else:
                    reasoning = f"User modified parameters mid-conversation. Old slots are now invalid. Will re-query calendar with new parameters."
                
                # Emit deduction for debug dashboard
                emit_deduction(
                    source=f"Context Change Detection{' - ' + scenario_detected if scenario_detected else ''}",
                    reasoning=reasoning,
                    data={
                        "scenario": scenario_detected,
                        "old_duration": old_duration,
                        "new_duration": state.get("meeting_duration_minutes"),
                        "old_date": old_date,
                        "new_date": state.get("preferred_date"),
                        "old_time": old_time,
                        "new_time": state.get("time_preference"),
                        "duration_changed": duration_changed,
                        "date_changed": old_date != state.get('preferred_date'),
                        "time_changed": old_time != state.get('time_preference')
                    }
                )
                
                # Special logging for Test 4.3 - Duration Change
                if scenario_detected == "Test 4.3 - Duration Change (re-validation required)":
                    logger.info(f"⚠️ TEST 4.3 SCENARIO DETECTED: Duration changed from {old_duration} to {state.get('meeting_duration_minutes')} minutes")
                    logger.info(f"   → Must re-check calendar to ensure extended slot ({state.get('time_preference')}) is still available")
                    logger.info(f"   → Will NOT confirm until new duration is validated")
                
                # Special logging for Test 4.2 - Day Change
                if scenario_detected == "Test 4.2 - Day Change (retains duration/time)":
                    logger.info(f"⚠️ TEST 4.2 SCENARIO DETECTED: Day changed from {old_date} to {state.get('preferred_date')}")
                    logger.info(f"   → Retained duration: {state.get('meeting_duration_minutes')} minutes")
                    logger.info(f"   → Retained time preference: {state.get('time_preference')}")
                    logger.info(f"   → Searching for same time slot on different day")
            
            # Check if this is a reference query BEFORE deciding on clarification
            # Reference queries might not have explicit dates but can proceed to query_calendar
            is_potential_reference = detect_reference_query_pattern(latest_message)
            
            # If we detect a reference query, mark it in the state so we remember it across clarifications
            if is_potential_reference and not state.get("is_reference_query"):
                state["is_reference_query"] = True
                # Store the original message that contained the reference
                state["reference_event_name"] = latest_message  # Will be parsed later in query_calendar
                logger.info("🔖 Marked as reference query - will remember across clarifications")
            
            # Check if this was PREVIOUSLY identified as a reference query (even if current message isn't)
            # This handles cases where user answers clarification questions like "2 hours"
            was_reference_query = state.get("is_reference_query", False)
            
            # 🔥 If parameters changed, force re-query (skip clarification unless absolutely necessary)
            if parameters_changed and had_previous_suggestions:
                # Check if we have enough info to query calendar
                has_duration = state.get("meeting_duration_minutes") is not None
                has_date_or_reference = state.get("preferred_date") or state.get("is_reference_query") or (state.get("date_range_start") and state.get("date_range_end"))
                
                if has_duration and has_date_or_reference:
                    state["next_action"] = "query_calendar"
                    state["needs_clarification"] = False
                    logger.info("🔄 Parameters changed - forcing re-query to calendar")
                else:
                    # Still need critical info
                    state["needs_clarification"] = True
                    state["next_action"] = "clarify"
            else:
                # Normal flow: Check if we need clarification
                missing_info = intent_data.get("missing_info", [])
                
                # If it's a reference query, we only need duration to proceed.
                # Don't ask for a date if it's a reference query.
                if was_reference_query and "date" in missing_info:
                    missing_info.remove("date")
                
                # 🔥 IMPORTANT: If it's a multi-day search with date range, we don't need a specific date, time preference, or title
                is_multi_day_with_range = state.get("multi_day_search") and state.get("date_range_start") and state.get("date_range_end")
                if is_multi_day_with_range:
                    removed_items = []
                    # For multi-day searches, we only need duration. Remove date, time, and title from missing_info
                    for item in ["date", "time", "title"]:
                        if item in missing_info:
                            missing_info.remove(item)
                            removed_items.append(item)
                    
                    if removed_items:
                        logger.info(f"📅 Multi-day search with date range - removed {removed_items} from missing_info (only need duration)")
                        emit_deduction(
                            source="Multi-Day Search - Skip Unnecessary Clarifications",
                            reasoning=f"Multi-day search detected with date range ({state.get('date_range_start')} to {state.get('date_range_end')}). For availability check, only duration is needed. Removed {removed_items} from missing_info.",
                            data={
                                "date_range_start": state.get("date_range_start"),
                                "date_range_end": state.get("date_range_end"),
                                "removed_from_missing": removed_items,
                                "remaining_missing": missing_info
                            }
                        )
                
                logger.info(f"📋 Missing info after filtering: {missing_info}")
                
                if missing_info:
                    state["needs_clarification"] = True
                    state["next_action"] = "clarify"
                    logger.info(f"❗ Still need clarification for: {missing_info}")
                else:
                    state["needs_clarification"] = False
                    # Determine next action based on what we have
                    has_duration = state.get("meeting_duration_minutes") is not None
                    has_date_info = state.get("preferred_date") or (state.get("date_range_start") and state.get("date_range_end"))
                    
                    logger.info(f"✅ All required info collected. has_duration={has_duration}, has_date_info={has_date_info}")
                    
                    # If it's a multi-day search with duration and date range, proceed to query
                    if is_multi_day_with_range and has_duration:
                        state["next_action"] = "query_calendar"
                        logger.info("📅 Multi-day constrained search ready - proceeding to query_calendar")
                        emit_deduction(
                            source="Decision: Proceed to Query Calendar",
                            reasoning=f"Multi-day search with all required info (duration={state.get('meeting_duration_minutes')}min, range={state.get('date_range_start')} to {state.get('date_range_end')}). Ready to search calendar.",
                            data={
                                "duration": state.get("meeting_duration_minutes"),
                                "date_range_start": state.get("date_range_start"),
                                "date_range_end": state.get("date_range_end"),
                                "multi_day_search": True
                            }
                        )
                    # If it's a reference query (current or past), always go to query_calendar once we have duration
                    elif is_potential_reference or was_reference_query:
                        # For reference queries, we need at least duration before querying calendar
                        if has_duration:
                            state["next_action"] = "query_calendar"
                            logger.info("Reference query with duration - proceeding to query_calendar")
                        else:
                            # Need to clarify duration first
                            state["needs_clarification"] = True
                            state["next_action"] = "clarify"
                            logger.info("Reference query but need duration - clarifying first")
                    else:
                        state["next_action"] = intent_data.get("next_action", "query_calendar")
            
            logger.info(f"Final State - Duration: {state.get('meeting_duration_minutes')}, Date: {state.get('preferred_date')}, Time: {state.get('time_preference')}")
        
        except json.JSONDecodeError as e:
            logger.error(f"❌ Failed to parse LLM intent JSON: {e}")
            logger.error(f"📄 LLM Response: {response.content}")
            
            # Fallback: Use simple Python-based extraction
            logger.warning("⚠️ FALLBACK PATH: Using simple extraction instead of LLM")
            
            # Track old values for change detection
            old_duration = state.get("meeting_duration_minutes")
            old_date = state.get("preferred_date")
            old_time = state.get("time_preference")
            parameters_changed = False
            
            context_time = state.get("time_preference")
            time_components = extract_time_components(
                latest_message,
                timezone=state["timezone"],
                context_time=context_time
            )
            
            if time_components.get("duration_minutes"):
                new_duration = time_components["duration_minutes"]
                if new_duration != old_duration and old_duration is not None:
                    parameters_changed = True
                    logger.info(f"🔄 Duration CHANGED (fallback): {old_duration} → {new_duration} minutes")
                state["meeting_duration_minutes"] = new_duration
            if time_components.get("date"):
                new_date = time_components["date"].strftime("%Y-%m-%d")
                if new_date != old_date and old_date is not None:
                    parameters_changed = True
                    logger.info(f"🔄 Date CHANGED (fallback): {old_date} → {new_date}")
                state["preferred_date"] = new_date
            if time_components.get("time_preference"):
                new_time = time_components["time_preference"]
                if new_time != old_time and old_time is not None:
                    parameters_changed = True
                    logger.info(f"🔄 Time CHANGED (fallback): {old_time} → {new_time}")
                state["time_preference"] = new_time
            
            # Check if we had previous suggestions
            had_previous_suggestions = state.get("ready_to_book", False) or bool(state.get("available_slots"))
            
            # Invalidate old slots if parameters changed
            if parameters_changed and had_previous_suggestions:
                logger.info("🔄 PARAMETER CHANGE DETECTED (fallback) - Invalidating previous suggestions")
                state["available_slots"] = None
                state["ready_to_book"] = False
                state["confirmed"] = False
                
                emit_deduction(
                    source="Context Change Detection (Fallback)",
                    reasoning=f"User modified parameters mid-conversation (detected in fallback path). Old slots are now invalid.",
                    data={
                        "old_duration": old_duration,
                        "new_duration": state.get("meeting_duration_minutes"),
                        "old_date": old_date,
                        "new_date": state.get("preferred_date"),
                        "old_time": old_time,
                        "new_time": state.get("time_preference")
                    }
                )
            
            # Check for reference query in fallback path too!
            is_potential_reference = detect_reference_query_pattern(latest_message)
            
            # If we detect a reference query, mark it in the state
            if is_potential_reference and not state.get("is_reference_query"):
                state["is_reference_query"] = True
                state["reference_event_name"] = latest_message
                logger.info("🔖 Marked as reference query (fallback) - will remember across clarifications")
            
            # Check if this was PREVIOUSLY identified as a reference query
            was_reference_query = state.get("is_reference_query", False)
            
            # 🔥 If parameters changed in fallback path, force re-query
            if parameters_changed and had_previous_suggestions:
                has_duration = state.get("meeting_duration_minutes") is not None
                has_date_or_reference = state.get("preferred_date") or state.get("is_reference_query") or (state.get("date_range_start") and state.get("date_range_end"))
                
                if has_duration and has_date_or_reference:
                    state["next_action"] = "query_calendar"
                    state["needs_clarification"] = False
                    logger.info("🔄 Parameters changed (fallback) - forcing re-query to calendar")
                else:
                    state["needs_clarification"] = True
                    state["next_action"] = "clarify"
            else:
                # Simple decision logic
                has_duration = state.get("meeting_duration_minutes") is not None
                has_date = state.get("preferred_date") is not None
                has_date_range = state.get("date_range_start") and state.get("date_range_end")
                
                if has_duration and (has_date or has_date_range):
                    state["next_action"] = "query_calendar"
                elif is_potential_reference or was_reference_query:
                    # Reference query - proceed to query_calendar if we have duration
                    if has_duration:
                        state["next_action"] = "query_calendar"
                        logger.info("Detected reference query pattern in fallback - proceeding to query_calendar")
                    else:
                        # Need duration first
                        state["needs_clarification"] = True
                        state["next_action"] = "clarify"
                        logger.info("Reference query but need duration - clarifying first")
                else:
                    state["needs_clarification"] = True
                    state["next_action"] = "clarify"
        
    except Exception as e:
        logger.error(f"Error in extract_requirements: {e}")
        emit_error("extract", e, state)
        state["error_message"] = str(e)
    
    emit_node_exit("extract", state)
    return state


def query_calendar(state: SchedulerState) -> SchedulerState:
    """
    Query Google Calendar to find available slots or search for events.
    """
    logger.info("Node: query_calendar")
    emit_node_enter("query_calendar", state)
    
    try:
        # Load user credentials
        credentials = oauth_manager.load_credentials(state["user_id"])
        if not credentials:
            state["error_message"] = "User not authenticated"
            return state
        
        # Initialize calendar tool
        calendar = GoogleCalendarTool(credentials)
        
        # Check if this is a reference query (either from state flag or from latest message)
        is_reference = state.get("is_reference_query", False)
        
        # Get the message to analyze - use stored reference message if available
        reference_message = state.get("reference_event_name", "")
        latest_message = state["messages"][-1]["content"]
        
        emit_deduction(
            source="query_calendar Routing",
            reasoning=f"Determining query type. is_reference_query flag: {is_reference}, reference_message: '{reference_message}', latest_message: '{latest_message}'",
            data={"is_reference": is_reference, "reference_message": reference_message, "latest_message": latest_message}
        )
        
        # Determine which message to use for reference query parsing
        message_to_check = reference_message if reference_message else latest_message
        
        # Check if this is a multi-day search with constraints (Test 3.4)
        is_multi_day = state.get("multi_day_search", False)
        has_date_range = state.get("date_range_start") and state.get("date_range_end")
        
        if is_multi_day and has_date_range:
            logger.info(f"Processing multi-day constrained query")
            emit_deduction(
                source="query_calendar Routing",
                reasoning=f"Detected multi-day search with date range. Calling handle_multi_day_constrained_query().",
                data={
                    "multi_day_search": True,
                    "date_range_start": state.get("date_range_start"),
                    "date_range_end": state.get("date_range_end"),
                    "negative_days": state.get("negative_days"),
                    "earliest_time": state.get("earliest_time")
                }
            )
            state = handle_multi_day_constrained_query(state, calendar)
        # Check for reference queries like "before my 5 PM meeting" or "after the 'Event Name'"
        elif is_reference or "before my" in message_to_check.lower() or "after my" in message_to_check.lower() or "before the" in message_to_check.lower() or "after the" in message_to_check.lower():
            logger.info(f"Processing reference query with message: '{message_to_check}'")
            emit_deduction(
                source="query_calendar Routing",
                reasoning=f"Detected reference query pattern. Calling handle_reference_query() with message: '{message_to_check}'",
                data={"message": message_to_check, "is_reference": is_reference}
            )
            state = handle_reference_query(state, calendar, message_to_check)
        else:
            # Simple availability query
            emit_deduction(
                source="query_calendar Routing",
                reasoning=f"No reference query pattern detected. Calling handle_simple_query().",
                data={"message": message_to_check}
            )
            state = handle_simple_query(state, calendar)
        
    except Exception as e:
        logger.error(f"Error in query_calendar: {e}")
        emit_error("query_calendar", e, state)
        state["error_message"] = str(e)
    
    emit_node_exit("query_calendar", state)
    return state


def handle_multi_day_constrained_query(state: SchedulerState, calendar: GoogleCalendarTool) -> SchedulerState:
    """
    Handle multi-day searches with constraints (Test 3.4).
    Example: "I'm free next week, but not too early and not on Wednesday."
    """
    logger.info("🔍 Handling multi-day constrained query")
    
    emit_deduction(
        source="Query Type: Multi-Day Constrained Query",
        reasoning=f"User requested availability across multiple days with constraints (negative days, time limits)",
        data={
            "date_range_start": state.get("date_range_start"),
            "date_range_end": state.get("date_range_end"),
            "negative_days": state.get("negative_days"),
            "earliest_time": state.get("earliest_time"),
            "latest_time": state.get("latest_time")
        }
    )
    
    # Get constraints
    date_range_start = state.get("date_range_start")
    date_range_end = state.get("date_range_end")
    negative_days = state.get("negative_days", [])
    earliest_time = state.get("earliest_time")
    latest_time = state.get("latest_time")
    duration = state.get("meeting_duration_minutes", 60)
    
    # Generate list of dates to search
    start_date = datetime.fromisoformat(date_range_start)
    end_date = datetime.fromisoformat(date_range_end)
    
    search_dates = []
    current_date = start_date
    while current_date <= end_date:
        # Check if this day should be excluded
        day_name = current_date.strftime("%A").lower()
        if day_name not in negative_days:
            search_dates.append(current_date.strftime("%Y-%m-%d"))
        else:
            logger.info(f"🚫 Skipping {day_name} {current_date.strftime('%Y-%m-%d')} (negative constraint)")
        current_date += timedelta(days=1)
    
    emit_deduction(
        source="Multi-Day Search Dates",
        reasoning=f"Generated {len(search_dates)} dates to search, excluding negative days: {negative_days}",
        data={"search_dates": search_dates, "excluded_days": negative_days}
    )
    
    # Search each day and collect slots
    all_slots = []
    
    # Get time preference from state (e.g., "morning", "afternoon")
    # This helps the calendar tool generate slots in the right range
    time_preference = state.get("time_preference")
    
    # Convert earliest/latest time constraints to time_preference if not set
    if not time_preference and (earliest_time or latest_time):
        # If we have time constraints like 08:00-12:00, that's "morning"
        if earliest_time and latest_time:
            earliest_hour = int(earliest_time.split(':')[0])
            latest_hour = int(latest_time.split(':')[0])
            
            if earliest_hour >= 8 and latest_hour <= 12:
                time_preference = "morning"
            elif earliest_hour >= 12 and latest_hour <= 17:
                time_preference = "afternoon"
            elif earliest_hour >= 17:
                time_preference = "evening"
    
    logger.info(f"🕐 Using time_preference: {time_preference} for calendar search")
    
    for date_str in search_dates:
        logger.info(f"🔍 Searching {date_str}...")
        
        # Search for slots on this day with time preference
        day_slots, _ = calendar.find_available_slots(
            date=date_str,
            duration_minutes=duration,
            time_preference=time_preference,  # Pass time preference to focus search
            timezone=state["timezone"]
        )
        
        # Apply time constraints to filter slots
        if day_slots:
            filtered_slots = []
            for slot in day_slots:
                slot_start_time = datetime.fromisoformat(slot['start'])
                slot_hour = slot_start_time.hour
                slot_minute = slot_start_time.minute
                
                # Check earliest time constraint
                if earliest_time:
                    earliest_hour = int(earliest_time.split(':')[0])
                    earliest_minute = int(earliest_time.split(':')[1]) if ':' in earliest_time else 0
                    slot_time_minutes = slot_hour * 60 + slot_minute
                    earliest_time_minutes = earliest_hour * 60 + earliest_minute
                    
                    if slot_time_minutes < earliest_time_minutes:
                        logger.debug(f"  ⏭️ Skipping {slot['start_formatted']} (before {earliest_time})")
                        continue
                
                # Check latest time constraint
                if latest_time:
                    latest_hour = int(latest_time.split(':')[0])
                    latest_minute = int(latest_time.split(':')[1]) if ':' in latest_time else 0
                    slot_time_minutes = slot_hour * 60 + slot_minute
                    latest_time_minutes = latest_hour * 60 + latest_minute
                    
                    if slot_time_minutes > latest_time_minutes:
                        logger.debug(f"  ⏭️ Skipping {slot['start_formatted']} (after {latest_time})")
                        continue
                
                # Slot passes all constraints
                filtered_slots.append(slot)
            
            logger.info(f"  ✅ Found {len(filtered_slots)} slots on {date_str} (after applying time constraints)")
            all_slots.extend(filtered_slots)
        else:
            logger.info(f"  ❌ No slots found on {date_str}")
    
    emit_deduction(
        source="Multi-Day Search Results",
        reasoning=f"Searched {len(search_dates)} days and found {len(all_slots)} total slots matching all constraints",
        data={"total_slots": len(all_slots), "days_searched": len(search_dates)}
    )
    
    # Sort slots by date and time
    all_slots.sort(key=lambda s: s['start'])
    
    # Store top slots (limit to 5-6 for better UX)
    state["available_slots"] = all_slots[:6] if len(all_slots) > 6 else all_slots
    
    if all_slots:
        state["next_action"] = "suggest"
        logger.info(f"✅ Found {len(all_slots)} slots across {len(search_dates)} days")
    else:
        state["next_action"] = "resolve_conflict"
        logger.info("❌ No slots found matching all constraints")
    
    return state


def handle_simple_query(state: SchedulerState, calendar: GoogleCalendarTool) -> SchedulerState:
    """Handle simple calendar availability queries."""
    
    emit_deduction(
        source="Query Type: Simple Query",
        reasoning=f"This is being handled as a SIMPLE query (not a reference query). Will search for availability on a specific date.",
        data={"date": state.get("preferred_date"), "duration": state.get("meeting_duration_minutes")}
    )
    
    # Reset reference query flags for simple queries
    state["is_reference_query"] = False
    state["reference_event_details"] = None
    state["time_relation"] = None
    
    duration = state.get("meeting_duration_minutes", 60)
    date = state.get("preferred_date")
    time_pref = state.get("time_preference")
    
    if not date:
        # Default to tomorrow if no date specified (use IST timezone)
        ist_tz = pytz.timezone('Asia/Kolkata')
        tomorrow = datetime.now(ist_tz) + timedelta(days=1)
        date = tomorrow.strftime("%Y-%m-%d")
        emit_deduction(
            source="Date Defaulting",
            reasoning=f"No date was provided, defaulting to tomorrow: {date}",
            data={"default_date": date}
        )
    
    # CRITICAL: Check for buffer_after_last_meeting BEFORE finding slots
    # If user said "2 hours after my last meeting", we need to:
    # 1. Find their last meeting on the target date
    # 2. Calculate: last_meeting_end + buffer = actual_earliest_time
    # 3. Apply this as a constraint
    buffer_after_last = state.get("buffer_after_last_meeting")
    buffer_before_next = state.get("buffer_before_next_meeting")
    
    if buffer_after_last or buffer_before_next:
        logger.info(f"🔍 Buffer constraint detected: after_last={buffer_after_last} min, before_next={buffer_before_next} min")
        
        # Get all events on the target date to find first/last meetings
        ist_tz = pytz.timezone(state["timezone"])
        target_dt = datetime.strptime(date, "%Y-%m-%d")
        target_dt = ist_tz.localize(target_dt)
        
        day_start = target_dt.replace(hour=0, minute=0, second=0)
        day_end = target_dt.replace(hour=23, minute=59, second=59)
        
        day_events = calendar.list_events(
            start_time=day_start.astimezone(pytz.UTC),
            end_time=day_end.astimezone(pytz.UTC)
        )
        
        emit_deduction(
            source="Buffer Constraint - Calendar Query",
            reasoning=f"Querying calendar for {date} to find first/last meetings for buffer calculation",
            data={"date": date, "event_count": len(day_events)}
        )
        
        if buffer_after_last and day_events:
            # Find the LAST meeting of the day
            last_meeting = None
            last_meeting_end = None
            
            for event in day_events:
                event_end_str = event.get("end", {}).get("dateTime")
                if event_end_str:
                    event_end = parser.isoparse(event_end_str)
                    if not last_meeting_end or event_end > last_meeting_end:
                        last_meeting_end = event_end
                        last_meeting = event
            
            if last_meeting and last_meeting_end:
                # Calculate actual earliest time: last_meeting_end + buffer
                actual_earliest_datetime = last_meeting_end + timedelta(minutes=buffer_after_last)
                actual_earliest_time = actual_earliest_datetime.strftime("%H:%M")
                
                logger.info(f"✅ Last meeting: '{last_meeting.get('summary')}' ends at {last_meeting_end.strftime('%I:%M %p')}")
                logger.info(f"✅ Buffer: {buffer_after_last} minutes")
                logger.info(f"✅ Actual earliest time: {actual_earliest_datetime.strftime('%I:%M %p')} ({actual_earliest_time})")
                
                emit_deduction(
                    source="Buffer After Last Meeting - Applied",
                    reasoning=f"User's last meeting '{last_meeting.get('summary')}' ends at {last_meeting_end.strftime('%I:%M %p')}. Adding {buffer_after_last} minute buffer = slots must start after {actual_earliest_datetime.strftime('%I:%M %p')}",
                    data={
                        "last_meeting": last_meeting.get('summary'),
                        "last_meeting_end": last_meeting_end.isoformat(),
                        "buffer_minutes": buffer_after_last,
                        "calculated_earliest": actual_earliest_time,
                        "calculated_earliest_full": actual_earliest_datetime.isoformat()
                    }
                )
                
                # Override or merge with existing earliest_time constraint
                existing_earliest = state.get("earliest_time")
                if existing_earliest:
                    # Compare and use the LATER of the two times
                    existing_hour, existing_minute = map(int, existing_earliest.split(':'))
                    actual_hour, actual_minute = map(int, actual_earliest_time.split(':'))
                    
                    existing_minutes = existing_hour * 60 + existing_minute
                    actual_minutes = actual_hour * 60 + actual_minute
                    
                    if actual_minutes > existing_minutes:
                        logger.info(f"⚠️ Buffer constraint ({actual_earliest_time}) is LATER than user's time preference ({existing_earliest}). Using buffer time.")
                        state["earliest_time"] = actual_earliest_time
                    else:
                        logger.info(f"✅ User's time preference ({existing_earliest}) is already later than buffer time ({actual_earliest_time}). Keeping user preference.")
                else:
                    # No existing constraint, set this as earliest_time
                    state["earliest_time"] = actual_earliest_time
            else:
                logger.warning(f"⚠️ No meetings found on {date} to apply buffer_after_last_meeting")
                emit_deduction(
                    source="Buffer After Last Meeting - No Events",
                    reasoning=f"User requested buffer after last meeting, but no meetings found on {date}",
                    data={"date": date}
                )
        
        if buffer_before_next and day_events:
            # Find the FIRST meeting of the day
            first_meeting = None
            first_meeting_start = None
            
            for event in day_events:
                event_start_str = event.get("start", {}).get("dateTime")
                if event_start_str:
                    event_start = parser.isoparse(event_start_str)
                    if not first_meeting_start or event_start < first_meeting_start:
                        first_meeting_start = event_start
                        first_meeting = event
            
            if first_meeting and first_meeting_start:
                # Calculate actual latest time: first_meeting_start - buffer
                actual_latest_datetime = first_meeting_start - timedelta(minutes=buffer_before_next)
                actual_latest_time = actual_latest_datetime.strftime("%H:%M")
                
                logger.info(f"✅ First meeting: '{first_meeting.get('summary')}' starts at {first_meeting_start.strftime('%I:%M %p')}")
                logger.info(f"✅ Buffer: {buffer_before_next} minutes")
                logger.info(f"✅ Actual latest time: {actual_latest_datetime.strftime('%I:%M %p')} ({actual_latest_time})")
                
                emit_deduction(
                    source="Buffer Before Next Meeting - Applied",
                    reasoning=f"User's first meeting '{first_meeting.get('summary')}' starts at {first_meeting_start.strftime('%I:%M %p')}. Subtracting {buffer_before_next} minute buffer = slots must END before {actual_latest_datetime.strftime('%I:%M %p')}",
                    data={
                        "first_meeting": first_meeting.get('summary'),
                        "first_meeting_start": first_meeting_start.isoformat(),
                        "buffer_minutes": buffer_before_next,
                        "calculated_latest": actual_latest_time
                    }
                )
                
                # Override or merge with existing latest_time constraint
                existing_latest = state.get("latest_time")
                if existing_latest:
                    # Compare and use the EARLIER of the two times
                    existing_hour, existing_minute = map(int, existing_latest.split(':'))
                    actual_hour, actual_minute = map(int, actual_latest_time.split(':'))
                    
                    existing_minutes = existing_hour * 60 + existing_minute
                    actual_minutes = actual_hour * 60 + actual_minute
                    
                    if actual_minutes < existing_minutes:
                        logger.info(f"⚠️ Buffer constraint ({actual_latest_time}) is EARLIER than user's time preference ({existing_latest}). Using buffer time.")
                        state["latest_time"] = actual_latest_time
                    else:
                        logger.info(f"✅ User's time preference ({existing_latest}) is already earlier than buffer time ({actual_latest_time}). Keeping user preference.")
                else:
                    # No existing constraint, set this as latest_time
                    state["latest_time"] = actual_latest_time
    
    # Find available slots
    slots, partial_gap = calendar.find_available_slots(
        date=date,
        duration_minutes=duration,
        time_preference=time_pref,
        timezone=state["timezone"]
    )
    
    # Apply time constraints if they exist (Test 3.4 - Multiple Constraints)
    earliest_time = state.get("earliest_time")
    latest_time = state.get("latest_time")
    
    if slots and (earliest_time or latest_time):
        filtered_slots = []
        for slot in slots:
            slot_start_time = datetime.fromisoformat(slot['start'])
            slot_hour = slot_start_time.hour
            slot_minute = slot_start_time.minute
            
            # Check earliest time constraint
            if earliest_time:
                earliest_hour = int(earliest_time.split(':')[0])
                earliest_minute = int(earliest_time.split(':')[1]) if ':' in earliest_time else 0
                slot_time_minutes = slot_hour * 60 + slot_minute
                earliest_time_minutes = earliest_hour * 60 + earliest_minute
                
                if slot_time_minutes < earliest_time_minutes:
                    logger.debug(f"  ⏭️ Skipping {slot['start_formatted']} (before {earliest_time})")
                    continue
            
            # Check latest time constraint
            if latest_time:
                latest_hour = int(latest_time.split(':')[0])
                latest_minute = int(latest_time.split(':')[1]) if ':' in latest_time else 0
                slot_time_minutes = slot_hour * 60 + slot_minute
                latest_time_minutes = latest_hour * 60 + latest_minute
                
                if slot_time_minutes > latest_time_minutes:
                    logger.debug(f"  ⏭️ Skipping {slot['start_formatted']} (after {latest_time})")
                    continue
            
            # Slot passes all constraints
            filtered_slots.append(slot)
        
        logger.info(f"✅ Filtered {len(slots)} slots to {len(filtered_slots)} after applying time constraints (earliest: {earliest_time}, latest: {latest_time})")
        emit_deduction(
            source="Time Constraint Filtering",
            reasoning=f"Applied time constraints to filter slots. Earliest: {earliest_time}, Latest: {latest_time}. Filtered from {len(slots)} to {len(filtered_slots)} slots.",
            data={
                "original_count": len(slots),
                "filtered_count": len(filtered_slots),
                "earliest_time": earliest_time,
                "latest_time": latest_time
            }
        )
        slots = filtered_slots
    
    state["available_slots"] = slots
    state["partial_gap_at_requested_time"] = partial_gap
    
    if slots:
        state["next_action"] = "suggest"
        logger.info(f"Found {len(slots)} available slots")
    else:
        state["next_action"] = "resolve_conflict"
        logger.info("No available slots found")
    
    return state


def handle_named_event_reference(state: SchedulerState, calendar: GoogleCalendarTool, message: str, event_name: str) -> SchedulerState:
    """
    Handle references to named calendar events.
    Example: "schedule a short chat a day after the 'Project Alpha Kick-off'"
    """
    logger.info(f"Searching for named event: '{event_name}'")
    
    import re
    
    # Search for the event in calendar (next 30 days, use IST timezone)
    ist_tz = pytz.timezone('Asia/Kolkata')
    now = datetime.now(ist_tz)
    search_end = now + timedelta(days=30)
    
    logger.info(f"🔍 Searching calendar from {now} to {search_end}")
    
    events = calendar.list_events(
        start_time=now,
        end_time=search_end
    )
    
    # Emit raw calendar data for debugging
    emit_raw_calendar_data(
        source=f"Event Search for '{event_name}'",
        data=events
    )
    
    emit_deduction(
        source="Calendar Search",
        reasoning=f"Searched calendar for events in the next 30 days. Found {len(events)} total events. Now searching for event matching '{event_name}'.",
        data={"total_events": len(events), "search_term": event_name}
    )
    
    # Find event by name (case-insensitive partial match)
    # We'll collect all potential matches and score them
    potential_matches = []
    for event in events:
        event_summary = event.get('summary', '')
        event_summary_lower = event_summary.lower()
        event_name_lower = event_name.lower()
        
        # Calculate match score
        if event_name_lower == event_summary_lower:
            # Exact match (case-insensitive)
            score = 100
        elif event_name_lower in event_summary_lower:
            # Substring match
            score = 80
        elif event_summary_lower in event_name_lower:
            # Event summary is substring of search term
            score = 70
        else:
            # No match
            continue
        
        potential_matches.append({
            "event": event,
            "score": score,
            "summary": event_summary
        })
    
    emit_deduction(
        source="Event Matching",
        reasoning=f"Found {len(potential_matches)} potential matches for '{event_name}'.",
        data=potential_matches
    )
    
    if not potential_matches:
        logger.warning(f"Could not find event named '{event_name}'")
        emit_deduction(
            source="Event Not Found",
            reasoning=f"No events matched '{event_name}'. Asking user for clarification.",
            data=None
        )
        # Inform user that event wasn't found
        state["messages"].append({
            "role": "assistant",
            "content": f"I couldn't find an event called '{event_name}' in your calendar. Could you provide the exact date and time you'd like to schedule instead?"
        })
        state["needs_clarification"] = True
        state["next_action"] = "clarify"
        return state
    
    # Sort by score (highest first) and pick the best match
    potential_matches.sort(key=lambda x: x["score"], reverse=True)
    reference_event = potential_matches[0]["event"]
    
    emit_deduction(
        source="Event Selection",
        reasoning=f"Selected event '{reference_event.get('summary')}' with score {potential_matches[0]['score']} as the reference event.",
        data=reference_event
    )
    
    # Parse the reference event time
    ref_start = datetime.fromisoformat(reference_event['start']['dateTime'].replace('Z', '+00:00'))
    ref_end = datetime.fromisoformat(reference_event['end']['dateTime'].replace('Z', '+00:00'))
    
    # Parse relative time expression
    # First check if this is a same-day "before/after" (without day modifier)
    # "before my flight" = same day, before the event
    # "a day before my flight" = day before
    
    # Check for same-day patterns (no day quantifier)
    same_day_before = re.search(r'(?:sometime\s+)?before\s+(?:my|the)\s+(?!the\s+day)', message, re.IGNORECASE)
    same_day_after = re.search(r'(?:sometime\s+)?after\s+(?:my|the)\s+(?!the\s+day)', message, re.IGNORECASE)
    
    # Check for explicit day-offset patterns
    day_offset_patterns = [
        (r'(\d+)\s+days?\s+(after|before)', lambda m: int(m.group(1)) * (1 if m.group(2) == 'after' else -1)),
        (r'a\s+day\s+(after|before)', lambda m: 1 if m.group(1) == 'after' else -1),
        (r'the\s+day\s+(after|before)', lambda m: 1 if m.group(1) == 'after' else -1),
        (r'the\s+next\s+day', lambda m: 1),
        (r'tomorrow', lambda m: 1),  # If reference event is today
    ]
    
    day_offset = None
    matched_pattern = None
    
    # Check for explicit day offsets first
    for pattern, extractor in day_offset_patterns:
        match = re.search(pattern, message, re.IGNORECASE)
        if match:
            day_offset = extractor(match)
            matched_pattern = pattern
            logger.info(f"Parsed day offset: {day_offset} days")
            break
    
    # If no day offset pattern found, check for same-day patterns
    if day_offset is None:
        if same_day_before or same_day_after:
            day_offset = 0  # Same day
            matched_pattern = "same-day before/after"
            logger.info(f"Detected same-day reference (before/after without day modifier)")
        else:
            # Default: next day
            day_offset = 1
            matched_pattern = "default (next day)"
    
    emit_deduction(
        source="Time Offset Parsing",
        reasoning=f"Parsed relative time expression from user message. Pattern matched: '{matched_pattern}'. Day offset: {day_offset} days.",
        data={"pattern": matched_pattern, "day_offset": day_offset, "original_message": message}
    )
    
    # Calculate target date
    target_date = ref_start.date() + timedelta(days=day_offset)
    target_date_str = target_date.strftime("%Y-%m-%d")
    
    emit_deduction(
        source="Target Date Calculation",
        reasoning=f"Calculated target date by adding {day_offset} days to reference event date {ref_start.date()}. Target date: {target_date_str}",
        data={"reference_date": str(ref_start.date()), "offset_days": day_offset, "target_date": target_date_str}
    )
    
    # Update state with target date
    state["preferred_date"] = target_date_str
    
    # Parse duration from message if available (only if not already set)
    # Check if duration already exists in state
    existing_duration = state.get("meeting_duration_minutes")
    
    duration_match = re.search(r'(\d+)\s*(?:hour|hr|minute|min)', message, re.IGNORECASE)
    if duration_match and not existing_duration:
        duration_value = int(duration_match.group(1))
        if 'hour' in message.lower() or 'hr' in message.lower():
            state["meeting_duration_minutes"] = duration_value * 60
        else:
            state["meeting_duration_minutes"] = duration_value
        emit_deduction(
            source="Duration Extraction from Message",
            reasoning=f"Extracted duration from reference query message: {duration_value} {'hours' if 'hour' in message.lower() else 'minutes'}",
            data={"duration_minutes": state["meeting_duration_minutes"], "message": message}
        )
    elif 'short' in message.lower() and not existing_duration:
        state["meeting_duration_minutes"] = 30  # Default short meeting
        emit_deduction(
            source="Duration Inference",
            reasoning=f"User said 'short chat', defaulting to 30 minutes",
            data={"duration_minutes": 30}
        )
    elif existing_duration:
        # Duration already set, keep it
        emit_deduction(
            source="Duration Already Set",
            reasoning=f"Duration was already set to {existing_duration} minutes from previous user input. Not overriding.",
            data={"existing_duration": existing_duration, "message": message}
        )
    elif not state.get("meeting_duration_minutes"):
        # Will need to ask for duration
        emit_deduction(
            source="Duration Missing",
            reasoning=f"No duration found in message and none previously set. Will need to ask user.",
            data={"message": message}
        )
    
    # Determine time relation ("before" or "after") from the message
    # For same-day references, use the actual words in the message
    # For day-offset references, use the day_offset sign
    if day_offset == 0:
        # Same day - check if user said "before" or "after"
        if 'before' in message.lower():
            time_relation = "before"
        elif 'after' in message.lower():
            time_relation = "after"
        else:
            time_relation = "before"  # Default
    else:
        # Day offset - positive = after, negative = before
        time_relation = "after" if day_offset > 0 else "before"
    
    # Store reference event details
    state["is_reference_query"] = True
    state["reference_event_details"] = {
        'summary': reference_event.get('summary', 'meeting'),
        'start': ref_start.isoformat(),
        'end': ref_end.isoformat(),
        'start_formatted': ref_start.strftime('%I:%M %p'),
        'date_formatted': ref_start.strftime('%A, %B %d, %Y')
    }
    state["time_relation"] = time_relation
    
    # Check if we have all required info
    if not state.get("meeting_duration_minutes"):
        state["needs_clarification"] = True
        state["next_action"] = "clarify"
        logger.info("Need to clarify duration for named event reference")
        return state
    
    # Find available slots on target date
    duration = state.get("meeting_duration_minutes", 60)
    time_pref = state.get("time_preference")
    
    # For same-day "before/after" references, consider buffer and search strategy
    travel_buffer_minutes = 0
    if day_offset == 0:
        if time_relation == "before":
            # Check if it's a flight/travel event
            event_summary_lower = reference_event.get('summary', '').lower()
            if any(keyword in event_summary_lower for keyword in ['flight', 'plane', 'airport', 'travel', 'departure']):
                travel_buffer_minutes = 180  # 3 hours for flights
                emit_deduction(
                    source="Travel Buffer Calculation",
                    reasoning=f"Detected flight/travel event '{reference_event.get('summary')}'. Applying 3-hour buffer for travel and check-in time.",
                    data={"event_type": "flight", "buffer_minutes": 180, "event_name": reference_event.get('summary')}
                )
            else:
                travel_buffer_minutes = 30  # 30 minutes for regular meetings
                emit_deduction(
                    source="Meeting Buffer Calculation",
                    reasoning=f"Applying 30-minute buffer before the meeting.",
                    data={"event_type": "meeting", "buffer_minutes": 30}
                )
            
            # Store buffer in state
            state["buffer_minutes"] = travel_buffer_minutes
        
        # IMPORTANT: For same-day "before/after" queries, ignore time_preference
        # The time mentioned (e.g., "6 PM") is the reference event's time, not the desired meeting time
        # We need to search the FULL day and then filter, not restrict search window
        if time_pref:
            emit_deduction(
                source="Time Preference Override",
                reasoning=f"For same-day '{time_relation}' query, ignoring time_preference to search full day (not restricting to specific hours). Will filter after.",
                data={"original_time_pref": time_pref, "overridden_to": None, "relation": time_relation}
            )
            time_pref = None
    
    slots, _ = calendar.find_available_slots(
        date=target_date_str,
        duration_minutes=duration,
        time_preference=time_pref,
        timezone=state["timezone"]
    )
    
    # Filter slots for same-day references
    if day_offset == 0 and slots:
        filtered_slots = []
        
        if time_relation == "before":
            # Meeting must END before (reference_start - buffer)
            cutoff_time = ref_start - timedelta(minutes=travel_buffer_minutes)
            
            emit_deduction(
                source="Same-Day Before Filter",
                reasoning=f"Filtering slots to end before {cutoff_time.strftime('%I:%M %p')} ({reference_event.get('summary')} at {ref_start.strftime('%I:%M %p')} minus {travel_buffer_minutes} min buffer).",
                data={"reference_time": ref_start.isoformat(), "buffer_minutes": travel_buffer_minutes, "cutoff_time": cutoff_time.isoformat()}
            )
            
            for slot in slots:
                slot_end = datetime.fromisoformat(slot['end'])
                if slot_end <= cutoff_time:
                    filtered_slots.append(slot)
            
            logger.info(f"Filtered {len(slots)} slots to {len(filtered_slots)} slots ending before {cutoff_time.strftime('%I:%M %p')}")
        
        elif time_relation == "after":
            # Meeting must START after reference event ends (+ buffer)
            cutoff_time = ref_end + timedelta(minutes=travel_buffer_minutes)
            
            emit_deduction(
                source="Same-Day After Filter",
                reasoning=f"Filtering slots to start after {cutoff_time.strftime('%I:%M %p')}.",
                data={"reference_end": ref_end.isoformat(), "buffer_minutes": travel_buffer_minutes, "cutoff_time": cutoff_time.isoformat()}
            )
            
            for slot in slots:
                slot_start = datetime.fromisoformat(slot['start'])
                if slot_start >= cutoff_time:
                    filtered_slots.append(slot)
            
            logger.info(f"Filtered {len(slots)} slots to {len(filtered_slots)} slots starting after {cutoff_time.strftime('%I:%M %p')}")
        
        slots = filtered_slots
    
    state["available_slots"] = slots
    
    if slots:
        state["next_action"] = "suggest"
        logger.info(f"Found {len(slots)} slots on {target_date_str} (relative to '{event_name}')")
    else:
        state["next_action"] = "resolve_conflict"
        logger.info(f"No slots found on {target_date_str}")
    
    return state


def handle_reference_query(state: SchedulerState, calendar: GoogleCalendarTool, message: str) -> SchedulerState:
    """
    Handle complex queries that reference other calendar events.
    Examples: 
    - "schedule 1 hour before my 5 PM meeting on Friday"
    - "a day after the 'Project Alpha Kick-off'"
    """
    logger.info("Handling reference query")
    
    import re
    
    # Strategy 1: Check for named event references (in quotes or specific patterns)
    # Pattern: "after the 'Event Name'" or "before my 'Event Name'" or "after Event Name"
    event_name_patterns = [
        r"(?:before|after)\s+(?:the|my)\s+['\"]([^'\"]+)",  # "after the 'Event Name" (captures even with missing closing quote)
        r"(?:before|after)\s+['\"]([^'\"]+)",  # "after 'Event Name" (captures even with missing closing quote)
        r"(?:before|after)\s+(?:the|my)\s+([A-Z][A-Za-z\s-]+(?:Kick-?off|Meeting|Call|Conference|Session))",  # Named events
    ]
    
    emit_deduction(
        source="Reference Query Detection",
        reasoning=f"Analyzing message for named event references: '{message}'",
        data={"message": message, "patterns_to_try": event_name_patterns}
    )
    
    event_name = None
    for idx, pattern in enumerate(event_name_patterns):
        match = re.search(pattern, message, re.IGNORECASE)
        if match:
            event_name = match.group(1).strip()
            logger.info(f"Found named event reference: '{event_name}'")
            emit_deduction(
                source="Event Name Extraction",
                reasoning=f"Successfully extracted event name using pattern #{idx+1}: '{pattern}'. Extracted name: '{event_name}'",
                data={"pattern_index": idx, "pattern": pattern, "extracted_name": event_name}
            )
            break
    
    # Log if no event name was found via regex - try LLM fallback
    if not event_name:
        emit_deduction(
            source="Event Name Extraction Failed (Regex)",
            reasoning=f"No event name could be extracted from message using any of the {len(event_name_patterns)} regex patterns. Attempting LLM-based extraction as fallback.",
            data={"message": message, "patterns_tried": event_name_patterns}
        )
        
        # Use LLM to extract event name
        llm_prompt = f"""Extract the event name from this user message about scheduling relative to an existing calendar event.

User message: "{message}"

Rules:
1. Look for event names mentioned after words like "before/after the" or "before/after my"
2. Event names are often in quotes but may not have closing quotes
3. Event names are usually capitalized (e.g., "Project Alpha Kick-off", "Team Meeting", "Conference Call")
4. Return ONLY the event name, nothing else
5. If no event name is found, return "NONE"

Event name:"""
        
        try:
            llm_response = llm.invoke([HumanMessage(content=llm_prompt)])
            extracted_name = llm_response.content.strip()
            
            if extracted_name and extracted_name != "NONE":
                event_name = extracted_name
                emit_deduction(
                    source="Event Name Extraction (LLM Fallback)",
                    reasoning=f"LLM successfully extracted event name: '{event_name}' from message where regex failed.",
                    data={"extracted_name": event_name, "llm_prompt": llm_prompt}
                )
                logger.info(f"LLM extracted event name: '{event_name}'")
            else:
                emit_deduction(
                    source="Event Name Extraction Failed (LLM)",
                    reasoning=f"LLM could not extract an event name either. LLM response: '{extracted_name}'",
                    data={"llm_response": extracted_name}
                )
        except Exception as e:
            logger.error(f"Error using LLM for event name extraction: {e}")
            emit_deduction(
                source="Event Name Extraction Error",
                reasoning=f"Error occurred while using LLM to extract event name: {str(e)}",
                data={"error": str(e)}
            )
    
    # If we found a named event, search for it
    if event_name:
        emit_deduction(
            source="Routing Decision",
            reasoning=f"Found named event reference '{event_name}'. Routing to handle_named_event_reference().",
            data={"event_name": event_name}
        )
        return handle_named_event_reference(state, calendar, message, event_name)
    
    # Strategy 2: Try to find time-based reference
    # Example: "before my 5 PM meeting on Friday"
    time_match = re.search(r'(\d{1,2})\s*(?:PM|AM|pm|am)', message)
    day_match = re.search(r'(monday|tuesday|wednesday|thursday|friday|saturday|sunday)', message, re.IGNORECASE)
    
    if time_match and day_match:
        # User referenced a specific time
        ref_hour = int(time_match.group(1))
        if 'PM' in message.upper() and ref_hour != 12:
            ref_hour += 12
        
        day_name = day_match.group(1)
        
        # Parse the day
        parser = TimeParser(state["timezone"])
        target_date = parser.parse_date(day_name)
        
        # Check if there's actually a meeting at that time
        if target_date:
            # Search for event around that time
            search_start = target_date.replace(hour=ref_hour-1, minute=0)
            search_end = target_date.replace(hour=ref_hour+1, minute=59)
            
            events = calendar.list_events(
                start_time=search_start,
                end_time=search_end
            )
            
            if events:
                # Found the reference meeting
                ref_event = events[0]
                ref_start = datetime.fromisoformat(ref_event['start']['dateTime'].replace('Z', '+00:00'))
                ref_end = datetime.fromisoformat(ref_event['end']['dateTime'].replace('Z', '+00:00'))
                
                # Check if it's a flight and apply buffer
                travel_buffer_minutes = 0
                event_summary_lower = ref_event.get('summary', '').lower()
                if any(keyword in event_summary_lower for keyword in ['flight', 'plane', 'airport', 'travel', 'departure']):
                    travel_buffer_minutes = 180  # 3 hours for flights
                    logger.info(f"Detected flight in time-based reference. Applying 3-hour buffer.")
                else:
                    travel_buffer_minutes = 30  # 30 minutes for regular meetings
                
                # Store reference event details in state
                state["is_reference_query"] = True
                state["reference_event_details"] = {
                    'summary': ref_event.get('summary', 'meeting'),
                    'start': ref_start.isoformat(),
                    'end': ref_end.isoformat(),
                    'start_formatted': ref_start.strftime('%I:%M %p'),
                    'date_formatted': ref_start.strftime('%A, %B %d, %Y')
                }
                state["time_relation"] = "before" if "before" in message else "after"
                state["buffer_minutes"] = travel_buffer_minutes
                
                # Instead of calculating a single slot, search for all available slots and filter
                duration = state.get("meeting_duration_minutes", 60)
                slot_date_str = target_date.strftime("%Y-%m-%d")
                
                # Get all slots for the day
                all_slots, _ = calendar.find_available_slots(
                    date=slot_date_str,
                    duration_minutes=duration,
                    time_preference=None,  # Search full day
                    timezone=state["timezone"]
                )
                
                # Filter based on buffer
                filtered_slots = []
                if "before" in message:
                    # Meeting must END before (reference_start - buffer)
                    cutoff_time = ref_start - timedelta(minutes=travel_buffer_minutes)
                    logger.info(f"Time-based 'before' query: filtering slots to end before {cutoff_time.strftime('%I:%M %p')}")
                    
                    for slot in all_slots:
                        slot_end_time = datetime.fromisoformat(slot['end'])
                        if slot_end_time <= cutoff_time:
                            filtered_slots.append(slot)
                else:  # "after"
                    # Meeting must START after (reference_end + buffer)
                    cutoff_time = ref_end + timedelta(minutes=travel_buffer_minutes)
                    logger.info(f"Time-based 'after' query: filtering slots to start after {cutoff_time.strftime('%I:%M %p')}")
                    
                    for slot in all_slots:
                        slot_start_time = datetime.fromisoformat(slot['start'])
                        if slot_start_time >= cutoff_time:
                            filtered_slots.append(slot)
                
                if filtered_slots:
                    state["available_slots"] = filtered_slots
                    state["next_action"] = "suggest"
                    logger.info(f"Found {len(filtered_slots)} slots for time-based reference query with buffer")
                    return state
                else:
                    # No slots found with buffer - go to resolve_conflict
                    state["available_slots"] = []
                    state["next_action"] = "resolve_conflict"
                    logger.info(f"No slots found for time-based reference query with buffer")
                    return state
    
    # Fallback: treat as simple query
    return handle_simple_query(state, calendar)


def suggest_times(state: SchedulerState) -> SchedulerState:
    """
    Suggest available time slots to the user.
    """
    logger.info("Node: suggest_times")
    emit_node_enter("suggest", state)
    
    try:
        slots = state.get("available_slots", [])
        
        if not slots:
            state["next_action"] = "resolve_conflict"
            return state
        
        # Check if this is a reference query (before/after another meeting)
        is_reference_query = state.get("is_reference_query", False)
        reference_event = state.get("reference_event_details")
        time_relation = state.get("time_relation")
        
        if is_reference_query and reference_event:
            # Handle reference query with special messaging
            ref_summary = reference_event.get('summary', 'meeting')
            ref_time = reference_event['start_formatted']
            ref_date = reference_event['date_formatted']
            relation_text = time_relation if time_relation else "after"
            
            # Check if same-day or different-day reference
            ref_dt = datetime.fromisoformat(reference_event['start'])
            first_slot_dt = datetime.fromisoformat(slots[0]['start'])
            is_same_day = (ref_dt.date() == first_slot_dt.date())
            
            # Check for travel buffer
            travel_buffer = state.get("buffer_minutes", 0)
            
            if len(slots) > 1:
                # Multiple slots available
                slot_descriptions = []
                for slot in slots[:3]:  # Show top 3 options
                    slot_descriptions.append(f"{slot['start_formatted']}")
                
                times_text = " or ".join(slot_descriptions)
                
                if is_same_day and relation_text == "before":
                    # Same-day "before" reference (like flight)
                    event_summary_lower = ref_summary.lower()
                    is_flight = any(keyword in event_summary_lower for keyword in ['flight', 'plane', 'airport', 'travel', 'departure'])
                    
                    if is_flight and travel_buffer > 0:
                        # Mention travel buffer for flights
                        buffer_hours = travel_buffer // 60
                        cutoff_time = (ref_dt - timedelta(minutes=travel_buffer)).strftime('%I:%M %p')
                        
                        message = f"Your {ref_summary.lower()} is at {ref_time}. Assuming {buffer_hours}-hour travel/check-in buffer, I can schedule before {cutoff_time}. I have {times_text}. Which works?"
                    else:
                        # Regular same-day "before" reference
                        message = f"Your '{ref_summary}' is at {ref_time}. I have {times_text} available before then. Which works?"
                    
                    logger.info(f"Same-day before reference response: {message}")
                else:
                    # Day-offset reference (different day)
                    # Format dates with ordinals (15th, 16th, etc.)
                    ref_day = ref_dt.day
                    ref_ordinal = f"{ref_day}{'th' if 11 <= ref_day <= 13 else {1: 'st', 2: 'nd', 3: 'rd'}.get(ref_day % 10, 'th')}"
                    ref_date_short = ref_dt.strftime(f'%B {ref_ordinal}')
                    
                    target_day = first_slot_dt.day
                    target_ordinal = f"{target_day}{'th' if 11 <= target_day <= 13 else {1: 'st', 2: 'nd', 3: 'rd'}.get(target_day % 10, 'th')}"
                    target_date_short = first_slot_dt.strftime(f'%B {ref_ordinal}')
                    
                    message = f"Your '{ref_summary}' is on {ref_date_short}. I can do {target_date_short} at {times_text}. Which works?"
                    logger.info(f"Day-offset reference response: {message}")
            else:
                # Single slot suggestion
                slot = slots[0]
                message = f"You have a {ref_time} {ref_summary.lower()} on {ref_date}. I can schedule {slot['start_formatted']}–{datetime.fromisoformat(slot['end']).strftime('%I:%M %p')} {relation_text} it. Should I?"
                logger.info(f"Single slot reference response: {message}")
            
        else:
            # Check for partial availability at requested time (Test Case 3.3)
            partial_gap = state.get("partial_gap_at_requested_time")
            if partial_gap:
                # There's only a partial slot available at the requested time
                gap_start_dt = datetime.fromisoformat(partial_gap['start'])
                gap_end_dt = datetime.fromisoformat(partial_gap['end'])
                gap_duration = partial_gap['duration_minutes']
                requested_duration = partial_gap['requested_duration']
                requested_time_formatted = gap_start_dt.strftime('%I:%M %p').lstrip('0')
                
                # Build compromise message
                alternatives = []
                if slots:
                    for i, slot in enumerate(slots[:3]):  # Show top 3 alternatives
                        alternatives.append(slot['start_formatted'])
                
                if alternatives:
                    alternatives_text = " or ".join(alternatives)
                    message = f"I only have a {gap_duration}-minute slot at {requested_time_formatted}. Would you like to (1) schedule {gap_duration} minutes at {requested_time_formatted}, or (2) find a different {requested_duration}-minute slot? I have {alternatives_text} available."
                else:
                    message = f"I only have a {gap_duration}-minute slot at {requested_time_formatted}, but you need {requested_duration} minutes. Would you like to schedule {gap_duration} minutes at {requested_time_formatted} instead?"
                
                logger.info(f"Detected partial availability: {gap_duration} min available at requested time, need {requested_duration} min. Offering compromise.")
            
            else:
                # Check if this is a multi-day constrained search (Test 3.4)
                is_multi_day = state.get("multi_day_search", False)
                negative_days = state.get("negative_days", [])
                earliest_time = state.get("earliest_time")
                
                if is_multi_day and len(slots) > 0:
                    # Multi-day search - present options across days concisely
                    # Group slots by day for better presentation
                    from collections import defaultdict
                    slots_by_day = defaultdict(list)
                    for slot in slots[:5]:  # Top 5 slots
                        day_name = datetime.fromisoformat(slot['start']).strftime("%A")
                        slots_by_day[day_name].append(slot)
                    
                    # Build concise message showing options across days
                    slot_options = []
                    for day_name, day_slots in list(slots_by_day.items())[:3]:  # Max 3 days
                        # Show first slot from each day
                        slot = day_slots[0]
                        slot_options.append(f"{day_name} {slot['start_formatted']}")
                    
                    options_text = ", ".join(slot_options)
                    
                    # Build constraint acknowledgment
                    constraint_parts = []
                    if negative_days:
                        if len(negative_days) == 1:
                            constraint_parts.append(f"not on {negative_days[0].capitalize()}")
                        else:
                            days_list = ", ".join([d.capitalize() for d in negative_days[:-1]]) + f" or {negative_days[-1].capitalize()}"
                            constraint_parts.append(f"not on {days_list}")
                    if earliest_time:
                        hour = int(earliest_time.split(':')[0])
                        time_str = f"{hour} AM" if hour < 12 else f"{hour - 12} PM" if hour > 12 else "12 PM"
                        constraint_parts.append(f"after {time_str}")
                    
                    constraints_text = " and ".join(constraint_parts) if constraint_parts else ""
                    
                    # Construct message
                    if constraints_text:
                        message = f"I have {options_text}. Which works?"
                    else:
                        message = f"I found options: {options_text}. Which works?"
                    
                    logger.info(f"Multi-day suggestion: {message}")
                else:
                    # Normal suggestion flow
                    # Format slots for presentation
                    slot_descriptions = []
                    for slot in slots:
                        slot_descriptions.append(f"- {slot['start_formatted']} on {slot['date_formatted']}")
                    
                    # Check if we have an exact time match
                    is_exact_match = False
                    requested_time = state.get("time_preference", "")
                    if requested_time and ':' in requested_time and slots:
                        # Parse requested hour from "17:00" format
                        requested_hour = int(requested_time.split(':')[0])
                        first_slot_time = datetime.fromisoformat(slots[0]['start'])
                        # Check if first slot matches requested hour (within 30 minutes)
                        if abs(first_slot_time.hour - requested_hour) == 0:
                            is_exact_match = True
                    
                    # Check for buffer requirements
                    buffer_after = state.get("buffer_after_last_meeting")
                    buffer_before = state.get("buffer_before_next_meeting")
                    travel_buffer = state.get("buffer_minutes")
                    
                    if buffer_after:
                        buffer_info = f"{buffer_after} minutes after last meeting"
                    elif buffer_before:
                        buffer_info = f"{buffer_before} minutes before next meeting"
                    elif travel_buffer:
                        buffer_info = f"{travel_buffer} minutes travel buffer"
                    else:
                        buffer_info = "None"
                    
                    # Use LLM to generate natural suggestion
                    prompt = SUGGESTION_PROMPT.format(
                        available_slots="\n".join(slot_descriptions),
                        duration=state.get("meeting_duration_minutes", "unknown"),
                        date=state.get("preferred_date", "requested date"),
                        time_preference=state.get("time_preference", "requested time"),
                        num_slots=len(slots),
                        is_exact_match="Yes" if is_exact_match else "No",
                        buffer_info=buffer_info
                    )
                    
                    response = llm.invoke([SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=prompt)])
                    message = response.content
        
        # Add assistant message to conversation
        state["messages"].append({
            "role": "assistant",
            "content": message
        })
        
        state["ready_to_book"] = True
        state["next_action"] = "wait_for_selection"
        
        logger.info("Suggested available times to user")
        
    except Exception as e:
        logger.error(f"Error in suggest_times: {e}")
        emit_error("suggest", e, state)
        state["error_message"] = str(e)
    
    emit_node_exit("suggest", state)
    return state


def resolve_conflict(state: SchedulerState) -> SchedulerState:
    """
    Handle conflicts when no slots are available.
    Suggest alternative times proactively.
    """
    logger.info("Node: resolve_conflict")
    emit_node_enter("resolve_conflict", state)
    
    try:
        # Load calendar
        credentials = oauth_manager.load_credentials(state["user_id"])
        calendar = GoogleCalendarTool(credentials)
        
        # Try alternative strategies
        alternatives = []
        
        # Check if this is a reference query with buffer requirements
        is_reference = state.get("is_reference_query", False)
        reference_event = state.get("reference_event_details")
        time_relation = state.get("time_relation")
        travel_buffer = state.get("buffer_minutes", 0)
        
        # Strategy 1: Check ENTIRE same day for ANY available time (PRIORITIZE SAME DAY FIRST)
        if state.get("preferred_date"):
            # Check all times on the same day (don't restrict by time_preference)
            same_day_slots, _ = calendar.find_available_slots(
                date=state["preferred_date"],
                duration_minutes=state.get("meeting_duration_minutes", 60),
                time_preference=None,  # Check ALL times of the day
                timezone=state["timezone"]
            )
            
            # FILTER: Apply intelligent time filtering to suggest reasonable hours
            # If user requested a specific time, suggest alternatives within a reasonable window
            original_time_pref = state.get("time_preference")
            if same_day_slots and original_time_pref:
                filtered_by_time = []
                
                # Determine reasonable time bounds
                if ':' in str(original_time_pref):
                    # Specific time requested (e.g., "07:00" for 7 AM)
                    req_hour = int(str(original_time_pref).split(':')[0])
                    
                    # Define reasonable window around requested time
                    # Early morning (5-8 AM): suggest 5 AM - 11 AM
                    # Morning (8-12): suggest 7 AM - 2 PM
                    # Afternoon (12-17): suggest 11 AM - 7 PM
                    # Evening (17-21): suggest 3 PM - 10 PM
                    # Night (21-24 or 0-5): suggest 6 PM - 11 PM
                    if 5 <= req_hour < 8:
                        min_hour, max_hour = 5, 11
                    elif 8 <= req_hour < 12:
                        min_hour, max_hour = 7, 14
                    elif 12 <= req_hour < 17:
                        min_hour, max_hour = 11, 19
                    elif 17 <= req_hour < 21:
                        min_hour, max_hour = 15, 22
                    else:
                        min_hour, max_hour = 18, 23
                    
                    logger.info(f"🕐 Filtering alternatives to reasonable hours ({min_hour}:00 - {max_hour}:00) based on requested time {req_hour}:00")
                    
                    for slot in same_day_slots:
                        slot_time = datetime.fromisoformat(slot['start'])
                        if min_hour <= slot_time.hour <= max_hour:
                            filtered_by_time.append(slot)
                    
                    logger.info(f"Filtered {len(same_day_slots)} slots to {len(filtered_by_time)} slots within reasonable hours")
                    same_day_slots = filtered_by_time
                
                elif original_time_pref in ['morning', 'afternoon', 'evening', 'night']:
                    # Time of day preference
                    if original_time_pref == 'morning':
                        min_hour, max_hour = 6, 12
                    elif original_time_pref == 'afternoon':
                        min_hour, max_hour = 12, 18
                    elif original_time_pref == 'evening':
                        min_hour, max_hour = 17, 21
                    else:  # night
                        min_hour, max_hour = 20, 23
                    
                    logger.info(f"🕐 Filtering alternatives to {original_time_pref} hours ({min_hour}:00 - {max_hour}:00)")
                    
                    for slot in same_day_slots:
                        slot_time = datetime.fromisoformat(slot['start'])
                        if min_hour <= slot_time.hour <= max_hour:
                            filtered_by_time.append(slot)
                    
                    logger.info(f"Filtered {len(same_day_slots)} slots to {len(filtered_by_time)} slots within {original_time_pref} hours")
                    same_day_slots = filtered_by_time
                else:
                    # No specific time preference, default to business hours (8 AM - 6 PM)
                    logger.info(f"🕐 Filtering alternatives to business hours (8:00 - 18:00)")
                    
                    for slot in same_day_slots:
                        slot_time = datetime.fromisoformat(slot['start'])
                        if 8 <= slot_time.hour <= 18:
                            filtered_by_time.append(slot)
                    
                    logger.info(f"Filtered {len(same_day_slots)} slots to {len(filtered_by_time)} slots within business hours")
                    same_day_slots = filtered_by_time
                
                # Fallback: If filtering removed all slots, use unfiltered list
                if not same_day_slots and filtered_by_time is not None:
                    logger.warning("⚠️ Time filtering removed all slots, falling back to all available slots on the day")
                    same_day_slots, _ = calendar.find_available_slots(
                        date=state["preferred_date"],
                        duration_minutes=state.get("meeting_duration_minutes", 60),
                        time_preference=None,
                        timezone=state["timezone"]
                    )
            
            # IMPORTANT: Apply buffer filtering if this is a reference query
            if is_reference and reference_event and travel_buffer > 0:
                ref_start = datetime.fromisoformat(reference_event['start'])
                filtered_by_buffer = []
                
                if time_relation == "before":
                    # Meeting must END before (reference_start - buffer)
                    cutoff_time = ref_start - timedelta(minutes=travel_buffer)
                    
                    logger.info(f"🔍 Applying buffer filter: slots must end before {cutoff_time.strftime('%I:%M %p')}")
                    emit_deduction(
                        source="Resolve Conflict - Buffer Filter",
                        reasoning=f"Applying {travel_buffer}-minute buffer for reference query. Filtering alternatives to end before {cutoff_time.strftime('%I:%M %p')}.",
                        data={"buffer_minutes": travel_buffer, "cutoff_time": cutoff_time.isoformat(), "reference_event": reference_event.get('summary')}
                    )
                    
                    for slot in same_day_slots:
                        slot_end = datetime.fromisoformat(slot['end'])
                        if slot_end <= cutoff_time:
                            filtered_by_buffer.append(slot)
                    
                    logger.info(f"Filtered {len(same_day_slots)} slots to {len(filtered_by_buffer)} slots ending before cutoff")
                    same_day_slots = filtered_by_buffer
                
                elif time_relation == "after":
                    # Meeting must START after reference event ends (+ buffer)
                    cutoff_time = ref_start + timedelta(minutes=travel_buffer)
                    
                    logger.info(f"🔍 Applying buffer filter: slots must start after {cutoff_time.strftime('%I:%M %p')}")
                    
                    for slot in same_day_slots:
                        slot_start = datetime.fromisoformat(slot['start'])
                        if slot_start >= cutoff_time:
                            filtered_by_buffer.append(slot)
                    
                    logger.info(f"Filtered {len(same_day_slots)} slots to {len(filtered_by_buffer)} slots starting after cutoff")
                    same_day_slots = filtered_by_buffer
            
            # Additional filter: Remove the exact requested time from results (since we know it's blocked)
            if same_day_slots:
                original_time_pref = state.get("time_preference")
                if original_time_pref and ':' in str(original_time_pref):
                    try:
                        req_hour = int(str(original_time_pref).split(':')[0])
                        req_minute = int(str(original_time_pref).split(':')[1]) if ':' in str(original_time_pref) and len(str(original_time_pref).split(':')) > 1 else 0
                        
                        filtered_slots = []
                        for slot in same_day_slots:
                            slot_time = datetime.fromisoformat(slot['start'])
                            # Keep slots that are NOT at the exact requested time
                            if not (slot_time.hour == req_hour and slot_time.minute == req_minute):
                                filtered_slots.append(slot)
                        
                        if filtered_slots:
                            logger.info(f"Removed exact requested time ({req_hour}:{req_minute:02d}) from alternatives")
                            same_day_slots = filtered_slots
                    except Exception as e:
                        logger.warning(f"Could not filter requested time from same-day slots: {e}")
            
            if same_day_slots:
                # Take up to 3 same-day alternatives
                alternatives.extend(same_day_slots[:3])
                logger.info(f"Found {len(same_day_slots)} alternative slots on the same day")
        
        # Strategy 2: Try next day (ONLY if same day has NO alternatives)
        if len(alternatives) == 0 and state.get("preferred_date"):
            next_day = datetime.fromisoformat(state["preferred_date"]) + timedelta(days=1)
            next_day_str = next_day.strftime("%Y-%m-%d")
            
            slots, _ = calendar.find_available_slots(
                date=next_day_str,
                duration_minutes=state.get("meeting_duration_minutes", 60),
                time_preference=state.get("time_preference"),
                timezone=state["timezone"]
            )
            
            if slots:
                # Take up to 2 next-day slots
                alternatives.extend(slots[:2])
                logger.info(f"No same-day alternatives found, suggesting {len(slots)} slots on next day")
        
        # Generate conflict resolution message
        if alternatives:
            slot_descriptions = [f"- {s['start_formatted']} on {s['date_formatted']}" for s in alternatives]
            
            # Store the ORIGINAL requested date before updating
            original_date = state.get("preferred_date", "requested date")
            
            # Preserve the original requested date in a separate field for tracking
            if not state.get("original_requested_date"):
                state["original_requested_date"] = original_date
            
            # Create prompt with ORIGINAL request details
            prompt = CONFLICT_RESOLUTION_PROMPT.format(
                date=original_date,
                time_preference=state.get("time_preference", "requested time"),
                duration=state.get("meeting_duration_minutes", 60),
                reason="All slots are booked"
            )
            
            response = llm.invoke([HumanMessage(content=prompt + "\n\nAlternatives:\n" + "\n".join(slot_descriptions))])
            
            state["messages"].append({
                "role": "assistant",
                "content": response.content
            })
            
            # FIX: Update the preferred_date to match the first alternative slot AFTER creating the message
            if alternatives[0].get('start'):
                new_date = datetime.fromisoformat(alternatives[0]['start']).strftime("%Y-%m-%d")
                state["preferred_date"] = new_date
                logger.info(f"Updated preferred_date from {original_date} to {new_date} to match alternatives")
            
            state["available_slots"] = alternatives
            state["ready_to_book"] = True
        else:
            # No alternatives found
            state["messages"].append({
                "role": "assistant",
                "content": "I couldn't find any available slots in the near future. Would you like me to check a wider time range, or do you have a different timeframe in mind?"
            })
        
        logger.info("Resolved conflict with alternatives")
        
    except Exception as e:
        logger.error(f"Error in resolve_conflict: {e}")
        emit_error("resolve_conflict", e, state)
        state["error_message"] = str(e)
    
    emit_node_exit("resolve_conflict", state)
    return state


def create_event(state: SchedulerState) -> SchedulerState:
    """
    Create the calendar event after user confirmation.
    """
    logger.info("Node: create_event")
    emit_node_enter("create_event", state)
    
    try:
        # Load credentials
        credentials = oauth_manager.load_credentials(state["user_id"])
        calendar = GoogleCalendarTool(credentials)
        
        # Get available slots
        slots = state.get("available_slots", [])
        if not slots:
            state["error_message"] = "No slot selected"
            return state
        
        # Check if user specified a day in their latest message (for multi-day confirmations)
        latest_message = state["messages"][-1]["content"].lower() if state.get("messages") else ""
        day_names = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
        selected_day = None
        
        for day in day_names:
            if day in latest_message:
                selected_day = day
                logger.info(f"📅 User selected specific day: {day}")
                break
        
        # If user selected a specific day, filter slots to that day first
        if selected_day:
            day_filtered_slots = []
            for slot in slots:
                slot_datetime = datetime.fromisoformat(slot['start'])
                slot_day = slot_datetime.strftime("%A").lower()
                if slot_day == selected_day:
                    day_filtered_slots.append(slot)
            
            if day_filtered_slots:
                slots = day_filtered_slots
                logger.info(f"✅ Filtered to {len(slots)} slot(s) on {selected_day}")
            else:
                logger.warning(f"⚠️ No slots found on {selected_day}, using all available slots")
        
        # Match user's requested time preference
        time_preference = state.get("time_preference")
        selected_slot = None
        
        # Log all available slots for debugging
        logger.info(f"🔍 Available slots for selection ({len(slots)} total):")
        for i, slot in enumerate(slots[:10]):  # Log first 10
            slot_dt = datetime.fromisoformat(slot['start'])
            logger.info(f"  [{i}] {slot['start_formatted']} ({slot_dt.strftime('%H:%M')})")
        
        # If user specified a time, try to match it
        if time_preference:
            import re
            # Parse the requested time
            time_str = str(time_preference).strip().upper()
            # Match formats like: 5PM, 5:00PM, 17:00, 5:30 PM, etc.
            match = re.match(r'(\d{1,2}):?(\d{2})?\s*(AM|PM)?', time_str)
            
            if match:
                requested_hour = int(match.group(1))
                requested_minute = int(match.group(2)) if match.group(2) else 0
                am_pm = match.group(3)
                
                # Convert to 24-hour format
                if am_pm == 'PM' and requested_hour != 12:
                    requested_hour += 12
                elif am_pm == 'AM' and requested_hour == 12:
                    requested_hour = 0
                
                logger.info(f"🎯 User requested specific time: {time_preference} → {requested_hour}:{requested_minute:02d} (24-hour format)")
                
                # Try exact match first
                for slot in slots:
                    slot_time = datetime.fromisoformat(slot['start'])
                    if slot_time.hour == requested_hour and slot_time.minute == requested_minute:
                        selected_slot = slot
                        logger.info(f"✅ EXACT MATCH FOUND: {slot['start_formatted']}")
                        break
                
                # If no exact match, check if we should auto-book or ask for confirmation
                if not selected_slot:
                    logger.warning(f"⚠️ No exact match for {requested_hour}:{requested_minute:02d}")
                    
                    # Find slots within 30 minutes for suggestion
                    nearby_slots = []
                    for slot in slots:
                        slot_time = datetime.fromisoformat(slot['start'])
                        slot_total_mins = slot_time.hour * 60 + slot_time.minute
                        requested_total_mins = requested_hour * 60 + requested_minute
                        distance = abs(slot_total_mins - requested_total_mins)
                        
                        if distance <= 30:  # Within 30 minutes
                            nearby_slots.append((slot, distance))
                    
                    # Sort by distance
                    if nearby_slots:
                        nearby_slots.sort(key=lambda x: x[1])
                        
                        # Check if user has already provided a title - if so, auto-book the closest slot
                        has_title = state.get("meeting_title") and state.get("meeting_title") != "Meeting"
                        
                        if has_title:
                            # User already confirmed and provided title - auto-book the closest slot
                            selected_slot = nearby_slots[0][0]  # Get the closest slot
                            closest_distance = nearby_slots[0][1]
                            logger.info(f"✅ AUTO-BOOKING closest slot after title confirmation: {selected_slot['start_formatted']} (distance: {closest_distance} min from requested time)")
                            # Continue to booking below (don't return here)
                        else:
                            # No title yet - present alternatives and ask user to choose
                            # Format alternatives for user (TTS-friendly)
                            alternatives = []
                            for slot, distance in nearby_slots[:3]:  # Show top 3 closest
                                alt_time = slot['start_formatted'].lstrip('0').replace(':00', '')
                                alternatives.append(alt_time)
                            
                            # Join alternatives naturally
                            if len(alternatives) == 2:
                                alt_text = f"{alternatives[0]} or {alternatives[1]}"
                            else:
                                alt_text = ', '.join(alternatives[:-1]) + f", or {alternatives[-1]}"
                            
                            response = f"That time isn't available, but I have {alt_text}. Would any of those work?"
                            
                            logger.warning(f"Found {len(nearby_slots)} nearby slots, asking user to choose")
                            
                            state["messages"].append({
                                "role": "assistant",
                                "content": response
                            })
                            
                            emit_message("assistant", response)
                            
                            # CRITICAL: Reset flags and stay in conversation
                            state["confirmed"] = False
                            state["awaiting_title_input"] = False
                            state["next_action"] = "extract"
                            
                            logger.info("✅ Presented nearby alternatives, waiting for user confirmation - BLOCKING AUTO-BOOK")
                            emit_node_exit("create_event", state)
                            return state
                    else:
                        # No match found - need to search calendar for that specific time
                        logger.warning(f"❌ No slots available near {requested_hour}:{requested_minute:02d}")
                        logger.warning(f"Available slots: {[datetime.fromisoformat(s['start']).strftime('%H:%M') for s in slots]}")
                        
                        # Try to find a slot at the exact requested time
                        date = state.get("preferred_date")
                        duration = state.get("meeting_duration_minutes", 60)
                        
                        if date:
                            logger.info(f"🔄 Re-querying calendar for {requested_hour}:{requested_minute:02d} on {date}")
                            # Format as HH:MM for calendar search
                            specific_time_pref = f"{requested_hour:02d}:{requested_minute:02d}"
                            new_slots, _ = calendar.find_available_slots(
                                date=date,
                                duration_minutes=duration,
                                time_preference=specific_time_pref,
                                timezone=state["timezone"]
                            )
                            
                            if new_slots:
                                # Check if any of these match the requested time
                                for slot in new_slots:
                                    slot_time = datetime.fromisoformat(slot['start'])
                                    if slot_time.hour == requested_hour and slot_time.minute == requested_minute:
                                        selected_slot = slot
                                        logger.info(f"✅ FOUND via re-query: {slot['start_formatted']}")
                                        break
                                
                                # If still no exact match, check if we should auto-book or ask
                                if not selected_slot and new_slots:
                                    logger.warning(f"⚠️ No exact match for {requested_hour}:{requested_minute:02d}")
                                    logger.warning(f"Available alternative slots: {[s['start_formatted'] for s in new_slots[:3]]}")
                                    
                                    # Check if user has already provided a title - if so, auto-book the first/closest slot
                                    has_title = state.get("meeting_title") and state.get("meeting_title") != "Meeting"
                                    
                                    if has_title:
                                        # User already confirmed and provided title - auto-book the first available slot
                                        selected_slot = new_slots[0]
                                        logger.info(f"✅ AUTO-BOOKING first available slot after title confirmation: {selected_slot['start_formatted']}")
                                        # Continue to booking below (don't return here)
                                    else:
                                        # No title yet - return to conversation with alternatives
                                        state["available_slots"] = new_slots
                                        
                                        # Format alternatives nicely
                                        alternatives = []
                                        for slot in new_slots[:3]:  # Show top 3 alternatives
                                            alt_time = slot['start_formatted'].lstrip('0').replace(':00', '')
                                            alternatives.append(alt_time)
                                        
                                        # Join alternatives naturally
                                        if len(alternatives) == 2:
                                            alt_text = f"{alternatives[0]} or {alternatives[1]}"
                                        else:
                                            alt_text = ', '.join(alternatives[:-1]) + f", or {alternatives[-1]}"
                                        
                                        response = f"That time isn't available. I have {alt_text}. Which would you prefer?"
                                        
                                        state["messages"].append({
                                            "role": "assistant",
                                            "content": response
                                        })
                                        
                                        emit_message("assistant", response)
                                        
                                        # Reset confirmation flags and stay in conversation
                                        state["confirmed"] = False
                                        state["awaiting_title_input"] = False
                                        state["next_action"] = "extract"
                                        
                                        logger.info("✅ Presented alternatives to user, waiting for selection")
                                        emit_node_exit("create_event", state)
                                        return state
        
        # CRITICAL: Check if we should auto-select or ask user
        if not selected_slot and time_preference:
            # Check if user has already provided a title - if so, auto-book the first available slot
            has_title = state.get("meeting_title") and state.get("meeting_title") != "Meeting"
            
            if has_title and slots:
                # User already confirmed and provided title - auto-book the first available slot
                selected_slot = slots[0]
                logger.info(f"✅ AUTO-BOOKING first available slot after title confirmation: {selected_slot['start_formatted']} (user requested {time_preference})")
                # Continue to booking below (don't return here)
            else:
                # No title yet or no slots - ask user to choose
                logger.error(f"❌ BLOCKING AUTO-BOOK: User requested {time_preference} but no match found")
                
                # Format available times for user (TTS-friendly)
                available_times = [datetime.fromisoformat(s['start']).strftime('%I:%M %p').lstrip('0').replace(':00', '') for s in slots[:5]]
                
                # Join times naturally
                if len(available_times) == 2:
                    times_text = f"{available_times[0]} or {available_times[1]}"
                else:
                    times_text = ', '.join(available_times[:-1]) + f", or {available_times[-1]}"
                
                response = f"That time isn't available. I have {times_text}. Which would you prefer?"
                
                state["messages"].append({
                    "role": "assistant",
                    "content": response
                })
                
                emit_message("assistant", response)
                
                # Reset confirmation and stay in conversation
                state["confirmed"] = False
                state["awaiting_title_input"] = False
                state["next_action"] = "extract"
                
                logger.info("✅ Asked user to choose from available times")
                emit_node_exit("create_event", state)
                return state
        
        # If still no slot selected AND no specific time was requested, use the first available
        if not selected_slot:
            selected_slot = slots[0]
            logger.info(f"📌 No specific time requested, using first available slot: {selected_slot['start_formatted']}")
        
        # Parse times and ensure they're timezone-aware (IST)
        import pytz
        tz = pytz.timezone(state["timezone"])
        
        start_time = datetime.fromisoformat(selected_slot["start"])
        end_time = datetime.fromisoformat(selected_slot["end"])
        
        # Ensure timezone awareness - if naive, localize to IST
        if start_time.tzinfo is None:
            start_time = tz.localize(start_time)
        else:
            # Convert to IST if it's in a different timezone
            start_time = start_time.astimezone(tz)
            
        if end_time.tzinfo is None:
            end_time = tz.localize(end_time)
        else:
            end_time = end_time.astimezone(tz)
        
        logger.info(f"📅 Creating event in {state['timezone']}: {start_time.isoformat()} to {end_time.isoformat()}")
        
        # Create event
        title = state.get("meeting_title") or "Meeting"
        description = state.get("meeting_description") or "Scheduled by Smart Scheduler AI"
        
        event = calendar.create_event(
            summary=title,
            start_time=start_time,
            end_time=end_time,
            description=description,
            timezone=state["timezone"]
        )
        
        logger.info(f"✅ Event created successfully: {title} at {start_time.strftime('%Y-%m-%d %H:%M IST')}")
        
        # ============================================================================
        # AUTO-REFRESH CALENDAR CONTEXT after booking
        # ============================================================================
        # Refresh the calendar context so LLM sees the newly created event
        # This enables users to schedule additional meetings relative to this one
        logger.info("🔄 Auto-refreshing calendar context after successful booking...")
        state = refresh_calendar_context(state)
        logger.info("✅ Calendar context refreshed - LLM now aware of newly created event")
        # ============================================================================
        
        # Confirmation message (TTS-friendly, no emojis)
        duration_mins = state.get('meeting_duration_minutes', 60)
        # Convert duration to natural speech
        if duration_mins == 60:
            duration_text = "one hour"
        elif duration_mins == 30:
            duration_text = "thirty minutes"
        elif duration_mins == 90:
            duration_text = "an hour and thirty minutes"
        elif duration_mins == 120:
            duration_text = "two hours"
        else:
            duration_text = f"{duration_mins} minutes"
        
        confirmation = f"All set! I've scheduled {title} for {selected_slot['start_formatted']} on {selected_slot['date_formatted']}. The meeting is {duration_text} long."
        
        state["messages"].append({
            "role": "assistant",
            "content": confirmation
        })
        
        state["confirmed"] = True
        state["next_action"] = "complete"
        
        # ============================================================================
        # BOOKING CONFIRMATION FLAG: Signal to frontend that booking is complete
        # ============================================================================
        # Set this flag to true ONLY when a booking is successfully created
        # Frontend will check for this flag to show the booking confirmation dialog
        state["booking_confirmed"] = True
        
        # ============================================================================
        # SOFT RESET: Store completed booking and mark conversation phase
        # ============================================================================
        # Store details of this completed booking so we can provide context later
        # Use IST timezone for timestamp
        ist_tz = pytz.timezone('Asia/Kolkata')
        state["last_completed_booking"] = {
            "title": title,
            "date": selected_slot['date_formatted'],
            "time": selected_slot['start_formatted'],
            "duration": state.get('meeting_duration_minutes', 60),
            "timestamp": datetime.now(ist_tz).isoformat()
        }
        # Mark phase as post_confirmation so next user message triggers soft reset
        state["conversation_phase"] = "post_confirmation"
        
        logger.info(f"Created calendar event: {title}")
        logger.info(f"✅ Booking completed. Marked conversation_phase as 'post_confirmation' for soft reset on next message.")
        
    except Exception as e:
        logger.error(f"Error in create_event: {e}")
        emit_error("create_event", e, state)
        state["error_message"] = str(e)
        state["messages"].append({
            "role": "assistant",
            "content": f"Sorry, I encountered an error creating the event: {str(e)}"
        })
    
    emit_node_exit("create_event", state)
    return state


def clarify(state: SchedulerState) -> SchedulerState:
    """
    Ask clarifying questions when information is missing.
    """
    logger.info("Node: clarify")
    emit_node_enter("clarify", state)
    
    try:
        # Determine what's missing
        missing = []
        
        if not state.get("meeting_duration_minutes"):
            missing.append("duration")
        
        # Do not ask for a date if:
        # 1. It's a reference query, OR
        # 2. It's a multi-day search with date range already set
        is_multi_day_with_range = state.get("multi_day_search") and state.get("date_range_start") and state.get("date_range_end")
        
        if not state.get("preferred_date") and not state.get("is_reference_query") and not is_multi_day_with_range:
            missing.append("date")
        
        # Don't ask for time preference if:
        # 1. It's a multi-day search with time constraints already set (earliest_time/latest_time)
        has_time_constraints = state.get("earliest_time") or state.get("latest_time")
        
        if not state.get("time_preference") and not is_multi_day_with_range and not has_time_constraints:
            missing.append("time preference")
        
        # Check for ambiguous date that needs clarification
        ambiguous_date_phrase = None
        messages = state.get("messages") or []
        if messages:
            # Check last few messages for ambiguous date indicators
            for msg in reversed(messages[-3:]):  # Check last 3 messages
                if msg.get("role") == "user":
                    content_lower = msg.get("content", "").lower()
                    # Look for ambiguous date phrases
                    if "late next week" in content_lower:
                        ambiguous_date_phrase = "late next week"
                        state["week_context"] = "next_week"  # Store context for later use
                        break
                    elif "early next week" in content_lower:
                        ambiguous_date_phrase = "early next week"
                        state["week_context"] = "next_week"
                        break
                    elif "mid week" in content_lower or "midweek" in content_lower:
                        ambiguous_date_phrase = "mid-week"
                        break
                    elif "sometime next week" in content_lower:
                        ambiguous_date_phrase = "sometime next week"
                        state["week_context"] = "next_week"
                        break
                    elif "end of the month" in content_lower or "end of month" in content_lower:
                        ambiguous_date_phrase = "end of the month"
                        break
                    elif "early next month" in content_lower:
                        ambiguous_date_phrase = "early next month"
                        break
        
        # Generate clarification question
        question = None
        if missing:
            if ambiguous_date_phrase and "date" in missing:
                # Generate smart clarifying question for ambiguous dates
                if ambiguous_date_phrase == "late next week":
                    question = "By late next week, do you mean Thursday or Friday?"
                elif ambiguous_date_phrase == "early next week":
                    question = "By early next week, do you mean Monday or Tuesday?"
                elif ambiguous_date_phrase == "mid-week" or ambiguous_date_phrase == "midweek":
                    question = "By mid-week, do you mean Tuesday, Wednesday, or Thursday?"
                elif ambiguous_date_phrase == "sometime next week":
                    question = "Which day next week works best for you?"
                elif ambiguous_date_phrase == "end of the month":
                    question = "Which day at the end of the month would work best?"
                elif ambiguous_date_phrase == "early next month":
                    question = "Which day early next month would you prefer?"
                else:
                    question = "What day would you like to schedule this?"
                
                emit_deduction(
                    source="Ambiguous Date Clarification",
                    reasoning=f"User said '{ambiguous_date_phrase}' which is ambiguous. Asking for specific clarification.",
                    data={"ambiguous_phrase": ambiguous_date_phrase, "question": question}
                )
            elif "duration" in missing:
                question = "How long should the meeting be?"
            elif "date" in missing:
                question = "What day would you like to schedule this?"
            elif "time preference" in missing:
                question = "What time works best for you? Morning, afternoon, or do you have a specific time in mind?"
            else:
                question = "Could you provide more details about when you'd like to meet?"
            
            if question:
                state["clarification_question"] = question
                if "messages" not in state or state["messages"] is None:
                    state["messages"] = []
                state["messages"].append({
                    "role": "assistant",
                    "content": question
                })
        
        state["next_action"] = "extract"
        
    except Exception as e:
        logger.error(f"Error in clarify: {e}")
        emit_error("clarify", e, state)
        state["error_message"] = str(e)
    
    emit_node_exit("clarify", state)
    return state
