import os
import re
import uuid
import shutil
import asyncio
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, HttpUrl

import yt_dlp


# ============================================================
# CONFIGURATION
# ============================================================

APP_NAME = "Softonix Instagram Downloader API"

BASE_DIR = Path(tempfile.gettempdir()) / "softonix_instagram_downloader"
BASE_DIR.mkdir(parents=True, exist_ok=True)

MAX_FILE_SIZE = 500 * 1024 * 1024  # 500 MB
DOWNLOAD_TIMEOUT = 180


# ============================================================
# FASTAPI
# ============================================================

app = FastAPI(
    title=APP_NAME,
    version="1.0.0"
)


# ============================================================
# CORS
# ============================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# REQUEST MODEL
# ============================================================

class InstagramRequest(BaseModel):
    url: HttpUrl


class DownloadRequest(BaseModel):
    url: HttpUrl
    index: int = 0


# ============================================================
# URL VALIDATION
# ============================================================

def validate_instagram_url(url: str) -> str:

    url = str(url).strip()

    pattern = re.compile(
        r"^https?://"
        r"(www\.)?"
        r"(instagram\.com|m\.instagram\.com)"
        r"(/.*)?$",
        re.IGNORECASE
    )

    if not pattern.match(url):
        raise HTTPException(
            status_code=400,
            detail="Only valid Instagram URLs are supported."
        )

    return url


# ============================================================
# YT-DLP OPTIONS
# ============================================================

def get_info_options():

    return {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,

        "noplaylist": False,

        "extract_flat": False,

        "socket_timeout": 30,

        "retries": 2,

        "fragment_retries": 2,

        "http_headers": {
            "User-Agent":
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
        }
    }


def get_download_options(output_template: str):

    return {
        "quiet": True,
        "no_warnings": True,

        "noplaylist": False,

        "socket_timeout": 30,

        "retries": 2,

        "fragment_retries": 2,

        "outtmpl": output_template,

        "restrictfilenames": True,

        "overwrites": True,

        "http_headers": {
            "User-Agent":
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
        },

        "max_filesize": MAX_FILE_SIZE,
    }


# ============================================================
# MEDIA TYPE
# ============================================================

def detect_media_type(info: dict) -> str:

    webpage_url = (
        info.get("webpage_url")
        or info.get("original_url")
        or ""
    ).lower()

    extractor_key = (
        info.get("extractor_key")
        or ""
    ).lower()

    if "reel" in webpage_url:
        return "reel"

    if "instagram" in extractor_key:

        if info.get("_type") == "playlist":
            return "carousel"

        if info.get("entries"):
            return "carousel"

        ext = info.get("ext")

        if ext in ["mp4", "webm", "mov"]:
            return "video"

        return "photo"

    return "media"


# ============================================================
# FORMAT MEDIA ITEM
# ============================================================

def format_media_item(
    info: dict,
    index: int
) -> dict:

    width = info.get("width")
    height = info.get("height")

    filesize = (
        info.get("filesize")
        or info.get("filesize_approx")
    )

    thumbnail = (
        info.get("thumbnail")
        or ""
    )

    ext = (
        info.get("ext")
        or ""
    )

    media_type = "photo"

    if ext.lower() in [
        "mp4",
        "webm",
        "mov",
        "m4v"
    ]:
        media_type = "video"

    return {
        "index": index,

        "type": media_type,

        "thumbnail": thumbnail,

        "width": width,

        "height": height,

        "filesize": filesize,

        "ext": ext,

        "duration": info.get("duration"),

        "title": (
            info.get("title")
            or "Instagram media"
        )
    }


# ============================================================
# EXTRACT MEDIA ITEMS
# ============================================================

def extract_items(info: dict) -> list:

    items = []

    entries = info.get("entries")

    if entries:

        for entry in entries:

            if not entry:
                continue

            items.append(entry)

    else:

        items.append(info)

    results = []

    for index, item in enumerate(items):

        try:

            results.append(
                format_media_item(
                    item,
                    index
                )
            )

        except Exception:

            continue

    return results


# ============================================================
# INFO EXTRACTION
# ============================================================

def extract_instagram_info(
    url: str
) -> dict:

    options = get_info_options()

    with yt_dlp.YoutubeDL(options) as ydl:

        try:

            info = ydl.extract_info(
                url,
                download=False
            )

        except Exception as exc:

            error_text = str(exc)

            raise RuntimeError(
                error_text
            )

    if not info:

        raise RuntimeError(
            "Instagram did not return media information."
        )

    items = extract_items(info)

    return {
        "success": True,

        "source_url": url,

        "title": (
            info.get("title")
            or "Instagram media"
        ),

        "uploader": (
            info.get("uploader")
            or info.get("channel")
            or ""
        ),

        "items": items,

        "count": len(items)
    }


