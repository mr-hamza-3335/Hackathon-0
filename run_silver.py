"""Entry point for the Silver upgrade — web UI + API + orchestrator.

Usage:
    python run_silver.py
    Open http://localhost:8000 in your browser.
"""

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "api.server:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
    )
