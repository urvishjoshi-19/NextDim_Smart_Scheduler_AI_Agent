from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Tuple
import pytz
import re

from ..utils.logger import logger

class ValidationResult:
    def __init__(self, is_valid: bool, error_type: Optional[str] = None, clarification_question: Optional[str] = None, suggestion: Optional[str] = None):
        self.is_valid = is_valid
        self.error_type = error_type
        self.clarification_question = clarification_question
        self.suggestion = suggestion

class EdgeCaseValidator:
    MAX_REASONABLE_DURATION = 480
    LONG_DURATION_THRESHOLD = 240
    
    def __init__(self, timezone: str = 'Asia/Kolkata'):
        self.timezone = pytz.timezone(timezone)
        self.now = datetime.now(self.timezone)
    
    def validate_date(self, date_obj: datetime, date_string: str) -> ValidationResult:
        if not date_obj:
            return ValidationResult(is_valid=True)
        
        if date_obj.tzinfo is None:
            date_obj = self.timezone.localize(date_obj)
        
        date_only = date_obj.replace(hour=0, minute=0, second=0, microsecond=0)
        now_date = self.now.replace(hour=0, minute=0, second=0, microsecond=0)
        
        if date_only < now_date:
            logger.warning(f"Past date detected: {date_obj.strftime('%A, %B %d, %Y')}")
            
            date_lower = date_string.lower()
            explicit_past = any(word in date_lower for word in ['last', 'past', 'yesterday', 'previous'])
            
            if explicit_past:
                day_name = date_obj.strftime('%A')
                
                clarification = f"I can only schedule future events. Did you mean next {day_name}?"
                suggestion = f"next {day_name.lower()}"
                
                logger.info(f"Suggesting correction: '{date_string}' → '{suggestion}'")
                
                return ValidationResult(
                    is_valid=False,
                    error_type="past_date",
                    clarification_question=clarification,
                    suggestion=suggestion
                )
            else:
                clarification = f"That date ({date_obj.strftime('%B %d')}) has already passed. Did you mean a future date?"
                
                return ValidationResult(
                    is_valid=False,
                    error_type="past_date",
                    clarification_question=clarification,
                    suggestion=None
                )
        
        return ValidationResult(is_valid=True)
    
    def validate_duration(self, duration_minutes: int, duration_string: str) -> ValidationResult:
        if not duration_minutes or duration_minutes <= 0:
            return ValidationResult(is_valid=True)
        
        if duration_minutes > self.MAX_REASONABLE_DURATION:
            hours = duration_minutes / 60
            logger.warning(f"Unrealistic duration: {duration_minutes} minutes")
            
            suggestion = None
            if duration_minutes == 600:
                suggestion = "1 hour"
            elif duration_minutes >= 480:
                hours_int = int(hours)
                suggestion = f"{hours_int // 2} hours"
            
            if suggestion:
                clarification = f"{int(hours)} hours is quite long — did you mean {suggestion}?"
            else:
                clarification = f"{int(hours)} hours is quite long — did you mean {int(hours)} minutes or 1 hour?"
            
            return ValidationResult(
                is_valid=False,
                error_type="unrealistic_duration",
                clarification_question=clarification,
                suggestion=suggestion
            )
        
        elif duration_minutes >= self.LONG_DURATION_THRESHOLD:
            hours = duration_minutes / 60
            clarification = f"{int(hours)} hours is quite long. Is that correct?"
            
            return ValidationResult(
                is_valid=False,
                error_type="long_duration",
                clarification_question=clarification,
                suggestion=None
            )
        
        return ValidationResult(is_valid=True)
    
    def validate_time(self, time_string: str, message: str) -> ValidationResult:
        if not message:
            return ValidationResult(is_valid=True)
        
        message_lower = message.lower()
        
        invalid_patterns = [
            (r'(\d+)\s*o[\'\']?\s*clock', lambda m: int(m.group(1)) > 24 or int(m.group(1)) == 0),
            (r'(?<![:\d])(\d+)\s*(?:pm|am)(?!\d)', lambda m: int(m.group(1)) > 12 or int(m.group(1)) == 0),
            (r'(\d+):(\d+)', lambda m: int(m.group(1)) >= 24 or int(m.group(2)) >= 60),
        ]
        
        for pattern, validator in invalid_patterns:
            match = re.search(pattern, message_lower)
            if match:
                if validator(match):
                    invalid_time = match.group(0)
                    logger.warning(f"Invalid time format: '{invalid_time}'")
                    
                    clarification = "I didn't catch that time. Could you say '2 PM' or '14:00'?"
                    
                    return ValidationResult(
                        is_valid=False,
                        error_type="invalid_time",
                        clarification_question=clarification,
                        suggestion="2 PM or 14:00"
                    )
        
        if not time_string:
            time_indicators = ['at', 'around', 'about', 'approximately']
            has_time_indicator = any(indicator in message_lower for indicator in time_indicators)
            
            if has_time_indicator:
                number_match = re.search(r'(?:at|around|about)\s+(\d+)(?:\s|$|\.)', message_lower)
                if number_match:
                    number = int(number_match.group(1))
                    if number > 24 or number == 0:
                        logger.warning(f"Invalid time reference: '{number}'")
                        
                        clarification = "I didn't catch that time. Could you say '2 PM' or '14:00'?"
                        
                        return ValidationResult(
                            is_valid=False,
                            error_type="invalid_time",
                            clarification_question=clarification,
                            suggestion="2 PM or 14:00"
                        )
        
        return ValidationResult(is_valid=True)
    
    def validate_all(self, date_obj: Optional[datetime], date_string: str, duration_minutes: Optional[int], duration_string: str, time_string: Optional[str], message: str) -> Tuple[bool, Optional[str], Optional[str]]:
        time_result = self.validate_time(time_string, message)
        if not time_result.is_valid:
            return False, time_result.error_type, time_result.clarification_question
        
        if date_obj:
            date_result = self.validate_date(date_obj, date_string)
            if not date_result.is_valid:
                return False, date_result.error_type, date_result.clarification_question
        
        if duration_minutes:
            duration_result = self.validate_duration(duration_minutes, duration_string)
            if not duration_result.is_valid:
                return False, duration_result.error_type, duration_result.clarification_question
        
        return True, None, None

