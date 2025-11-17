from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any, Tuple
import pytz
from dateutil import parser

from ..utils.logger import logger
from ..utils.debug_events import emit_calendar_query, emit_calendar_events, emit_availability_check

class GoogleCalendarTool:
    def __init__(self, credentials: Credentials):
        self.credentials = credentials
        self.service = build('calendar', 'v3', credentials=credentials)
        logger.info("Initialized Google Calendar tool")
    
    def list_events(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        max_results: int = 50,
        calendar_id: str = 'primary'
    ) -> List[Dict[str, Any]]:
        if start_time is None:
            ist_tz = pytz.timezone('Asia/Kolkata')
            start_time = datetime.now(ist_tz)
        
        if end_time is None:
            end_time = start_time + timedelta(days=7)
        
        try:
            if start_time.tzinfo is not None:
                time_min = start_time.isoformat()
            else:
                time_min = start_time.isoformat() + 'Z'
                
            if end_time.tzinfo is not None:
                time_max = end_time.isoformat()
            else:
                time_max = end_time.isoformat() + 'Z'
            
            events_result = self.service.events().list(
                calendarId=calendar_id,
                timeMin=time_min,
                timeMax=time_max,
                maxResults=max_results,
                singleEvents=True,
                orderBy='startTime'
            ).execute()
            
            events = events_result.get('items', [])
            logger.info(f"Retrieved {len(events)} events from calendar")
            return events
        
        except HttpError as error:
            logger.error(f"Error listing calendar events: {error}")
            raise
    
    def analyze_recurring_meeting_pattern(self, meeting_keyword: str, lookback_days: int = 60) -> Optional[int]:
        try:
            from collections import Counter
            
            ist_tz = pytz.timezone('Asia/Kolkata')
            end_time = datetime.now(ist_tz)
            start_time = end_time - timedelta(days=lookback_days)
            
            logger.info(f"Analyzing past '{meeting_keyword}' meetings")
            
            events = self.list_events(start_time, end_time, max_results=100)
            
            matching_events = []
            keyword_lower = meeting_keyword.lower()
            
            for event in events:
                summary = event.get('summary', '').lower()
                keyword_normalized = keyword_lower.replace('-', '').replace(' ', '')
                summary_normalized = summary.replace('-', '').replace(' ', '')
                
                if keyword_normalized in summary_normalized or keyword_lower in summary:
                    matching_events.append(event)
            
            logger.info(f"Found {len(matching_events)} past '{meeting_keyword}' meetings")
            
            if not matching_events:
                return None
            
            durations = []
            for event in matching_events:
                if 'start' in event and 'end' in event:
                    try:
                        if 'dateTime' in event['start']:
                            start_dt = datetime.fromisoformat(event['start']['dateTime'].replace('Z', '+00:00'))
                            end_dt = datetime.fromisoformat(event['end']['dateTime'].replace('Z', '+00:00'))
                            duration_minutes = int((end_dt - start_dt).total_seconds() / 60)
                            durations.append(duration_minutes)
                    except Exception as e:
                        logger.warning(f"Could not parse event duration: {e}")
                        continue
            
            if not durations:
                logger.warning("No valid durations found")
                return None
            
            duration_counter = Counter(durations)
            most_common_duration, count = duration_counter.most_common(1)[0]
            
            logger.info(f"Duration analysis: {dict(duration_counter.most_common())}")
            logger.info(f"Most common: {most_common_duration} minutes")
            
            if count >= 2:
                return most_common_duration
            elif count == 1 and len(durations) == 1:
                logger.info(f"Using {most_common_duration} minutes")
                return most_common_duration
            
            return None
            
        except Exception as e:
            logger.error(f"Error analyzing recurring meeting pattern: {e}")
            return None
    
    def find_available_slots(
        self,
        date: str,
        duration_minutes: int,
        time_preference: Optional[str] = None,
        timezone: str = 'Asia/Kolkata'
    ) -> Tuple[List[Dict[str, Any]], Optional[Dict[str, Any]]]:
        target_date = self._parse_date(date, timezone)
        
        specific_hour = None
        if time_preference and ':' in time_preference:
            try:
                specific_hour = int(time_preference.split(':')[0])
                logger.info(f"Specific time requested: {specific_hour}:00")
            except:
                pass
        
        start_hour, end_hour = self._get_time_range(time_preference)
        
        tz = pytz.timezone(timezone)
        start_time = tz.localize(datetime.combine(target_date, datetime.min.time().replace(hour=start_hour)))
        end_time = tz.localize(datetime.combine(target_date, datetime.min.time().replace(hour=end_hour)))
        
        emit_calendar_query({
            "date": date,
            "parsed_date": str(target_date),
            "duration_minutes": duration_minutes,
            "time_preference": time_preference,
            "specific_hour": specific_hour,
            "start_hour": start_hour,
            "end_hour": end_hour,
            "timezone": timezone,
            "search_window_start": start_time.isoformat(),
            "search_window_end": end_time.isoformat(),
            "search_window_start_utc": start_time.astimezone(pytz.UTC).isoformat(),
            "search_window_end_utc": end_time.astimezone(pytz.UTC).isoformat()
        })
        
        events = self.list_events(
            start_time=start_time.astimezone(pytz.UTC),
            end_time=end_time.astimezone(pytz.UTC)
        )
        
        emit_calendar_events([{
            "summary": e.get("summary", "No title"),
            "start": e.get("start", {}).get("dateTime", e.get("start", {}).get("date", "Unknown")),
            "end": e.get("end", {}).get("dateTime", e.get("end", {}).get("date", "Unknown"))
        } for e in events])
        
        available_slots, all_gaps = self._find_gaps(
            events=events,
            start_time=start_time,
            end_time=end_time,
            duration_minutes=duration_minutes,
            timezone=timezone
        )
        
        partial_gap_at_requested_time = None
        if specific_hour is not None:
            for gap in all_gaps:
                if not gap.get('fits_requirement', True):
                    gap_start = parser.isoparse(gap['start'])
                    gap_end = parser.isoparse(gap['end'])
                    gap_duration = gap['duration_minutes']
                    requested_datetime = gap_start.replace(hour=specific_hour, minute=0, second=0, microsecond=0)
                    
                    if (gap_start <= requested_datetime < gap_end) or (gap_start.hour == specific_hour and gap_start.minute == 0):
                        partial_gap_at_requested_time = {
                            'start': gap['start'],
                            'end': gap['end'],
                            'duration_minutes': gap_duration,
                            'requested_duration': duration_minutes,
                            'shortage_minutes': duration_minutes - gap_duration
                        }
                        logger.info(f"Partial gap at {specific_hour}:00 - {gap_duration} min available, need {duration_minutes} min")
                        break
        
        if specific_hour is not None and available_slots:
            exact_hour_slots = []
            other_slots = []
            
            for slot in available_slots:
                slot_time = datetime.fromisoformat(slot['start'])
                if slot_time.hour == specific_hour:
                    exact_hour_slots.append(slot)
                else:
                    other_slots.append(slot)
            
            # If no exact hour slots, generate one at the requested hour if possible
            if not exact_hour_slots and available_slots:
                # CRITICAL FIX: We need to validate that the requested time actually fits in a gap
                # We cannot just create a "synthetic" slot without checking for conflicts!
                
                # Get all gaps again to properly validate
                for gap in all_gaps:
                    if not gap.get('fits_requirement', True):
                        # This gap is too small for the duration, skip it
                        continue
                    
                    gap_start = parser.isoparse(gap['start'])
                    gap_end = parser.isoparse(gap['end'])
                    
                    # Create a potential slot at the requested hour
                    requested_slot_start = gap_start.replace(hour=specific_hour, minute=0, second=0, microsecond=0)
                    requested_slot_end = requested_slot_start + timedelta(minutes=duration_minutes)
                    
                    # STRICT VALIDATION: The requested slot must COMPLETELY fit within this gap
                    # It must not overlap with any existing events
                    if requested_slot_start >= gap_start and requested_slot_end <= gap_end:
                        logger.info(f"✅ Requested time {specific_hour}:00 fits in gap {gap_start.strftime('%H:%M')}-{gap_end.strftime('%H:%M')}")
                        exact_hour_slots.append({
                            'start': requested_slot_start.isoformat(),
                            'end': requested_slot_end.isoformat(),
                            'start_formatted': requested_slot_start.strftime('%I:%M %p'),
                            'date_formatted': requested_slot_start.strftime('%A, %B %d, %Y'),
                            'priority': 0,  # Highest priority - exact requested time
                            'is_synthetic': True
                        })
                        break
                    else:
                        logger.warning(f"❌ Requested time {specific_hour}:00 does NOT fit in gap {gap_start.strftime('%H:%M')}-{gap_end.strftime('%H:%M')}")
                        logger.warning(f"   Requested slot: {requested_slot_start.strftime('%H:%M')}-{requested_slot_end.strftime('%H:%M')}")
                        logger.warning(f"   Gap boundaries: {gap_start.strftime('%H:%M')}-{gap_end.strftime('%H:%M')}")
                
                # If we couldn't create a synthetic slot, log why
                if not exact_hour_slots:
                    logger.warning(f"⚠️ Cannot create slot at {specific_hour}:00 - requested time conflicts with existing events or falls outside available gaps")
            
            # Sort other slots by proximity to the requested hour
            def time_distance(slot):
                slot_time = datetime.fromisoformat(slot['start'])
                slot_hour = slot_time.hour
                slot_minute = slot_time.minute
                
                # Calculate distance in minutes from requested time
                # Exact hour match = 0, each hour away adds 60, each minute away adds 1
                hour_diff = abs(slot_hour - specific_hour) * 60
                minute_diff = slot_minute if slot_hour == specific_hour else 0
                return hour_diff + minute_diff
            
            other_slots.sort(key=time_distance)
            
            # Recombine: exact hour slots first, then sorted others
            available_slots = exact_hour_slots + other_slots
            logger.info(f"Prioritized slots near {specific_hour}:00, found {len(exact_hour_slots)} exact matches and {len(other_slots)} alternatives")
        
        logger.info(f"Found {len(available_slots)} available slots on {date}")
        return available_slots, partial_gap_at_requested_time
    
    def _find_gaps(
        self,
        events: List[Dict],
        start_time: datetime,
        end_time: datetime,
        duration_minutes: int,
        timezone: str
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Find gaps between events that can fit the required duration.
        
        Args:
            events: List of existing events
            start_time: Start of search window
            end_time: End of search window
            duration_minutes: Required duration
            timezone: Timezone for output
        
        Returns:
            Tuple of (available slots, all gaps including partial ones)
        """
        available_slots = []
        duration = timedelta(minutes=duration_minutes)
        
        # Convert to UTC for comparison
        current_time = start_time.astimezone(pytz.UTC)
        window_end = end_time.astimezone(pytz.UTC)
        
        # Debug: Log initial state
        gaps_found = []
        
        for event in events:
            # Parse event times
            event_start = parser.isoparse(event['start'].get('dateTime', event['start'].get('date')))
            event_end = parser.isoparse(event['end'].get('dateTime', event['end'].get('date')))
            
            # Check if there's a gap before this event
            gap_minutes = int((event_start - current_time).total_seconds() / 60)
            if event_start - current_time >= duration:
                gap = {
                    'start': current_time.astimezone(pytz.timezone(timezone)),
                    'end': event_start.astimezone(pytz.timezone(timezone)),
                    'duration_minutes': gap_minutes
                }
                available_slots.append(gap)
                gaps_found.append({
                    'start': gap['start'].isoformat(),
                    'end': gap['end'].isoformat(),
                    'duration_minutes': gap_minutes,
                    'fits_requirement': True
                })
            elif gap_minutes > 0:
                # Gap exists but too small
                gaps_found.append({
                    'start': current_time.astimezone(pytz.timezone(timezone)).isoformat(),
                    'end': event_start.astimezone(pytz.timezone(timezone)).isoformat(),
                    'duration_minutes': gap_minutes,
                    'fits_requirement': False,
                    'reason': f'Gap is {gap_minutes} min, need {duration_minutes} min'
                })
            
            # Move current time to end of this event
            current_time = max(current_time, event_end)
        
        # Check if there's a gap after the last event
        final_gap_minutes = int((window_end - current_time).total_seconds() / 60)
        if window_end - current_time >= duration:
            gap = {
                'start': current_time.astimezone(pytz.timezone(timezone)),
                'end': window_end.astimezone(pytz.timezone(timezone)),
                'duration_minutes': final_gap_minutes
            }
            available_slots.append(gap)
            gaps_found.append({
                'start': gap['start'].isoformat(),
                'end': gap['end'].isoformat(),
                'duration_minutes': final_gap_minutes,
                'fits_requirement': True
            })
        elif final_gap_minutes > 0:
            gaps_found.append({
                'start': current_time.astimezone(pytz.timezone(timezone)).isoformat(),
                'end': window_end.astimezone(pytz.timezone(timezone)).isoformat(),
                'duration_minutes': final_gap_minutes,
                'fits_requirement': False,
                'reason': f'Gap is {final_gap_minutes} min, need {duration_minutes} min'
            })
        
        # Generate edge-aligned slots that stick to gap boundaries
        fitting_slots = []
        for slot in available_slots:
            gap_start = slot['start']
            gap_end = slot['end']
            gap_duration_minutes = int((gap_end - gap_start).total_seconds() / 60)
            
            # Strategy: Prioritize slots aligned to gap edges
            edge_slots = []
            
            # Priority 1: Slot that STARTS at gap beginning (right after previous event)
            if gap_start + duration <= gap_end:
                edge_slots.append({
                    'start': gap_start.isoformat(),
                    'end': (gap_start + duration).isoformat(),
                    'start_formatted': gap_start.strftime('%I:%M %p'),
                    'date_formatted': gap_start.strftime('%A, %B %d, %Y'),
                    'priority': 1  # Highest priority - starts at edge
                })
            
            # Priority 2: Slot that ENDS at gap end (right before next event)
            slot_that_ends_at_edge = gap_end - duration
            if slot_that_ends_at_edge >= gap_start:
                # Only add if it's different from the start-aligned slot
                if not edge_slots or (slot_that_ends_at_edge - gap_start).total_seconds() / 60 >= 30:
                    edge_slots.append({
                        'start': slot_that_ends_at_edge.isoformat(),
                        'end': gap_end.isoformat(),
                        'start_formatted': slot_that_ends_at_edge.strftime('%I:%M %p'),
                        'date_formatted': slot_that_ends_at_edge.strftime('%A, %B %d, %Y'),
                        'priority': 2  # Second priority - ends at edge
                    })
            
            # Add edge-aligned slots first
            fitting_slots.extend(edge_slots)
            
            # Priority 3: If gap is very large, add intermediate slots on hour boundaries
            if gap_duration_minutes > duration_minutes * 2:
                # Generate slots on hourly boundaries (00, 30 minutes)
                current_hour = gap_start.hour
                current_minute = (gap_start.minute // 30) * 30  # Round down to nearest 30 min
                
                # Move to next slot boundary
                if current_minute == 0:
                    current_minute = 30
                else:
                    current_hour += 1
                    current_minute = 0
                
                intermediate_count = 0
                max_intermediates = 8  # Increased to generate more slots throughout the time window
                
                while intermediate_count < max_intermediates:
                    # Create slot at this boundary
                    current_start = gap_start.replace(hour=current_hour, minute=current_minute, second=0, microsecond=0)
                    
                    # Check if slot fits in gap and doesn't conflict with events
                    if current_start + duration <= gap_end:
                        # Only add if not too close to existing edge slots
                        is_too_close_to_existing = False
                        for existing_slot in fitting_slots:
                            existing_start = parser.isoparse(existing_slot['start'])
                            distance_minutes = abs((existing_start - current_start).total_seconds() / 60)
                            # Require at least 15 minutes distance between slots
                            if distance_minutes < 15:
                                is_too_close_to_existing = True
                                logger.info(f"Skipping slot at {current_start.strftime('%H:%M')} - too close to existing slot (distance: {distance_minutes:.0f} min)")
                                break
                        
                        if not is_too_close_to_existing:
                            fitting_slots.append({
                                'start': current_start.isoformat(),
                                'end': (current_start + duration).isoformat(),
                                'start_formatted': current_start.strftime('%I:%M %p'),
                                'date_formatted': current_start.strftime('%A, %B %d, %Y'),
                                'priority': 3  # Lower priority - intermediate slot
                            })
                            logger.info(f"Added intermediate slot at {current_start.strftime('%H:%M')}")
                            intermediate_count += 1
                    
                    # Move to next 30-minute boundary
                    current_minute += 30
                    if current_minute >= 60:
                        current_minute = 0
                        current_hour += 1
                        # Stop if we've gone past the gap end hour
                        if current_hour >= gap_end.hour:
                            break
            
            # Limit total slots to avoid overwhelming user
            if len(fitting_slots) >= 20:
                break
        
        # Emit availability check debug event
        emit_availability_check({
            "duration_required_minutes": duration_minutes,
            "search_window_start": start_time.astimezone(pytz.timezone(timezone)).isoformat(),
            "search_window_end": end_time.astimezone(pytz.timezone(timezone)).isoformat(),
            "events_count": len(events),
            "gaps_found": gaps_found,
            "large_enough_gaps": len(available_slots),
            "fitting_slots_generated": len(fitting_slots),
            "returned_slots": min(10, len(fitting_slots))
        })
        
        return fitting_slots[:10], gaps_found  # Return top 10 suggestions and all gap information
    
    def create_event(
        self,
        summary: str,
        start_time: datetime,
        end_time: datetime,
        description: Optional[str] = None,
        timezone: str = 'Asia/Kolkata',
        calendar_id: str = 'primary'
    ) -> Dict[str, Any]:
        """
        Create a new calendar event.
        
        Args:
            summary: Event title
            start_time: Event start time
            end_time: Event end time
            description: Optional event description
            timezone: Timezone for the event
            calendar_id: Calendar ID (default: 'primary')
        
        Returns:
            Created event dictionary
        """
        event = {
            'summary': summary,
            'description': description or 'Created by Smart Scheduler AI',
            'start': {
                'dateTime': start_time.isoformat(),
                'timeZone': timezone,
            },
            'end': {
                'dateTime': end_time.isoformat(),
                'timeZone': timezone,
            },
        }
        
        try:
            created_event = self.service.events().insert(
                calendarId=calendar_id,
                body=event
            ).execute()
            
            logger.info(f"Created event: {summary} at {start_time}")
            return created_event
        
        except HttpError as error:
            logger.error(f"Error creating calendar event: {error}")
            raise
    
    def search_event_by_name(
        self,
        event_name: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Search for an event by name.
        
        Args:
            event_name: Name of the event to search for
            start_time: Start of search window (default: now in IST)
            end_time: End of search window (default: 30 days from now)
        
        Returns:
            First matching event or None
        """
        if start_time is None:
            # Use IST timezone (Asia/Kolkata)
            ist_tz = pytz.timezone('Asia/Kolkata')
            start_time = datetime.now(ist_tz)
        
        if end_time is None:
            end_time = start_time + timedelta(days=30)
        
        try:
            events_result = self.service.events().list(
                calendarId='primary',
                timeMin=start_time.isoformat() + 'Z',
                timeMax=end_time.isoformat() + 'Z',
                q=event_name,
                singleEvents=True,
                orderBy='startTime'
            ).execute()
            
            events = events_result.get('items', [])
            
            if events:
                logger.info(f"Found event matching '{event_name}'")
                return events[0]
            else:
                logger.info(f"No event found matching '{event_name}'")
                return None
        
        except HttpError as error:
            logger.error(f"Error searching for event: {error}")
            raise
    
    def _parse_date(self, date_string: str, timezone: str) -> datetime:
        """
        Parse date string to datetime object.
        
        Args:
            date_string: Date in various formats
            timezone: User's timezone
        
        Returns:
            Parsed datetime object
        """
        # Try parsing with dateutil
        try:
            return parser.parse(date_string).date()
        except:
            # Fallback to today
            tz = pytz.timezone(timezone)
            return datetime.now(tz).date()
    
    def _get_time_range(self, preference: Optional[str]) -> tuple[int, int]:
        """
        Get hour range based on time preference.
        
        Args:
            preference: "morning", "afternoon", "evening", specific time like "17:00", or None
        
        Returns:
            Tuple of (start_hour, end_hour) in 24-hour format
        """
        # Check if preference is a specific time (e.g., "17:00" or "06:00")
        if preference and ':' in preference:
            try:
                hour = int(preference.split(':')[0])
                # For specific time, search in a 4-hour window around it
                # REMOVED: max(8, ...) restriction to allow early morning times like 6 AM
                start_hour = max(0, hour - 1)  # Allow any hour from midnight
                end_hour = min(23, hour + 4)   # Extended window for better coverage
                return (start_hour, end_hour)
            except:
                pass  # Fall through to general preferences
        
        # General time-of-day preferences (only applied when user doesn't specify exact time)
        # Extended ranges to accommodate different schedules and timezones worldwide
        if preference == "morning":
            return (5, 12)  # Early morning to noon (5 AM - 12 PM)
        elif preference == "afternoon":
            return (12, 18)  # Noon to early evening (12 PM - 6 PM)
        elif preference == "evening":
            return (17, 23)  # Late afternoon to late night (5 PM - 11 PM)
        elif preference == "night" or preference == "late night":
            return (20, 23)  # Late night (8 PM - 11 PM)
        else:
            return (0, 23)  # Full 24-hour availability if no preference specified

