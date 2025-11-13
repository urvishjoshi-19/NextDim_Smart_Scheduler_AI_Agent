from datetime import datetime, timedelta
from typing import Optional, Tuple
from dateutil import parser, relativedelta
import pytz
import calendar
import re

from ..utils.logger import logger


def parse_word_number(text: str) -> Optional[int]:
    text_lower = text.lower().strip()
    
    ones = {
        'zero': 0, 'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5,
        'six': 6, 'seven': 7, 'eight': 8, 'nine': 9, 'ten': 10,
        'eleven': 11, 'twelve': 12, 'thirteen': 13, 'fourteen': 14, 'fifteen': 15,
        'sixteen': 16, 'seventeen': 17, 'eighteen': 18, 'nineteen': 19
    }
    
    tens = {
        'twenty': 20, 'thirty': 30, 'forty': 40, 'fifty': 50,
        'sixty': 60, 'seventy': 70, 'eighty': 80, 'ninety': 90
    }
    
    hundreds = {
        'hundred': 100, 'one hundred': 100, 'two hundred': 200, 'three hundred': 300
    }
    
    if text_lower in ones:
        return ones[text_lower]
    
    if text_lower in tens:
        return tens[text_lower]
    
    if text_lower in hundreds:
        return hundreds[text_lower]
    
    for ten_word, ten_val in tens.items():
        for one_word, one_val in ones.items():
            if one_val == 0:
                continue
            compound_space = f"{ten_word} {one_word}"
            compound_hyphen = f"{ten_word}-{one_word}"
            
            if text_lower == compound_space or text_lower == compound_hyphen:
                return ten_val + one_val
            
            compound_and = f"{ten_word} and {one_word}"
            if text_lower == compound_and:
                return ten_val + one_val
    
    hundred_pattern = r'(\w+)\s+hundred(?:\s+and)?\s+(.+)'
    match = re.match(hundred_pattern, text_lower)
    if match:
        hundred_word = match.group(1)
        remainder = match.group(2)
        
        if hundred_word in ones:
            hundred_val = ones[hundred_word] * 100
            remainder_val = parse_word_number(remainder)
            if remainder_val is not None:
                return hundred_val + remainder_val
            return hundred_val
    
    return None


