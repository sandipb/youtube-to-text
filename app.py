#!/usr/bin/env python3
"""
Podcast Cleaner Web App
FastAPI web interface for transcribing and cleaning YouTube videos.
"""

import json
import os
import uuid
from pathlib import Path
from typing import Dict, Any
from urllib.parse import quote

from fastapi import FastAPI, BackgroundTasks, HTTPException, Request
from fastapi.responses import Response, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from clean_podcast import process_video, extract_video_id

app = FastAPI(
    title="I Hate Video",
    description="Convert YouTube videos into clean, readable transcripts with AI-generated chapters and takeaways",
    version="1.0.0",
)

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Setup templates
templates = Jinja2Templates(directory="templates")

# Store jobs in memory (for simplicity)
jobs: Dict[str, Dict[str, Any]] = {}

# Persistent cache file
CACHE_FILE = Path(__file__).parent / "transcript_cache.json"


def load_cache() -> Dict[str, Any]:
    """Load transcript cache from disk."""
    if CACHE_FILE.exists():
        try:
            with open(CACHE_FILE, "r") as f:
                return json.load(f)
        except:
            return {}
    return {}


def save_cache(cache: Dict[str, Any]) -> None:
    """Save transcript cache to disk."""
    with open(CACHE_FILE, "w") as f:
        json.dump(cache, f)


# Cache completed transcripts by video ID
transcript_cache = load_cache()


class TranscribeRequest(BaseModel):
    url: str


class TranscribeResponse(BaseModel):
    job_id: str


class StatusResponse(BaseModel):
    status: str
    progress: str
    result: Dict[str, str] | None = None
    error: str | None = None


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Serve the main page."""
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/transcribe", response_model=TranscribeResponse)
async def transcribe(request: TranscribeRequest, background_tasks: BackgroundTasks):
    """Start a transcription job."""
    url = request.url.strip()

    if not url:
        raise HTTPException(status_code=400, detail="URL is required")

    # Extract video ID and check cache
    try:
        video_id = extract_video_id(url)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    # If we have a cached result, return it immediately
    if video_id in transcript_cache:
        job_id = str(uuid.uuid4())
        jobs[job_id] = {
            "status": "completed",
            "progress": "Loaded from cache",
            "result": transcript_cache[video_id],
            "error": None,
        }
        return TranscribeResponse(job_id=job_id)

    # Get API key from environment
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="GOOGLE_API_KEY not configured")

    # Create job
    job_id = str(uuid.uuid4())
    jobs[job_id] = {
        "status": "processing",
        "progress": "Starting...",
        "result": None,
        "error": None,
    }

    # Run in background task
    def run_job():
        try:

            def progress_callback(message):
                jobs[job_id]["progress"] = message

            result = process_video(url, api_key, progress_callback)
            jobs[job_id]["status"] = "completed"
            jobs[job_id]["result"] = result
            # Cache the result and save to disk
            transcript_cache[video_id] = result
            save_cache(transcript_cache)
        except Exception as e:
            jobs[job_id]["status"] = "error"
            jobs[job_id]["error"] = str(e)

    background_tasks.add_task(run_job)

    return TranscribeResponse(job_id=job_id)


@app.get("/status/{job_id}")
async def status(job_id: str):
    """Check job status."""
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    response = {
        "status": job["status"],
        "progress": job["progress"],
    }

    if job["status"] == "completed":
        response["result"] = {
            "title": job["result"]["title"],
            "markdown": job["result"]["markdown"],
            "filename": job["result"]["filename"],
        }
    elif job["status"] == "error":
        response["error"] = job["error"]

    return response


@app.get("/download/{job_id}")
async def download(job_id: str):
    """Download the transcript as a markdown file."""
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job["status"] != "completed":
        raise HTTPException(status_code=400, detail="Job not completed")

    result = job["result"]
    # Use ASCII-safe filename and UTF-8 encoded filename for broader compatibility
    safe_filename = result["filename"].encode("ascii", "ignore").decode()
    if not safe_filename:
        safe_filename = "transcript.md"

    # URL-encode the filename for the filename* parameter (RFC 5987)
    encoded_filename = quote(result["filename"], safe="")

    return Response(
        content=result["markdown"],
        media_type="text/markdown",
        headers={
            "Content-Disposition": f"attachment; filename=\"{safe_filename}\"; filename*=UTF-8''{encoded_filename}"
        },
    )


@app.get("/download/{job_id}/pdf")
async def download_pdf(job_id: str, font: str = "Times New Roman"):
    """Download the transcript as a PDF file."""
    from weasyprint import HTML, CSS
    import markdown
    import io

    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job["status"] != "completed":
        raise HTTPException(status_code=400, detail="Job not completed")

    result = job["result"]

    # Sanitize font name to prevent CSS injection
    allowed_fonts = [
        "Arial",
        "Calibri",
        "Comic Sans MS",
        "Garamond",
        "Georgia",
        "Tahoma",
        "Times New Roman",
        "Wingdings",
    ]
    if font not in allowed_fonts:
        font = "Times New Roman"

    # Convert markdown to HTML
    md_content = result["markdown"]
    html_content = markdown.markdown(md_content, extensions=["tables", "fenced_code"])

    # Wrap in full HTML document with styling
    full_html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>{result["title"]}</title>
</head>
<body>
{html_content}
</body>
</html>"""

    # PDF styling with selected font
    css = CSS(
        string=f"""
        @page {{
            margin: 1in;
            size: letter;
        }}
        body {{
            font-family: "{font}", sans-serif;
            font-size: 12pt;
            line-height: 1.5;
            color: #333;
        }}
        h1 {{
            font-family: "{font}", sans-serif;
            font-size: 18pt;
            margin-bottom: 0.5em;
        }}
        h2 {{
            font-family: "{font}", sans-serif;
            font-size: 14pt;
            margin-top: 1em;
            margin-bottom: 0.5em;
            border-bottom: 1px solid #ccc;
            padding-bottom: 0.2em;
        }}
        img {{
            max-width: 100%;
            height: auto;
        }}
        ul, ol {{
            margin-left: 1.5em;
        }}
        li {{
            margin-bottom: 0.3em;
        }}
    """
    )

    # Generate PDF
    pdf_buffer = io.BytesIO()
    HTML(string=full_html).write_pdf(pdf_buffer, stylesheets=[css])
    pdf_buffer.seek(0)

    # Filename handling
    pdf_filename = result["filename"].replace(".md", ".pdf")
    safe_filename = pdf_filename.encode("ascii", "ignore").decode()
    if not safe_filename:
        safe_filename = "transcript.pdf"
    encoded_filename = quote(pdf_filename, safe="")

    return Response(
        content=pdf_buffer.read(),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename=\"{safe_filename}\"; filename*=UTF-8''{encoded_filename}"
        },
    )


if __name__ == "__main__":
    # Load .env file if it exists
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ[key] = value

    print("Starting Podcast Cleaner Web App...")
    print("Open http://127.0.0.1:8080 in your browser")

    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8080)
