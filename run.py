#!/usr/bin/env python3
"""Launch the web server: python run.py  ->  http://127.0.0.1:8000"""

import uvicorn

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=False)
