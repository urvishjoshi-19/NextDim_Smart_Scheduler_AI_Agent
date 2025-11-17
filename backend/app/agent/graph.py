from langgraph.graph import StateGraph, END
from typing import Literal

from .state import SchedulerState, create_initial_state
from .nodes import (
    extract_requirements,
    query_calendar,
    suggest_times,
    resolve_conflict,
    create_event,
    clarify
)
from ..utils.logger import logger


def should_query_calendar(state: SchedulerState) -> Literal["query_calendar", "clarify", "create_event", END]:
    if state.get("confirmed"):
        logger.info("Routing: extract -> create_event (user confirmed)")
        return "create_event"
    
    # When awaiting title input, the message has been added - END workflow to wait for user response
    if state.get("awaiting_title_input"):
        logger.info("Routing: extract -> END (awaiting title input - message already sent)")
        return END
    
    if state.get("cancelled") and state.get("next_action") == "respond":
        logger.info("Routing: extract -> END (user cancelled)")
        return END
    
    has_duration = state.get("meeting_duration_minutes") is not None
    has_date = state.get("preferred_date") is not None
    has_date_range = state.get("date_range_start") is not None and state.get("date_range_end") is not None
    has_date_info = has_date or has_date_range
    
    if state.get("is_reference_query") and has_duration:
        logger.info("Routing: extract -> query_calendar (reference query)")
        return "query_calendar"
    
    if state.get("multi_day_search") and has_date_range and has_duration:
        logger.info("Routing: extract -> query_calendar (multi-day search)")
        return "query_calendar"
    
    if has_duration and has_date_info:
        logger.info("Routing: extract -> query_calendar")
        return "query_calendar"
    else:
        logger.info(f"Routing: extract -> clarify")
        return "clarify"


from langgraph.graph import StateGraph, END
from typing import Literal

from .state import SchedulerState, create_initial_state
from .nodes import (
    extract_requirements,
    query_calendar,
    suggest_times,
    resolve_conflict,
    create_event,
    clarify
)
from ..utils.logger import logger


def should_query_calendar(state: SchedulerState) -> Literal["query_calendar", "clarify", "create_event", END]:
    if state.get("confirmed"):
        logger.info("Routing: extract -> create_event")
        return "create_event"
    
    if state.get("awaiting_title_input"):
        logger.info("Routing: extract -> END")
        return END
    
    if state.get("cancelled") and state.get("next_action") == "respond":
        logger.info("Routing: extract -> END")
        return END
    
    has_duration = state.get("meeting_duration_minutes") is not None
    has_date = state.get("preferred_date") is not None
    has_date_range = state.get("date_range_start") is not None and state.get("date_range_end") is not None
    has_date_info = has_date or has_date_range
    
    if state.get("is_reference_query") and has_duration:
        logger.info("Routing: extract -> query_calendar")
        return "query_calendar"
    
    if state.get("multi_day_search") and has_date_range and has_duration:
        logger.info("Routing: extract -> query_calendar")
        return "query_calendar"
    
    if has_duration and has_date_info:
        logger.info("Routing: extract -> query_calendar")
        return "query_calendar"
    else:
        logger.info("Routing: extract -> clarify")
        return "clarify"


def handle_calendar_results(state: SchedulerState) -> Literal["suggest", "resolve_conflict"]:
    slots = state.get("available_slots", [])
    
    if slots:
        logger.info("Routing: query_calendar -> suggest")
        return "suggest"
    else:
        logger.info("Routing: query_calendar -> resolve_conflict")
        return "resolve_conflict"


def after_suggestion(state: SchedulerState) -> Literal["create_event", "extract", END]:
    """
    After suggesting times, END to wait for user's next message.
    When user responds, a new workflow invocation will start from extract.
    """
    if state.get("confirmed"):
        logger.info("Routing: suggest -> create_event (user confirmed)")
        return "create_event"
    
    # 🎯 Route to END to finish this workflow cycle and wait for user response
    # The next user message will start a NEW workflow invocation
    logger.info("Routing: suggest -> END (waiting for user selection)")
    return END


def after_create_event(state: SchedulerState) -> Literal["extract", END]:
    if state.get("messages"):
        latest = state["messages"][-1]["content"].lower()
        
        if any(word in latest for word in ["another", "also", "more", "else"]):
            logger.info("Routing: create_event -> extract")
            return "extract"
    
    logger.info("Routing: create_event -> END")
    return END


def create_scheduling_agent():
    workflow = StateGraph(SchedulerState)
    
    workflow.add_node("extract", extract_requirements)
    workflow.add_node("query_calendar", query_calendar)
    workflow.add_node("suggest", suggest_times)
    workflow.add_node("resolve_conflict", resolve_conflict)
    workflow.add_node("create_event", create_event)
    workflow.add_node("clarify", clarify)
    
    workflow.set_entry_point("extract")
    
    workflow.add_conditional_edges(
        "extract",
        should_query_calendar,
        {
            "query_calendar": "query_calendar",
            "clarify": "clarify",
            "create_event": "create_event",
            END: END
        }
    )
    
    workflow.add_conditional_edges(
        "query_calendar",
        handle_calendar_results,
        {
            "suggest": "suggest",
            "resolve_conflict": "resolve_conflict"
        }
    )
    
    workflow.add_conditional_edges(
        "suggest",
        after_suggestion,
        {
            "create_event": "create_event",
            "extract": "extract",
            END: END
        }
    )
    
    workflow.add_conditional_edges(
        "create_event",
        after_create_event,
        {
            "extract": "extract",
            END: END
        }
    )
    
    # These nodes send responses and END to wait for next user input
    workflow.add_edge("clarify", END)
    workflow.add_edge("resolve_conflict", END)
    
    app = workflow.compile()
    logger.info("Compiled scheduling agent workflow")
    return app


scheduling_agent = create_scheduling_agent()


def run_agent(user_id: str, user_message: str, timezone: str = "Asia/Kolkata") -> str:
    state = create_initial_state(user_id, timezone)
    
    state["messages"].append({
        "role": "user",
        "content": user_message
    })
    
    result = scheduling_agent.invoke(state)
    
    if result["messages"]:
        for msg in reversed(result["messages"]):
            if msg["role"] == "assistant":
                return msg["content"]
    
    return "I'm here to help you schedule meetings. What would you like to schedule?"


def run_agent_stream(user_id: str, user_message: str, timezone: str = "Asia/Kolkata"):
    state = create_initial_state(user_id, timezone)
    
    state["messages"].append({
        "role": "user",
        "content": user_message
    })
    
    for update in scheduling_agent.stream(state):
        yield update
