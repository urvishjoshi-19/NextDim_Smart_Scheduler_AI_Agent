"""
Time utility functions for handling 24-hour and 12-hour format conversions.

This module provides a consistent interface for time handling throughout the application:
- Internal storage: 24-hour format (HH:MM)
- User display: 12-hour format (h:MM AM/PM)
- LLM communication: 24-hour format (HH:MM)

All times are handled in IST (Indian Standard Time).
"""

import re
from typing import Optional, Dict, Tuple
from datetime import datetime, time
import pytz


class TimeFormat:
    """
    Utility class for time format conversions and validation.
    Ensures consistent time handling across the application.
    """
    
    @staticmethod
    def parse_to_24hr(time_str: str, context: Optional[str] = None) -> Optional[str]:
        """
        Parse any time string to 24-hour format (HH:MM).
        
        Handles:
        - "3 PM" → "15:00"
        - "3:30 PM" → "15:30"
        - "15:00" → "15:00"
        - "3:00" (ambiguous) → uses context or defaults
        
        Args:
            time_str: Time string in various formats
            context: Conversation context to resolve ambiguity
        
        Returns:
            24-hour format string (HH:MM) or None if unparseable
        """
        if not time_str:
            return None
        
        time_str = str(time_str).strip().upper()
        
        # Remove common words
        time_str = time_str.replace("AT", "").replace("O'CLOCK", "").strip()
        
        # Pattern 1: 12-hour with AM/PM (3 PM, 3:30 PM, 03:30 PM)
        match = re.match(r'(\d{1,2}):?(\d{2})?\s*(AM|PM)', time_str)
        if match:
            hour = int(match.group(1))
            minute = int(match.group(2)) if match.group(2) else 0
            am_pm = match.group(3)
            
            # Validate
            if hour < 1 or hour > 12 or minute < 0 or minute >= 60:
                return None
            
            # Convert to 24-hour
            if am_pm == 'PM' and hour != 12:
                hour += 12
            elif am_pm == 'AM' and hour == 12:
                hour = 0
            
            return f"{hour:02d}:{minute:02d}"
        
        # Pattern 2: 24-hour format (15:00, 3:00)
        match = re.match(r'(\d{1,2}):(\d{2})', time_str)
        if match:
            hour = int(match.group(1))
            minute = int(match.group(2))
            
            # Validate
            if hour < 0 or hour >= 24 or minute < 0 or minute >= 60:
                return None
            
            # If hour >= 12, it's clearly 24-hour format
            if hour >= 12:
                return f"{hour:02d}:{minute:02d}"
            
            # Ambiguous (0-11) - use context
            if context:
                context_lower = context.lower()
                if any(word in context_lower for word in ['afternoon', 'pm', 'evening', 'night']):
                    # User meant PM
                    if hour != 12:
                        hour += 12
                    return f"{hour:02d}:{minute:02d}"
                elif any(word in context_lower for word in ['morning', 'am']):
                    # User meant AM
                    return f"{hour:02d}:{minute:02d}"
            
            # Default: business hours logic (9 AM - 5 PM is common)
            # If hour is 9-11, assume AM
            # If hour is 1-5, assume PM
            # Otherwise, return as-is
            if 1 <= hour <= 5:
                hour += 12  # Assume PM for 1-5
            
            return f"{hour:02d}:{minute:02d}"
        
        # Pattern 3: Just hour (3, 15)
        match = re.match(r'(\d{1,2})', time_str)
        if match:
            hour = int(match.group(1))
            
            if hour < 0 or hour >= 24:
                return None
            
            # If clearly 24-hour (13-23)
            if hour >= 13:
                return f"{hour:02d}:00"
            
            # Use context for ambiguous hours
            if context:
                context_lower = context.lower()
                if any(word in context_lower for word in ['afternoon', 'pm', 'evening', 'night']):
                    if hour != 12:
                        hour += 12
                    return f"{hour:02d}:00"
            
            # Default for common times
            if 1 <= hour <= 5:
                hour += 12  # Assume PM
            
            return f"{hour:02d}:00"
        
        return None
    
    @staticmethod
    def to_12hr_display(time_24hr: str) -> str:
        """
        Convert 24-hour format to user-friendly 12-hour display.
        
        Args:
            time_24hr: Time in 24-hour format (HH:MM)
        
        Returns:
            12-hour format for display (h:MM AM/PM or h AM/PM)
        
        Examples:
            "15:00" → "3 PM"
            "15:30" → "3:30 PM"
            "09:00" → "9 AM"
            "09:15" → "9:15 AM"
        """
        if not time_24hr:
            return ""
        
        try:
            match = re.match(r'(\d{1,2}):(\d{2})', time_24hr)
            if not match:
                return time_24hr
            
            hour = int(match.group(1))
            minute = int(match.group(2))
            
            # Determine AM/PM
            am_pm = "AM" if hour < 12 else "PM"
            
            # Convert to 12-hour
            hour_12 = hour % 12
            if hour_12 == 0:
                hour_12 = 12
            
            # Format display (hide :00 for cleaner look)
            if minute == 0:
                return f"{hour_12} {am_pm}"
            else:
                return f"{hour_12}:{minute:02d} {am_pm}"
        
        except:
            return time_24hr
    
    @staticmethod
    def to_12hr_full(time_24hr: str) -> str:
        """
        Convert 24-hour format to full 12-hour format (always show minutes).
        
        Args:
            time_24hr: Time in 24-hour format (HH:MM)
        
        Returns:
            Full 12-hour format (hh:MM AM/PM)
        
        Examples:
            "15:00" → "03:00 PM"
            "09:00" → "09:00 AM"
        """
        if not time_24hr:
            return ""
        
        try:
            match = re.match(r'(\d{1,2}):(\d{2})', time_24hr)
            if not match:
                return time_24hr
            
            hour = int(match.group(1))
            minute = int(match.group(2))
            
            am_pm = "AM" if hour < 12 else "PM"
            hour_12 = hour % 12
            if hour_12 == 0:
                hour_12 = 12
            
            return f"{hour_12:02d}:{minute:02d} {am_pm}"
        
        except:
            return time_24hr
    
    @staticmethod
    def validate_and_correct(time_str: str, context: Optional[str] = None) -> Tuple[str, bool]:
        """
        Validate time string and auto-correct obvious errors.
        
        Args:
            time_str: Time string to validate
            context: Context for validation
        
        Returns:
            Tuple of (corrected_24hr_time, was_corrected)
        
        Examples:
            ("3:00", "afternoon") → ("15:00", True)  # Corrected AM to PM
            ("15:00", "afternoon") → ("15:00", False)  # Already correct
        """
        parsed = TimeFormat.parse_to_24hr(time_str, context)
        
        if not parsed:
            return None, False
        
        # Check if correction was needed based on context
        was_corrected = False
        
        if context:
            context_lower = context.lower()
            hour = int(parsed.split(':')[0])
            
            # Check for PM context but AM time
            if any(word in context_lower for word in ['afternoon', 'evening', 'night', 'pm']):
                if hour < 12:
                    # This looks like an error - should be PM
                    was_corrected = True
            
            # Check for AM context but PM time
            elif any(word in context_lower for word in ['morning', 'am']):
                if hour >= 12:
                    # This looks like an error - should be AM
                    was_corrected = True
        
        return parsed, was_corrected
    
    @staticmethod
    def extract_from_message(message: str) -> Optional[Dict[str, str]]:
        """
        Extract time from a message and return both formats.
        
        Args:
            message: User message
        
        Returns:
            Dict with '24hr' and '12hr' keys, or None
        
        Example:
            "I want 3 PM" → {"24hr": "15:00", "12hr": "3 PM", "original": "3 PM"}
        """
        # Look for time patterns in message
        patterns = [
            r'(\d{1,2}:?\d{0,2}\s*(?:AM|PM|am|pm))',
            r'(\d{1,2}:\d{2})',
            r'(\d{1,2})\s*(?:o\'clock|oclock)'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, message, re.IGNORECASE)
            if match:
                original = match.group(1)
                time_24hr = TimeFormat.parse_to_24hr(original, message)
                
                if time_24hr:
                    return {
                        "24hr": time_24hr,
                        "12hr": TimeFormat.to_12hr_display(time_24hr),
                        "original": original
                    }
        
        return None
    
    @staticmethod
    def is_business_hours(time_24hr: str) -> bool:
        """
        Check if time falls within typical business hours (9 AM - 6 PM IST).
        
        Args:
            time_24hr: Time in 24-hour format
        
        Returns:
            True if within business hours
        """
        try:
            hour = int(time_24hr.split(':')[0])
            return 9 <= hour < 18
        except:
            return False
    
    @staticmethod
    def get_time_of_day(time_24hr: str) -> str:
        """
        Get time of day classification.
        
        Args:
            time_24hr: Time in 24-hour format
        
        Returns:
            "morning", "afternoon", or "evening"
        """
        try:
            hour = int(time_24hr.split(':')[0])
            
            if 5 <= hour < 12:
                return "morning"
            elif 12 <= hour < 17:
                return "afternoon"
            elif 17 <= hour < 21:
                return "evening"
            else:
                return "night"
        except:
            return "unknown"


# Convenience functions for common use cases

def convert_to_24hr(time_str: str, context: Optional[str] = None) -> Optional[str]:
    """Shorthand for TimeFormat.parse_to_24hr()"""
    return TimeFormat.parse_to_24hr(time_str, context)


def convert_to_12hr(time_24hr: str) -> str:
    """Shorthand for TimeFormat.to_12hr_display()"""
    return TimeFormat.to_12hr_display(time_24hr)


def validate_time(time_str: str, context: Optional[str] = None) -> Tuple[str, bool]:
    """Shorthand for TimeFormat.validate_and_correct()"""
    return TimeFormat.validate_and_correct(time_str, context)

