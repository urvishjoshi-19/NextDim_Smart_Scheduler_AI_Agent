from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from typing import Optional, Dict, Any
import json
import os
from pathlib import Path

from ..utils.config import settings
from ..utils.logger import logger

class OAuthManager:
    SCOPES = [
        'https://www.googleapis.com/auth/calendar',
        'https://www.googleapis.com/auth/calendar.events',
        'https://www.googleapis.com/auth/userinfo.email',
        'https://www.googleapis.com/auth/userinfo.profile',
        'openid'
    ]
    
    def __init__(self):
        # Determine the correct redirect URI based on environment
        if settings.environment == "production":
            self.redirect_uri = "https://smart-scheduler-ai-lhorvsygpa-uc.a.run.app/auth/callback"
        else:
            self.redirect_uri = "http://localhost:8000/auth/callback"
        
        self.client_config = {
            "web": {
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [
                    self.redirect_uri,
                    "http://localhost:8000/auth/callback"
                ]
            }
        }
        
        self.token_dir = Path("./tokens")
        self.token_dir.mkdir(exist_ok=True)
        
        logger.info(f"OAuth initialized with redirect_uri: {self.redirect_uri}")
    
    def get_authorization_url(self, state: Optional[str] = None) -> tuple[str, str]:
        flow = Flow.from_client_config(
            self.client_config,
            scopes=self.SCOPES,
            redirect_uri=self.redirect_uri
        )
        
        authorization_url, state = flow.authorization_url(
            access_type='offline',
            include_granted_scopes='true',
            prompt='consent'
        )
        
        logger.info(f"Generated authorization URL with state: {state}")
        return authorization_url, state
    
    def exchange_code_for_credentials(self, code: str, state: str) -> Credentials:
        flow = Flow.from_client_config(
            self.client_config,
            scopes=self.SCOPES,
            redirect_uri=self.redirect_uri,
            state=state
        )
        
        flow.fetch_token(code=code)
        credentials = flow.credentials
        
        logger.info("Successfully exchanged code for credentials")
        return credentials
    
    def save_credentials(self, user_id: str, credentials: Credentials) -> None:
        token_path = self.token_dir / f"{user_id}.json"
        
        token_data = {
            'token': credentials.token,
            'refresh_token': credentials.refresh_token,
            'token_uri': credentials.token_uri,
            'client_id': credentials.client_id,
            'client_secret': credentials.client_secret,
            'scopes': credentials.scopes
        }
        
        with open(token_path, 'w') as f:
            json.dump(token_data, f)
        
        logger.info(f"Saved credentials for user: {user_id}")
    
    def load_credentials(self, user_id: str) -> Optional[Credentials]:
        token_path = self.token_dir / f"{user_id}.json"
        
        if not token_path.exists():
            logger.warning(f"No credentials found for user: {user_id}")
            return None
        
        with open(token_path, 'r') as f:
            token_data = json.load(f)
        
        credentials = Credentials(
            token=token_data['token'],
            refresh_token=token_data.get('refresh_token'),
            token_uri=token_data['token_uri'],
            client_id=token_data['client_id'],
            client_secret=token_data['client_secret'],
            scopes=token_data['scopes']
        )
        
        # Refresh if expired
        if credentials.expired and credentials.refresh_token:
            logger.info(f"Refreshing expired credentials for user: {user_id}")
            credentials.refresh(Request())
            self.save_credentials(user_id, credentials)
        
        return credentials
    
    def revoke_credentials(self, user_id: str) -> bool:
        token_path = self.token_dir / f"{user_id}.json"
        
        if token_path.exists():
            token_path.unlink()
            logger.info(f"Revoked credentials for user: {user_id}")
            return True
        
        return False
    
    def get_user_info(self, credentials: Credentials) -> Dict[str, Any]:
        from googleapiclient.discovery import build
        
        service = build('oauth2', 'v2', credentials=credentials)
        user_info = service.userinfo().get().execute()
        
        return {
            'user_id': user_info.get('id'),
            'email': user_info.get('email'),
            'name': user_info.get('name'),
            'picture': user_info.get('picture')
        }

oauth_manager = OAuthManager()

