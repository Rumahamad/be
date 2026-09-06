"""Simple local launcher for the BNC API."""

import os

import uvicorn

from app.main import app

if __name__ == "__main__":
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=int(os.getenv("PORT", "8080")),
    )
