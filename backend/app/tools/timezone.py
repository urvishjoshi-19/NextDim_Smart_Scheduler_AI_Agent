import pytz
from typing import Optional
from datetime import datetime

from ..utils.logger import logger


class TimezoneManager:
    TIMEZONE_ABBREV = {
        'PST': 'America/Los_Angeles',
        'PDT': 'America/Los_Angeles',
        'EST': 'America/New_York',
        'EDT': 'America/New_York',
        'CST': 'America/Chicago',
        'CDT': 'America/Chicago',
        'MST': 'America/Denver',
        'MDT': 'America/Denver',
        'GMT': 'GMT',
        'UTC': 'UTC',
        'IST': 'Asia/Kolkata',
    }
    
    @staticmethod
    def detect_timezone_from_text(text: str) -> Optional[str]:
        text_upper = text.upper()
        
        for abbrev, full_tz in TimezoneManager.TIMEZONE_ABBREV.items():
            if abbrev in text_upper:
                logger.info(f"Detected timezone {full_tz} from text")
                return full_tz
        
        return None
    
    @staticmethod
    def get_user_timezone(user_input: Optional[str] = None, default: str = 'UTC') -> str:
        if user_input:
            detected = TimezoneManager.detect_timezone_from_text(user_input)
            if detected:
                return detected
        
        return default
    
    @staticmethod
    def convert_time(dt: datetime, from_tz: str, to_tz: str) -> datetime:
        from_zone = pytz.timezone(from_tz)
        to_zone = pytz.timezone(to_tz)
        
        if dt.tzinfo is None:
            dt = from_zone.localize(dt)
        
        return dt.astimezone(to_zone)
    
    @staticmethod
    def format_time_with_timezone(dt: datetime, timezone: str) -> str:
        tz = pytz.timezone(timezone)
        local_time = dt.astimezone(tz)
        tz_abbrev = local_time.strftime('%Z')
        return local_time.strftime(f'%I:%M %p {tz_abbrev}')

