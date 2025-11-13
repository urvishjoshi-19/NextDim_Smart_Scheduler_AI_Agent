from typing import TypedDict, Optional, List, Dict, Any, Annotated
from datetime import datetime
import operator


class SchedulerState(TypedDict):
    messages: Annotated[List[Dict[str, str]], operator.add]
    user_id: str
    timezone: str
    calendar_context: Optional[str]
    calendar_events_raw: Optional[List[Dict[str, Any]]]
    calendar_loaded: bool
    calendar_date_range: Optional[Dict[str, str]]
    meeting_duration_minutes: Optional[int]
    preferred_date: Optional[str]
    original_requested_date: Optional[str]
    preferred_time: Optional[str]
    time_preference: Optional[str]
    meeting_title: Optional[str]
    meeting_description: Optional[str]
    negative_days: Optional[List[str]]
    earliest_time: Optional[str]
    latest_time: Optional[str]
    multi_day_search: bool
    date_range_start: Optional[str]
    date_range_end: Optional[str]
    available_slots: Optional[List[Dict[str, Any]]]
    conflicting_events: Optional[List[Dict[str, Any]]]
    partial_gap_at_requested_time: Optional[Dict[str, Any]]
    reference_event_name: Optional[str]
    reference_event_time: Optional[datetime]
    reference_event_details: Optional[Dict[str, Any]]
    time_relation: Optional[str]
    buffer_minutes: Optional[int]
    buffer_after_last_meeting: Optional[int]
    buffer_before_next_meeting: Optional[int]
    is_reference_query: bool
    needs_clarification: bool
    clarification_question: Optional[str]
    ready_to_book: bool
    confirmed: bool
    awaiting_title_input: bool
    cancelled: bool
    cancelled_params: Optional[Dict[str, Any]]
    last_completed_booking: Optional[Dict[str, Any]]
    conversation_phase: Optional[str]
    next_action: Optional[str]
    error_message: Optional[str]
    retry_count: int


class ConversationMessage(TypedDict):
    role: str
    content: str
    timestamp: datetime


def create_initial_state(user_id: str, timezone: str = "Asia/Kolkata") -> SchedulerState:
    return SchedulerState(
        messages=[],
        user_id=user_id,
        timezone=timezone,
        calendar_context=None,
        calendar_events_raw=None,
        calendar_loaded=False,
        calendar_date_range=None,
        meeting_duration_minutes=None,
        preferred_date=None,
        original_requested_date=None,
        preferred_time=None,
        time_preference=None,
        meeting_title=None,
        meeting_description=None,
        negative_days=None,
        earliest_time=None,
        latest_time=None,
        multi_day_search=False,
        date_range_start=None,
        date_range_end=None,
        available_slots=None,
        conflicting_events=None,
        partial_gap_at_requested_time=None,
        reference_event_name=None,
        reference_event_time=None,
        reference_event_details=None,
        time_relation=None,
        buffer_minutes=None,
        buffer_after_last_meeting=None,
        buffer_before_next_meeting=None,
        is_reference_query=False,
        needs_clarification=False,
        clarification_question=None,
        ready_to_book=False,
        confirmed=False,
        awaiting_title_input=False,
        cancelled=False,
        cancelled_params=None,
        last_completed_booking=None,
        conversation_phase=None,
        next_action="extract",
        error_message=None,
        retry_count=0
    )
