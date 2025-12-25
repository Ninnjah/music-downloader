import os
from pathlib import Path
from typing import List
from urllib.parse import quote, unquote

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from fastapi.responses import FileResponse

import config
from models.request import (
    AlbumDownloadRequest,
    DownloadRequest,
    ReverseDownloadRequest,
    ReverseLookupRequest,
    SearchRequest,
)
from models.response import TrackResponse
from services.metadata import MetadataService
from services.navidrome import NavidromeService
from services.spotify import SpotifyService
from services.tasks import (
    album_download_status,
    cleanup_temp_file,
    download_album_track,
    download_and_process,
    download_status,
    reverse_download_and_process,
)
from services.youtube import YouTubeService
from utils.file_handler import get_download_path

# Initialize services
try:
    spotify_service = SpotifyService()
except Exception as e:
    print(f"Warning: Spotify service initialization failed: {e}")
    spotify_service = None

youtube_service = YouTubeService()
metadata_service = MetadataService()
navidrome_service = NavidromeService()

router = APIRouter(prefix="/api")


@router.post("/search", response_model=List[TrackResponse])
async def search_tracks(request: SearchRequest):
    """Search for tracks on Spotify"""
    if not spotify_service:
        raise HTTPException(status_code=500, detail="Spotify service not configured")

    try:
        tracks = spotify_service.search_tracks(request.query, request.limit)
        return tracks
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")


