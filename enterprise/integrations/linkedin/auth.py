"""
LinkedIn OAuth2 Authorization — CLI Entry Point
================================================
Run this once to authorize the LinkedIn integration:

    python -m enterprise.integrations.linkedin.auth

This opens a browser for LinkedIn's OAuth consent screen,
captures the authorization code via a local HTTP callback server,
exchanges it for tokens, and stores them in the encrypted credential vault.

Safe Mode — only these scopes are requested:
    - openid           (OpenID Connect identity)
    - profile          (read basic profile: name, ID)
    - w_member_social  (publish posts)

No scraping, no auto-connect, no messaging automation.
"""

import sys
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


def main() -> None:
    print("\n=== LinkedIn OAuth2 Authorization (Safe Mode) ===\n")

    # Guard against non-interactive invocation
    if not sys.stdin.isatty():
        print("[ERROR] LinkedIn authorization requires an interactive terminal.")
        print("        Run: python -m enterprise.integrations.linkedin.auth")
        sys.exit(1)

    from enterprise.integrations.linkedin.client import LinkedInClient

    client = LinkedInClient()

    print("[LinkedIn] Starting OAuth2 authorization flow...")
    print("           This will open your browser for LinkedIn consent.\n")

    try:
        token = client.authorize()
        print("\n[LinkedIn] Authorization successful!")

        # Verify by fetching profile
        profile = client.get_profile()
        if profile:
            print(f"  Connected as: {profile.get('name', 'Unknown')}")
            print(f"  LinkedIn ID: {profile.get('id', 'N/A')}")
        else:
            print("  [Warning] Could not fetch profile — token stored but may need verification.")

        print("\n  LinkedIn integration is ready.")
        print("  You can now use: POST /api/v2/linkedin/draft\n")

    except KeyboardInterrupt:
        print("\n\nAuthorization cancelled.\n")
        sys.exit(0)
    except Exception as e:
        print(f"\n[ERROR] Authorization failed: {e}")
        print("\nTroubleshooting:")
        print("  1. Ensure LINKEDIN_CLIENT_ID and LINKEDIN_CLIENT_SECRET are set in .env")
        print("  2. Ensure http://localhost:8080/oauth/linkedin is in your LinkedIn App redirect URIs")
        print("  3. Ensure your LinkedIn App has 'Share on LinkedIn' product enabled")
        sys.exit(1)


if __name__ == "__main__":
    main()
