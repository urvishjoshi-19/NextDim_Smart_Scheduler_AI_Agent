import logging
import asyncio
from typing import Optional
from fastapi import WebSocket


class WebSocketLogHandler(logging.Handler):
    def __init__(self, websocket: WebSocket):
        super().__init__()
        self.websocket = websocket
        self.loop = None
        
    def set_event_loop(self, loop):
        self.loop = loop
        
    def emit(self, record):
        try:
            log_message = self.format(record)
            
            level_map = {
                'DEBUG': 'info',
                'INFO': 'info',
                'WARNING': 'warning',
                'ERROR': 'error',
                'CRITICAL': 'error'
            }
            level = level_map.get(record.levelname, 'info')
            
            message_data = {
                "type": "log",
                "level": level,
                "message": log_message
            }
            
            if self.loop and not self.loop.is_closed():
                asyncio.run_coroutine_threadsafe(
                    self.websocket.send_json(message_data),
                    self.loop
                )
        except Exception:
            pass


def attach_websocket_logger(websocket: WebSocket, logger_name: str = "smart_scheduler") -> WebSocketLogHandler:
    logger = logging.getLogger(logger_name)
    
    handler = WebSocketLogHandler(websocket)
    handler.setLevel(logging.INFO)
    
    try:
        loop = asyncio.get_event_loop()
        handler.set_event_loop(loop)
    except RuntimeError:
        pass
    
    logger.addHandler(handler)
    return handler


def detach_websocket_logger(handler: WebSocketLogHandler, logger_name: str = "smart_scheduler"):
    logger = logging.getLogger(logger_name)
    logger.removeHandler(handler)