@router.post("/reverse/youtube")
async def reverse_lookup_youtube(request: ReverseLookupRequest):
    """Given a YouTube/YouTube Music URL, extract title via yt-dlp and search Spotify."""
    if not spotify_service:
        raise HTTPException(status_code=500, detail="Spotify service not configured")

    try:
        yt_info = youtube_service.extract_video_info(request.url)
        if not yt_info.get("success"):
            raise HTTPException(
                status_code=400,
                detail=f"Failed to read YouTube URL: {yt_info.get('error', 'Unknown error')}",
            )

        title = (yt_info.get("title") or "").strip()
        if not title:
            raise HTTPException(status_code=400, detail="YouTube title was empty")

        spotify_candidates = spotify_service.search_tracks(title, limit=5)

        return {
            "youtube": yt_info,
            "query": title,
            "spotify_candidates": spotify_candidates,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Reverse lookup failed: {str(e)}")


@router.post("/search/tracks/top")
async def search_tracks_top(request: SearchRequest):
    """Search for tracks on Spotify with a small, fixed default suitable for pick-lists."""
    if not spotify_service:
        raise HTTPException(status_code=500, detail="Spotify service not configured")

    try:
        limit = request.limit or 5
        limit = max(1, min(int(limit), 10))
        return spotify_service.search_tracks(request.query, limit=limit)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")


@router.post("/search/albums")
async def search_albums(request: SearchRequest):
    """Search for albums on Spotify"""
    if not spotify_service:
        raise HTTPException(status_code=500, detail="Spotify service not configured")

    try:
        albums = spotify_service.search_albums(request.query, request.limit)
        return albums
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Album search failed: {str(e)}")


@router.get("/album/{album_id}")
async def get_album(album_id: str):
    """Get album details including all tracks"""
    if not spotify_service:
        raise HTTPException(status_code=500, detail="Spotify service not configured")

    try:
        album = spotify_service.get_album_details(album_id)
        if not album:
            raise HTTPException(status_code=404, detail="Album not found")
        return album
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching album: {str(e)}")


@router.get("/track/{track_id}", response_model=TrackResponse)
async def get_track(track_id: str):
    """Get details for a specific track"""
    if not spotify_service:
        raise HTTPException(status_code=500, detail="Spotify service not configured")

    try:
        track = spotify_service.get_track_details(track_id)
        if not track:
            raise HTTPException(status_code=404, detail="Track not found")
        return track
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching track: {str(e)}")


@router.post("/download")
async def download_track(request: DownloadRequest, background_tasks: BackgroundTasks):
    """Start downloading a track"""
    if not spotify_service:
        raise HTTPException(status_code=500, detail="Spotify service not configured")

    # Validate location
    if request.location not in ["local", "navidrome"]:
        request.location = "local"  # Default to local

    # Initialize status
    location_msg = (
        "local downloads folder" if request.location == "local" else "Navidrome server"
    )
    download_status[request.track_id] = {
        "status": "queued",
        "message": f"Download queued for {location_msg}",
        "progress": 0,
        "stage": "queued",
    }

    # Add background task with location and video_id parameters
    background_tasks.add_task(
        download_and_process,
        youtube_service=youtube_service,
        spotify_service=spotify_service,
        metadata_service=metadata_service,
        navidrome_service=navidrome_service,
        track_id=request.track_id,
        location=request.location,
        video_id=request.video_id,
    )

    return {
        "status": "queued",
        "message": f"Download started to {location_msg}",
        "track_id": request.track_id,
    }


@router.post("/reverse/download")
async def reverse_download(
    request: ReverseDownloadRequest, background_tasks: BackgroundTasks
):
    """Finalize reverse flow: download YouTube URL and tag with chosen Spotify track or manual metadata."""
    if not spotify_service:
        raise HTTPException(status_code=500, detail="Spotify service not configured")

    # Validate location
    location = (
        request.location if request.location in ["local", "navidrome"] else "local"
    )
    location_msg = (
        "local downloads folder" if location == "local" else "Navidrome server"
    )

    # Create a synthetic job id (stable enough for polling)
    job_id = f"yt-{abs(hash((request.youtube_url, request.spotify_track_id or '', location))) % 10_000_000}"

    download_status[job_id] = {
        "status": "queued",
        "message": f"Reverse download queued for {location_msg}",
        "progress": 0,
        "stage": "queued",
    }

    background_tasks.add_task(
        reverse_download_and_process,
        youtube_service=youtube_service,
        spotify_service=spotify_service,
        metadata_service=metadata_service,
        navidrome_service=navidrome_service,
        job_id=job_id,
        youtube_url=request.youtube_url,
        location=location,
        spotify_track_id=request.spotify_track_id,
        metadata=request.metadata,
    )

    return {
        "status": "queued",
        "message": f"Reverse download started to {location_msg}",
        "job_id": job_id,
    }


@router.get("/download/status/{track_id}")
async def get_download_status(track_id: str):
    """Get download status for a track"""
    if track_id not in download_status:
        raise HTTPException(status_code=404, detail="Download not found")

    return download_status[track_id]


@router.post("/download/album")
async def download_album(
    request: AlbumDownloadRequest, background_tasks: BackgroundTasks
):
    """Start downloading all tracks from an album"""
    if not spotify_service:
        raise HTTPException(status_code=500, detail="Spotify service not configured")

    # Get album details
    album = spotify_service.get_album_details(request.album_id)
    if not album:
        raise HTTPException(status_code=404, detail="Album not found")

    # Validate location
    location = (
        request.location if request.location in ["local", "navidrome"] else "local"
    )
    location_msg = (
        "local downloads folder" if location == "local" else "Navidrome server"
    )

    # Initialize album status
    album_download_status[request.album_id] = {
        "status": "downloading",
        "album_name": album["name"],
        "artist": album["artist"],
        "total_tracks": len(album["tracks"]),
        "completed_tracks": 0,
        "failed_tracks": 0,
        "current_track": None,
        "track_ids": [t["id"] for t in album["tracks"]],
    }

    # Queue each track for download
    for track in album["tracks"]:
        download_status[track["id"]] = {
            "status": "queued",
            "message": f"Queued (Album: {album['name']})",
            "progress": 0,
            "stage": "queued",
            "album_id": request.album_id,
        }
        background_tasks.add_task(
            download_album_track,
            youtube_service=youtube_service,
            spotify_service=spotify_service,
            metadata_service=metadata_service,
            navidrome_service=navidrome_service,
            track_id=track["id"],
            location=location,
            album_id=request.album_id,
        )

    return {
        "status": "queued",
        "message": f"Album '{album['name']}' queued for download to {location_msg}",
        "album_id": request.album_id,
        "total_tracks": len(album["tracks"]),
    }


@router.get("/download/album/status/{album_id}")
async def get_album_download_status(album_id: str):
    """Get download status for an album"""
    if album_id not in album_download_status:
        raise HTTPException(status_code=404, detail="Album download not found")

    return album_download_status[album_id]


@router.get("/youtube/candidates/{track_id}")
async def get_youtube_candidates(track_id: str):
    """Get YouTube candidates for a track to let user choose if confidence is low"""
    if not spotify_service:
        raise HTTPException(status_code=500, detail="Spotify service not configured")

    try:
        # Get track details from Spotify
        track_info = spotify_service.get_track_details(track_id)
        if not track_info:
            raise HTTPException(status_code=404, detail="Track not found")

        # Search YouTube for candidates
        result = youtube_service.search_candidates(
            track_info["name"], track_info["artist"], track_info
        )

        return {
            "track": {
                "id": track_id,
                "name": track_info["name"],
                "artist": track_info["artist"],
                "album": track_info.get("album", ""),
            },
            **result,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error searching YouTube: {str(e)}"
        )


@router.get("/download/file/{track_id}")
async def download_file(
    track_id: str,
    filename: str = Query(...),
    background_tasks: BackgroundTasks = BackgroundTasks(),
):
    """Download a file (for local browser downloads) and delete temp file afterward"""
    if track_id not in download_status:
        raise HTTPException(status_code=404, detail="Download not found")

    status = download_status[track_id]
    if status.get("status") != "completed":
        raise HTTPException(status_code=400, detail="File not ready for download")

    file_path = status.get("file_path")
    if not file_path or not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found")

    # Decode URL-encoded filename for comparison
    decoded_filename = unquote(filename)
    actual_filename = os.path.basename(file_path)

    # Verify filename matches for security (compare decoded vs actual)
    if actual_filename != decoded_filename:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid filename. Expected: {actual_filename}, Got: {decoded_filename}",
        )

    # Check if this is a temp file (for local downloads) - delete after serving
    # Normalize paths for comparison
    temp_dir_path = str(Path(config.DOWNLOAD_DIR) / "temp")
    is_temp_file = temp_dir_path in file_path or "temp" in os.path.dirname(file_path)

    # Return file for browser to download (saves to user's Downloads folder)
    # Use RFC 5987 encoding for non-ASCII filenames in Content-Disposition header
    # This handles special characters like ć, č, š, etc.
    ascii_filename = (
        decoded_filename.encode("ascii", "ignore").decode("ascii") or "download.mp3"
    )
    encoded_filename = quote(decoded_filename)

    response = FileResponse(
        file_path,
        media_type="audio/mpeg",
        filename=ascii_filename,  # Fallback ASCII filename
        headers={
            "Content-Disposition": f"attachment; filename=\"{ascii_filename}\"; filename*=UTF-8''{encoded_filename}"
        },
    )

    # Delete temp file after download completes (only for local downloads)
    if is_temp_file:
        background_tasks.add_task(cleanup_temp_file, file_path)

    return response


@router.get("/track/{track_id}/exists")
async def check_track_exists(track_id: str):
    """Check if a track file already exists in downloads"""
    if not spotify_service:
        raise HTTPException(status_code=500, detail="Spotify service not configured")

    try:
        # Get track details from Spotify
        track_info = spotify_service.get_track_details(track_id)
        if not track_info:
            return {"exists": False}

        # Check if file exists
        download_path = get_download_path(
            track_info, config.DOWNLOAD_DIR, config.OUTPUT_FORMAT
        )
        file_exists = os.path.exists(download_path)

        return {
            "exists": file_exists,
            "file_path": download_path if file_exists else None,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error checking track: {str(e)}")


@router.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "spotify_configured": spotify_service is not None,
        "navidrome_path": config.NAVIDROME_MUSIC_PATH,
    }