# ============================================================
# FIND DOWNLOADED FILE
# ============================================================

def find_downloaded_files(
    folder: Path
) -> list:

    allowed_extensions = {
        ".mp4",
        ".webm",
        ".mov",
        ".m4v",
        ".jpg",
        ".jpeg",
        ".png",
        ".webp"
    }

    files = []

    for file in folder.rglob("*"):

        if not file.is_file():
            continue

        if file.suffix.lower() not in allowed_extensions:
            continue

        try:

            if file.stat().st_size <= 0:
                continue

            if file.stat().st_size > MAX_FILE_SIZE:
                continue

        except OSError:

            continue

        files.append(file)

    return sorted(
        files,
        key=lambda x: x.stat().st_mtime
    )


# ============================================================
# HEALTH
# ============================================================

@app.get("/")
async def root():

    return {
        "success": True,
        "service": APP_NAME,
        "status": "online"
    }


@app.get("/health")
async def health():

    return {
        "status": "healthy"
    }


# ============================================================
# INSTAGRAM INFO
# ============================================================

@app.post("/api/instagram/info")
async def instagram_info(
    request: InstagramRequest
):

    url = validate_instagram_url(
        str(request.url)
    )

    try:

        result = await asyncio.wait_for(
            asyncio.to_thread(
                extract_instagram_info,
                url
            ),
            timeout=DOWNLOAD_TIMEOUT
        )

        return result

    except asyncio.TimeoutError:

        raise HTTPException(
            status_code=504,
            detail="Instagram processing timed out."
        )

    except Exception as exc:

        message = str(exc)

        if not message:
            message = (
                "Unable to extract Instagram media."
            )

        raise HTTPException(
            status_code=500,
            detail=message
        )


# ============================================================
# DOWNLOAD MEDIA
# ============================================================

def download_instagram_media(
    url: str,
    index: int
):

    job_id = uuid.uuid4().hex

    job_dir = (
        BASE_DIR /
        job_id
    )

    job_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    try:

        info_options =
            get_info_options()

        with yt_dlp.YoutubeDL(
            info_options
        ) as ydl:

            info = ydl.extract_info(
                url,
                download=False
            )


        entries = info.get("entries")


        if entries:

            entries = [
                item
                for item in entries
                if item
            ]

        else:

            entries = [info]


        if index < 0 or index >= len(entries):

            raise ValueError(
                "Invalid media index."
            )


        selected = entries[index]


        selected_url = (
            selected.get("webpage_url")
            or selected.get("original_url")
            or url
        )


        output_template = str(
            job_dir /
            "%(title).80s-%(id)s.%(ext)s"
        )


        download_options =
            get_download_options(
                output_template
            )


        with yt_dlp.YoutubeDL(
            download_options
        ) as ydl:

            ydl.download(
                [selected_url]
            )


        files = find_downloaded_files(
            job_dir
        )


        if not files:

            raise RuntimeError(
                "No downloadable media file was created."
            )


        return files[0]


    except Exception:

        shutil.rmtree(
            job_dir,
            ignore_errors=True
        )

        raise


# ============================================================
# DOWNLOAD ENDPOINT
# ============================================================

@app.post("/api/instagram/download")
async def instagram_download(
    request: DownloadRequest
):

    url = validate_instagram_url(
        str(request.url)
    )

    index = int(
        request.index
    )

    if index < 0:
        raise HTTPException(
            status_code=400,
            detail="Invalid media index."
        )


    try:

        file_path = await asyncio.wait_for(
            asyncio.to_thread(
                download_instagram_media,
                url,
                index
            ),
            timeout=DOWNLOAD_TIMEOUT
        )


    except asyncio.TimeoutError:

        raise HTTPException(
            status_code=504,
            detail="Media download timed out."
        )


    except Exception as exc:

        message = str(exc)

        if not message:
            message = (
                "Unable to download Instagram media."
            )

        raise HTTPException(
            status_code=500,
            detail=message
        )


    media_type = (
        "application/octet-stream"
    )


    extension =
        file_path.suffix.lower()


    if extension == ".mp4":
        media_type = "video/mp4"

    elif extension == ".webm":
        media_type = "video/webm"

    elif extension == ".mov":
        media_type = "video/quicktime"

    elif extension in [
        ".jpg",
        ".jpeg"
    ]:
        media_type = "image/jpeg"

    elif extension == ".png":
        media_type = "image/png"

    elif extension == ".webp":
        media_type = "image/webp"


    return FileResponse(
        path=str(file_path),
        media_type=media_type,
        filename=file_path.name,
        background=None
    )


# ============================================================
# RUN LOCAL
# ============================================================

if __name__ == "__main__":

    import uvicorn

    port = int(
        os.environ.get(
            "PORT",
            "8000"
        )
    )

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port
    )