class TimeParser:
    WEEKDAYS = {
        'monday': 0, 'mon': 0,
        'tuesday': 1, 'tue': 1, 'tues': 1,
        'wednesday': 2, 'wed': 2,
        'thursday': 3, 'thu': 3, 'thur': 3, 'thurs': 3,
        'friday': 4, 'fri': 4,
        'saturday': 5, 'sat': 5,
        'sunday': 6, 'sun': 6
    }
    
    TIME_OF_DAY = {
        'morning': (8, 12),
        'afternoon': (12, 17),
        'evening': (17, 21),
        'night': (21, 23)
    }
    
    def __init__(self, timezone: str = 'Asia/Kolkata'):
        self.timezone = pytz.timezone(timezone)
        self.now = datetime.now(self.timezone)
    
    def parse_date(self, date_string: str) -> Optional[datetime]:
        date_lower = date_string.lower().strip()
        
        if 'today' in date_lower:
            return self.now
        
        if 'tomorrow' in date_lower:
            return self.now + timedelta(days=1)
        
        if 'yesterday' in date_lower:
            return self.now - timedelta(days=1)
        
        if 'last weekday of' in date_lower or 'last working day of' in date_lower:
            logger.info(f"Detected 'last weekday of month' pattern")
            return self._get_last_weekday_of_month(date_lower)
        
        if any(pattern in date_lower for pattern in ['late next week', 'end of next week', 'this weekend', 'next weekend', 'early next week', 'beginning of next week']):
            logger.info(f"Detected relative week pattern")
            return self._get_relative_week_date(date_lower)
        
        for day_name, day_num in self.WEEKDAYS.items():
            if day_name in date_lower:
                return self._get_next_weekday(day_num, date_lower)
        
        try:
            parsed = parser.parse(date_string, fuzzy=True)
            return self.timezone.localize(parsed) if parsed.tzinfo is None else parsed
        except:
            logger.warning(f"Could not parse date: {date_string}")
            return None
    
    def parse_time_preference(self, text: str, context_time: Optional[str] = None) -> Optional[str]:
        text_lower = text.lower()
        
        specific_time = self.parse_specific_time(text_lower, context_time)
        if specific_time:
            return specific_time
        
        for preference in self.TIME_OF_DAY.keys():
            if preference in text_lower:
                return preference
        
        return None
    
    def parse_specific_time(self, text: str, context_time: Optional[str] = None) -> Optional[str]:
        invalid_oclock = re.search(r'(\d+)\s*o[\'\']?\s*clock', text)
        if invalid_oclock:
            hour = int(invalid_oclock.group(1))
            if hour > 24 or hour == 0:
                logger.warning(f"Invalid time detected: {hour} o'clock")
                return None
        
        invalid_24h = re.search(r'(\d+):(\d+)', text)
        if invalid_24h:
            hour = int(invalid_24h.group(1))
            minute = int(invalid_24h.group(2))
            if hour >= 24 or minute >= 60:
                logger.warning(f"Invalid time detected: {hour}:{minute}")
                return None
        
        range_match = re.search(r'(\d{1,2})\s*(?:to|-|:)\s*(\d{1,2}):?(\d{2})?', text)
        if range_match:
            start_hour = int(range_match.group(1))
            end_hour = int(range_match.group(2))
            end_minute = int(range_match.group(3)) if range_match.group(3) else 0
            
            # Determine AM/PM from context or heuristics
            is_pm = False
            
            # Check for explicit PM/AM in text
            if 'pm' in text or 'afternoon' in text or 'evening' in text:
                is_pm = True
            elif 'am' in text or 'morning' in text:
                is_pm = False
            # Use context from previous message
            elif context_time and ':' in context_time:
                context_hour = int(context_time.split(':')[0])
                is_pm = context_hour >= 12
            # Heuristic: 5-11 are likely PM in conversation context
            elif 5 <= start_hour <= 11:
                is_pm = True
            
            # Convert to 24-hour format
            if is_pm and start_hour < 12:
                start_hour += 12
            if is_pm and end_hour < 12:
                end_hour += 12
            
            # Return start time (user wants meeting starting at this time)
            return f"{start_hour:02d}:00"
        
        # Pattern for times like "5 PM", "5:30 PM", "17:00"
        time_patterns = [
            r'(\d{1,2}):(\d{2})\s*(am|pm)',  # 5:30 PM
            r'(\d{1,2})\s*(am|pm)',  # 5 PM
            r'(\d{1,2}):(\d{2})',  # 14:30 (24-hour)
        ]
        
        for pattern in time_patterns:
            match = re.search(pattern, text)
            if match:
                groups = match.groups()
                
                if len(groups) == 2 and groups[1] in ['am', 'pm']:
                    # Format: "5 PM"
                    hour = int(groups[0])
                    if groups[1] == 'pm' and hour != 12:
                        hour += 12
                    elif groups[1] == 'am' and hour == 12:
                        hour = 0
                    return f"{hour:02d}:00"
                
                elif len(groups) == 3 and groups[2] in ['am', 'pm']:
                    # Format: "5:30 PM"
                    hour = int(groups[0])
                    minute = int(groups[1])
                    if groups[2] == 'pm' and hour != 12:
                        hour += 12
                    elif groups[2] == 'am' and hour == 12:
                        hour = 0
                    return f"{hour:02d}:{minute:02d}"
                
                elif len(groups) == 2 and groups[1].isdigit():
                    # Format: "14:30" (24-hour)
                    return f"{int(groups[0]):02d}:{int(groups[1]):02d}"
        
        # Handle single digit times with context (e.g., "5" when context is PM)
        # But avoid matching dates like "November 5"
        if context_time and not any(month in text for month in ['january', 'february', 'march', 'april', 'may', 'june', 'july', 'august', 'september', 'october', 'november', 'december']):
            single_time_match = re.search(r'(?:^|\s)(\d{1,2})(?:\s|$|,)', text)
            if single_time_match:
                hour = int(single_time_match.group(1))
                # Only treat as time if it's in reasonable hour range (1-12)
                if 1 <= hour <= 12:
                    # Use context to determine AM/PM
                    if ':' in context_time:
                        context_hour = int(context_time.split(':')[0])
                        if context_hour >= 12 and hour < 12:
                            hour += 12
                        return f"{hour:02d}:00"
        
        return None
    
    def parse_duration(self, text: str) -> Optional[int]:
        """
        Extract meeting duration from text.
        
        Args:
            text: Input text (e.g., "1 hour", "30 minutes", "45 min", "full hour", "an hour", "half hour")
        
        Returns:
            Duration in minutes or None
        """
        text_lower = text.lower()
        
        # ===================================================================
        # NATURAL LANGUAGE PATTERNS (check these FIRST before numeric patterns)
        # ===================================================================
        
        # "hour and a half", "an hour and a half", "1.5 hours"
        if re.search(r'(?:an?\s+)?hour\s+and\s+a\s+half|1\.5\s*hours?', text_lower):
            logger.info("📏 Parsed duration: 'hour and a half' → 90 minutes")
            return 90
        
        # "half hour", "half an hour", "a half hour", "30 min"
        if re.search(r'(?:a\s+)?half\s+(?:an?\s+)?hours?|half[\s-]hour', text_lower):
            logger.info("📏 Parsed duration: 'half hour' → 30 minutes")
            return 30
        
        # "full hour", "a full hour", "an hour", "one hour"
        # BUT make sure it's not part of a longer pattern like "1 hour 30 minutes"
        if re.search(r'\b(?:a\s+full\s+hour|full\s+hour|an?\s+hour|one\s+hour)\b', text_lower):
            # Check if NOT followed by "and X minutes" pattern
            if not re.search(r'(?:an?\s+|one\s+)?hour\s+(?:and\s+)?\d+', text_lower):
                logger.info("📏 Parsed duration: 'full hour/an hour' → 60 minutes")
                return 60
        
        # ===================================================================
        # WORD NUMBER PATTERNS with UNITS (using comprehensive parser)
        # ===================================================================
        
        # Pattern: WORD_NUMBER + "hour(s)" or "minute(s)"
        # Examples: "sixty minutes", "sixty five minutes", "two hours"
        # Also handles: "I need sixty minutes", "make it sixty five minutes please"
        
        # Try to extract word number followed by hours
        # More flexible pattern that looks for word numbers before "hour(s)"
        hour_word_pattern = r'(?:^|[^\w])([\w\s-]+?)\s+hours?(?:\s|$|\.|,)'
        hour_match = re.search(hour_word_pattern, text_lower)
        if hour_match:
            word_num_text = hour_match.group(1).strip()
            # Remove common filler words and prefixes
            word_num_text = re.sub(r'^(i need|make it|uh|um|er)\s+', '', word_num_text)
            word_value = parse_word_number(word_num_text)
            if word_value is not None:
                total = word_value * 60
                logger.info(f"📏 Parsed duration: '{word_num_text} hour(s)' → {total} minutes")
                return total
        
        # Try to extract word number followed by minutes
        # More flexible pattern that looks for word numbers before "minute(s)"
        minute_word_pattern = r'(?:^|[^\w])([\w\s-]+?)\s+minutes?(?:\s|$|\.|,)'
        minute_match = re.search(minute_word_pattern, text_lower)
        if minute_match:
            word_num_text = minute_match.group(1).strip()
            # Remove common filler words and prefixes
            word_num_text = re.sub(r'^(i need|make it|uh|um|er)\s+', '', word_num_text)
            # Also remove filler words in the middle (handle "sixty, um, minutes")
            word_num_text = re.sub(r',\s*(uh|um|er)\s*$', '', word_num_text)
            word_value = parse_word_number(word_num_text)
            if word_value is not None:
                logger.info(f"📏 Parsed duration: '{word_num_text} minute(s)' → {word_value} minutes")
                return word_value
        
        # ===================================================================
        # NUMERIC PATTERNS (original patterns)
        # ===================================================================
        
        # Look for combined patterns first (e.g., "1 hour 30 minutes", "1h 30m")
        combined_match = re.search(
            r'(\d+)[\s\-]*(?:hour|hr|h)(?:s)?\s*(?:and)?\s*(\d+)[\s\-]*(?:minute|min|m)(?:s)?',
            text_lower
        )
        if combined_match:
            hours = int(combined_match.group(1))
            minutes = int(combined_match.group(2))
            total = hours * 60 + minutes
            logger.info(f"📏 Parsed duration: '{hours}h {minutes}m' → {total} minutes")
            return total
        
        # Look for hour patterns (handles "1 hour", "1-hour", "1hr", "2 hours", etc.)
        hour_match = re.search(r'(\d+)[\s\-]*(?:hour|hr|h)(?:s)?', text_lower)
        if hour_match:
            hours = int(hour_match.group(1))
            total = hours * 60
            logger.info(f"📏 Parsed duration: '{hours} hour(s)' → {total} minutes")
            return total
        
        # Look for minute patterns (handles "30 minutes", "30-min", "45m", etc.)
        minute_match = re.search(r'(\d+)[\s\-]*(?:minute|min|m)(?:s)?', text_lower)
        if minute_match:
            minutes = int(minute_match.group(1))
            logger.info(f"📏 Parsed duration: '{minutes} minute(s)' → {minutes} minutes")
            return minutes
        
        return None
    
    def get_time_range_for_preference(
        self,
        date: datetime,
        preference: Optional[str] = None
    ) -> Tuple[datetime, datetime]:
        """
        Get time range for a given date and preference.
        
        Args:
            date: Target date
            preference: Time preference ("morning", "afternoon", "evening")
        
        Returns:
            Tuple of (start_time, end_time)
        """
        if preference and preference in self.TIME_OF_DAY:
            start_hour, end_hour = self.TIME_OF_DAY[preference]
        else:
            start_hour, end_hour = 8, 18  # Default business hours
        
        start_time = self.timezone.localize(
            datetime.combine(date.date(), datetime.min.time().replace(hour=start_hour))
        )
        end_time = self.timezone.localize(
            datetime.combine(date.date(), datetime.min.time().replace(hour=end_hour))
        )
        
        return start_time, end_time
    
    def calculate_time_before_event(
        self,
        event_time: datetime,
        buffer_minutes: int
    ) -> datetime:
        """
        Calculate time before an event.
        
        Args:
            event_time: Event start time
            buffer_minutes: Minutes before event
        
        Returns:
            Calculated datetime
        """
        return event_time - timedelta(minutes=buffer_minutes)
    
    def calculate_time_after_event(
        self,
        event_time: datetime,
        buffer_minutes: int
    ) -> datetime:
        """
        Calculate time after an event.
        
        Args:
            event_time: Event end time
            buffer_minutes: Minutes after event
        
        Returns:
            Calculated datetime
        """
        return event_time + timedelta(minutes=buffer_minutes)
    
    def _get_next_weekday(self, target_day: int, text: str) -> datetime:
        """
        Get next occurrence of a weekday.
        
        Args:
            target_day: Target day number (0=Monday, 6=Sunday)
            text: Original text for context (to check for "next")
        
        Returns:
            Datetime of next occurrence
        """
        current_day = self.now.weekday()
        days_ahead = target_day - current_day
        
        # EDGE CASE (Test 5.1): Check if user said "last" - this indicates past date
        # We'll still calculate it so validator can detect and ask for clarification
        text_lower = text.lower()
        if 'last' in text_lower and 'next' not in text_lower:
            # Calculate LAST occurrence (in the past)
            logger.warning(f"🚫 Detected 'last' in date request: {text}")
            if days_ahead > 0:
                days_ahead -= 7
            return self.now + timedelta(days=days_ahead)
        
        # If "next" is explicitly mentioned, add 7 days
        if 'next' in text_lower:
            if days_ahead <= 0:
                days_ahead += 7
        else:
            # This week if possible, otherwise next week
            if days_ahead < 0:
                days_ahead += 7
        
        return self.now + timedelta(days=days_ahead)
    
    def _get_last_weekday_of_month(self, text: str) -> datetime:
        """
        Get last weekday (Mon-Fri) of a month.
        
        Args:
            text: Text containing month reference
        
        Returns:
            Datetime of last weekday
        """
        # Determine which month
        if 'this month' in text.lower():
            target_date = self.now
            month_ref = "this month"
        elif 'next month' in text.lower():
            target_date = self.now + relativedelta.relativedelta(months=1)
            month_ref = "next month"
        else:
            target_date = self.now
            month_ref = "this month (default)"
        
        # Get last day of month
        last_day = calendar.monthrange(target_date.year, target_date.month)[1]
        last_date = datetime(target_date.year, target_date.month, last_day)
        
        logger.info(f"🗓️ Computing last weekday for {month_ref}: {target_date.year}-{target_date.month}")
        logger.info(f"   Last day of month: {last_day} (weekday: {last_date.strftime('%A')})")
        
        # Go back until we find a weekday (Mon-Fri)
        # weekday(): Monday=0, Tuesday=1, ..., Saturday=5, Sunday=6
        iterations = 0
        while last_date.weekday() > 4:  # 5=Saturday, 6=Sunday
            last_date -= timedelta(days=1)
            iterations += 1
            logger.info(f"   Skipping {last_date + timedelta(days=1)} ({(last_date + timedelta(days=1)).strftime('%A')}), trying {last_date.strftime('%Y-%m-%d %A')}")
        
        logger.info(f"✅ Last weekday of month: {last_date.strftime('%Y-%m-%d %A')} (skipped {iterations} days)")
        
        # Localize to timezone and set to start of day
        localized = self.timezone.localize(last_date.replace(hour=0, minute=0, second=0, microsecond=0))
        return localized
    
    def _get_relative_week_date(self, text: str) -> datetime:
        """
        Parse relative week patterns like "late next week", "early this week", "this weekend".
        
        For ambiguous patterns like "late next week", returns the earlier option (Thursday)
        so the agent can ask for clarification.
        
        Args:
            text: Text containing relative week pattern
        
        Returns:
            Datetime for the computed date
        """
        text_lower = text.lower()
        
        # Determine reference week
        if 'this week' in text_lower:
            # Start of this week (Monday)
            days_to_monday = (self.now.weekday() - 0) % 7
            week_start = self.now - timedelta(days=days_to_monday)
            week_ref = "this week"
        elif 'next week' in text_lower:
            # Start of next week (Monday)
            days_to_monday = (self.now.weekday() - 0) % 7
            current_week_start = self.now - timedelta(days=days_to_monday)
            week_start = current_week_start + timedelta(days=7)
            week_ref = "next week"
        else:
            week_start = self.now
            week_ref = "this week (default)"
        
        logger.info(f"🗓️ Computing relative week date for '{text_lower}'")
        logger.info(f"   Reference: {week_ref}, week starts on {week_start.strftime('%Y-%m-%d %A')}")
        
        # Determine which day of the week
        if 'late' in text_lower or 'end of' in text_lower:
            # Late week = Thursday (day 3) or Friday (day 4)
            # We return Thursday so agent can ask "Thursday or Friday?"
            target_day_of_week = 3  # Thursday
            target_description = "Thursday (late week)"
        elif 'early' in text_lower or 'beginning of' in text_lower:
            # Early week = Monday (day 0) or Tuesday (day 1)
            # We return Monday
            target_day_of_week = 0  # Monday
            target_description = "Monday (early week)"
        elif 'weekend' in text_lower:
            # Weekend = Saturday (day 5)
            target_day_of_week = 5  # Saturday
            target_description = "Saturday (weekend)"
        else:
            # Default to middle of week (Wednesday)
            target_day_of_week = 2  # Wednesday
            target_description = "Wednesday (mid-week default)"
        
        # Calculate the target date
        days_ahead = (target_day_of_week - week_start.weekday()) % 7
        target_date = week_start + timedelta(days=days_ahead)
        
        logger.info(f"   Target: {target_description} ({target_date.strftime('%Y-%m-%d')})")
        
        # Localize to timezone and set to start of day
        localized = self.timezone.localize(target_date.replace(hour=0, minute=0, second=0, microsecond=0))
        return localized


def extract_time_components(text: str, timezone: str = 'Asia/Kolkata', context_time: Optional[str] = None) -> dict:
    """
    Extract all time-related components from text.
    
    Args:
        text: Input text
        timezone: User's timezone
        context_time: Previous time preference for context (helps with "5 to 5:30" interpretation)
    
    Returns:
        Dictionary with extracted components (date, time_preference, duration)
    """
    parser_instance = TimeParser(timezone)
    
    return {
        'date': parser_instance.parse_date(text),
        'time_preference': parser_instance.parse_time_preference(text, context_time),
        'duration_minutes': parser_instance.parse_duration(text)
    }

