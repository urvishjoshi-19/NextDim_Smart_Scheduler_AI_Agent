from typing import Dict, Any, List, Callable
import asyncio
from datetime import datetime
import json

from .logger import logger


class DebugEventEmitter:
    def __init__(self):
        self.listeners: List[Callable] = []
        self.event_history: List[Dict[str, Any]] = []
        self.max_history = 100
    
    def add_listener(self, callback: Callable):
        self.listeners.append(callback)
    
    def remove_listener(self, callback: Callable):
        if callback in self.listeners:
            self.listeners.remove(callback)
    
    async def emit(self, event_type: str, data: Dict[str, Any]):
        event = {
            "type": event_type,
            "timestamp": datetime.utcnow().isoformat(),
            "data": data
        }
        
        self.event_history.append(event)
        if len(self.event_history) > self.max_history:
            self.event_history.pop(0)
        
        for listener in self.listeners:
            try:
                if asyncio.iscoroutinefunction(listener):
                    await listener(event)
                else:
                    listener(event)
            except Exception as e:
                logger.error(f"Error in debug event listener: {e}")
    
    def get_history(self) -> List[Dict[str, Any]]:
        return self.event_history.copy()


debug_emitter = DebugEventEmitter()


def emit_node_enter(node_name: str, state: Dict[str, Any]):
    messages = state.get("messages") or []
    slots = state.get("available_slots") or []
    
    asyncio.create_task(debug_emitter.emit("node_enter", {
        "node": node_name,
        "state_summary": {
            "duration": state.get("meeting_duration_minutes"),
            "date": state.get("preferred_date"),
            "original_requested_date": state.get("original_requested_date"),
            "time": state.get("time_preference"),
            "messages_count": len(messages),
            "slots_count": len(slots),
            "ready_to_book": state.get("ready_to_book"),
            "confirmed": state.get("confirmed")
        }
    }))


def emit_node_exit(node_name: str, state: Dict[str, Any]):
    messages = state.get("messages") or []
    slots = state.get("available_slots") or []
    
    asyncio.create_task(debug_emitter.emit("node_exit", {
        "node": node_name,
        "state_summary": {
            "duration": state.get("meeting_duration_minutes"),
            "date": state.get("preferred_date"),
            "original_requested_date": state.get("original_requested_date"),
            "time": state.get("time_preference"),
            "messages_count": len(messages),
            "slots_count": len(slots),
            "ready_to_book": state.get("ready_to_book"),
            "confirmed": state.get("confirmed")
        }
    }))


def emit_error(node_name: str, error: Exception, state: Dict[str, Any]):
    asyncio.create_task(debug_emitter.emit("error", {
        "node": node_name,
        "error_type": type(error).__name__,
        "error_message": str(error),
        "state_summary": {
            "duration": state.get("meeting_duration_minutes"),
            "date": state.get("preferred_date"),
            "time": state.get("time_preference"),
        }
    }))


def emit_routing(from_node: str, to_node: str, reason: str = ""):
    asyncio.create_task(debug_emitter.emit("routing", {
        "from": from_node,
        "to": to_node,
        "reason": reason
    }))


def emit_message(role: str, content: str):
    asyncio.create_task(debug_emitter.emit("message", {
        "role": role,
        "content": content[:200]
    }))


def emit_calendar_query(query_details: dict):
    asyncio.create_task(debug_emitter.emit("calendar_query", query_details))


def emit_calendar_events(events: list):
    asyncio.create_task(debug_emitter.emit("calendar_events", {
        "count": len(events),
        "events": events
    }))


def emit_availability_check(check_details: dict):
    asyncio.create_task(debug_emitter.emit("availability_check", check_details))


def emit_raw_calendar_data(source: str, data: any):
    asyncio.create_task(debug_emitter.emit("raw_calendar_data", {
        "source": source,
        "data": data
    }))


def emit_deduction(source: str, reasoning: str, data: any = None):
    asyncio.create_task(debug_emitter.emit("deduction", {
        "source": source,
        "reasoning": reasoning,
        "data": data
    }))

