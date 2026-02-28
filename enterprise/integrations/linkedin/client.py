"""
LinkedIn API Client — SAFE MODE
================================
Post scheduling and content drafting ONLY.
Strictly within LinkedIn API allowed operations:
  - Share text posts (UGC Posts API)
  - Schedule posts (via local scheduler)
  - Draft content with AI

NOT implemented (outside API scope):
  - Auto-connection requests
  - Auto-messaging
  - Profile scraping
  - Engagement automation

Official LinkedIn API docs:
  https://learn.microsoft.com/en-us/linkedin/marketing/integrations/community-management/shares/ugc-post-api
"""

import json
import logging
import urllib.parse
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import requests

from enterprise.integrations.base import BaseIntegration, IntegrationStatus, ActionResult
from enterprise.credentials.manager import get_credential_manager

logger = logging.getLogger(__name__)

LINKEDIN_AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"
LINKEDIN_TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
LINKEDIN_API_BASE = "https://api.linkedin.com/v2"

LINKEDIN_SCOPES = ["openid", "profile", "w_member_social"]


class LinkedInClient(BaseIntegration):
    """
    LinkedIn API client — post scheduling and content management only.

    Authentication: OAuth2 Authorization Code flow.
    All posts require human approval before publishing.
    """

    name = "linkedin"
    description = "LinkedIn API — safe mode post scheduling and content drafting"

    def __init__(self):
        super().__init__()
        self._access_token: Optional[str] = None
        self._person_urn: Optional[str] = None

    def connect(self) -> bool:
        try:
            token_data = self.creds.load_oauth_token("LINKEDIN")
            if not token_data:
                logger.warning("LinkedIn not authorized. Run: python -m enterprise.integrations.linkedin.auth")
                self._status = IntegrationStatus.REQUIRES_AUTH
                return False

            import time
            expires_at = token_data.get("expires_at", 0)
            if time.time() >= expires_at - 60:
                logger.warning("LinkedIn token may be expired. Re-authorize if requests fail.")

            self._access_token = token_data.get("access_token")
            profile = self._get("/me")
            self._person_urn = f"urn:li:person:{profile['id']}"
            logger.info("LinkedIn connected as: %s %s", profile.get("localizedFirstName"), profile.get("localizedLastName"))
            self._status = IntegrationStatus.CONNECTED
            return True

        except Exception as e:
            self._status = IntegrationStatus.ERROR
            self._error = str(e)
            logger.error("LinkedIn connect failed: %s", e)
            return False

    def health_check(self) -> bool:
        try:
            self._get("/me")
            return True
        except Exception:
            return False

    def get_status(self) -> IntegrationStatus:
        return self._status

    def authorize(self) -> Dict:
        """
        Run the OAuth2 authorization flow.
        Opens browser, captures redirect, exchanges for token.
        """
        from http.server import BaseHTTPRequestHandler, HTTPServer
        import threading
        import time

        client_id = self.creds.require("LINKEDIN_CLIENT_ID", "LinkedIn App Client ID")
        client_secret = self.creds.require("LINKEDIN_CLIENT_SECRET", "LinkedIn App Client Secret")
        redirect_uri = self.creds.get("LINKEDIN_REDIRECT_URI", "http://localhost:8080/oauth/linkedin")

        port = 8080
        auth_code_holder = {"code": None, "error": None}

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                parsed = urllib.parse.urlparse(self.path)
                params = urllib.parse.parse_qs(parsed.query)
                if "code" in params:
                    auth_code_holder["code"] = params["code"][0]
                elif "error" in params:
                    auth_code_holder["error"] = params.get("error_description", ["Unknown"])[0]
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(b"<html><body><h2>LinkedIn connected!</h2><p>Close this tab.</p></body></html>")

            def log_message(self, *args):
                pass

        auth_url = (
            f"{LINKEDIN_AUTH_URL}?"
            f"response_type=code"
            f"&client_id={client_id}"
            f"&redirect_uri={urllib.parse.quote(redirect_uri)}"
            f"&scope={urllib.parse.quote(' '.join(LINKEDIN_SCOPES))}"
            f"&state=linkedin-oauth"
        )

        server = HTTPServer(("localhost", port), Handler)
        thread = threading.Thread(target=server.handle_request, daemon=True)
        thread.start()

        print(f"\n[LinkedIn OAuth2] Opening browser...")
        webbrowser.open(auth_url)
        thread.join(timeout=300)

        if auth_code_holder.get("error"):
            raise RuntimeError(f"LinkedIn OAuth error: {auth_code_holder['error']}")
        if not auth_code_holder.get("code"):
            raise RuntimeError("No auth code received.")

        # Exchange code for token
        resp = requests.post(LINKEDIN_TOKEN_URL, data={
            "grant_type": "authorization_code",
            "code": auth_code_holder["code"],
            "redirect_uri": redirect_uri,
            "client_id": client_id,
            "client_secret": client_secret,
        })
        resp.raise_for_status()
        token = resp.json()
        token["expires_at"] = time.time() + token.get("expires_in", 5184000)  # 60 days

        self.creds.store_oauth_token("LINKEDIN", token)
        print("  ✓ LinkedIn authorized.\n")
        return token

    # ------------------------------------------------------------------ #
    # Content Operations (SAFE MODE — post scheduling only)               #
    # ------------------------------------------------------------------ #

    def publish_post(self, text: str, visibility: str = "PUBLIC") -> ActionResult:
        """
        Publish a text post to LinkedIn feed.
        MUST be called only after human approval.

        visibility: "PUBLIC" | "CONNECTIONS"
        """
        if not self._person_urn:
            return ActionResult(success=False, error="Not connected")

        try:
            visibility_map = {
                "PUBLIC": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
                "CONNECTIONS": {"com.linkedin.ugc.MemberNetworkVisibility": "CONNECTIONS"},
            }

            body = {
                "author": self._person_urn,
                "lifecycleState": "PUBLISHED",
                "specificContent": {
                    "com.linkedin.ugc.ShareContent": {
                        "shareCommentary": {"text": text},
                        "shareMediaCategory": "NONE",
                    }
                },
                "visibility": visibility_map.get(visibility, visibility_map["PUBLIC"]),
            }

            data = self._post("/ugcPosts", json=body)
            post_id = data.get("id", "")

            self._log_action("publish_post", {
                "post_id": post_id,
                "text_length": len(text),
                "visibility": visibility,
            })

            return ActionResult(
                success=True,
                data={"post_id": post_id, "text": text, "visibility": visibility},
            )
        except Exception as e:
            logger.error("LinkedIn publish failed: %s", e)
            return ActionResult(success=False, error=str(e))

    def get_profile(self) -> Optional[Dict]:
        """Return basic profile information."""
        try:
            profile = self._get("/me")
            email_resp = self._get("/emailAddress?q=members&projection=(elements*(handle~))")
            email = (
                email_resp.get("elements", [{}])[0]
                .get("handle~", {})
                .get("emailAddress", "")
            )
            return {
                "id": profile.get("id"),
                "name": f"{profile.get('localizedFirstName', '')} {profile.get('localizedLastName', '')}",
                "email": email,
                "urn": self._person_urn,
            }
        except Exception as e:
            logger.error("get_profile failed: %s", e)
            return None

    # ------------------------------------------------------------------ #
    # HTTP helpers                                                         #
    # ------------------------------------------------------------------ #

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
            "X-Restli-Protocol-Version": "2.0.0",
        }

    def _get(self, path: str, params: Optional[Dict] = None) -> Dict:
        resp = requests.get(f"{LINKEDIN_API_BASE}{path}", headers=self._headers(), params=params)
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, json: Optional[Dict] = None) -> Dict:
        resp = requests.post(f"{LINKEDIN_API_BASE}{path}", headers=self._headers(), json=json)
        resp.raise_for_status()
        return resp.json()
