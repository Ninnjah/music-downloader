import os
import re
import shutil
import time
from pathlib import Path
from typing import Dict, Optional
from urllib.parse import quote

import config
from services.metadata import MetadataService
from services.navidrome import NavidromeService
from services.spotify import SpotifyService
from services.youtube import YouTubeService
from utils.file_handler import get_download_path

# Download status storages (in production, use Redis or a database)
download_status: Dict[str, Dict] = {}
album_download_status: Dict[str, Dict] = {}


def download_and_process(
    youtube_service: YouTubeService,
    spotify_service: SpotifyService,
    metadata_service: MetadataService,
    navidrome_service: NavidromeService,
    track_id: str,
    location: str = "local",
    video_id: Optional[str] = None,
):
    """Background task to download and process a track"""
    try:
        download_status[track_id] = {
            "status": "processing",
            "message": "Fetching track info...",
            "stage": "fetching",
            "progress": 10,
        }

        # Get track details from Spotify
        track_info = spotify_service.get_track_details(track_id)
        if not track_info:
            download_status[track_id] = {
                "status": "error",
                "message": "Could not fetch track information",
                "progress": 0,
            }
            return

        download_status[track_id] = {
            "status": "processing",
            "message": "Preparing download location...",
            "stage": "preparing",
            "progress": 15,
        }

        # Determine download path based on location preference
        if location == "navidrome":
            # Download directly to Navidrome music directory with proper structure (Artist/Album/)
            # First download to temp location, then copy to Navidrome directory
            temp_dir = os.path.join(config.DOWNLOAD_DIR, "temp")
            Path(temp_dir).mkdir(parents=True, exist_ok=True)
            download_path = get_download_path(
                track_info, temp_dir, config.OUTPUT_FORMAT
            )
            print(f"Downloading track {track_id} for Navidrome: {download_path}")
        else:
            # For local downloads: download to temp folder, then serve via browser download
            # This allows each user's browser to save to their own Downloads folder
            temp_dir = os.path.join(config.DOWNLOAD_DIR, "temp")
            Path(temp_dir).mkdir(parents=True, exist_ok=True)
            download_path = get_download_path(
                track_info, temp_dir, config.OUTPUT_FORMAT
            )
            print(
                f"Downloading track {track_id} for local browser download: {download_path}"
            )

        download_status[track_id] = {
            "status": "processing",
            "message": "Searching YouTube and downloading...",
            "stage": "downloading",
            "progress": 30,
        }

        # Download - pass full track_info for better matching
        # If video_id is provided, download that specific video
        download_result = youtube_service.search_and_download(
            track_info["name"],
            track_info["artist"],
            download_path,
            track_info,  # Pass full track info for validation
            video_id,  # Specific YouTube video if user selected one
        )

        if not download_result.get("success"):
            download_status[track_id] = {
                "status": "error",
                "message": f"Download failed: {download_result.get('error', 'Unknown error')}",
                "progress": 0,
            }
            return

        download_status[track_id] = {
            "status": "processing",
            "message": "Applying metadata...",
            "stage": "tagging",
            "progress": 85,
        }

        # Apply metadata to downloaded file
        metadata_service.apply_metadata(download_result["file_path"], track_info)

        # Handle completion based on location
        if location == "navidrome":
            # Copy to Navidrome music directory with proper structure (Artist/Album/)
            download_status[track_id] = {
                "status": "processing",
                "message": "Copying to Navidrome library...",
                "stage": "copying",
                "progress": 90,
            }

            try:
                # Get target path in Navidrome directory (Artist/Album/filename.mp3)
                target_path = navidrome_service.get_target_path(
                    track_info, config.OUTPUT_FORMAT
                )

                # Copy file to Navidrome directory
                shutil.copy2(download_result["file_path"], target_path)

                # Clean up temp file
                if os.path.exists(download_result["file_path"]):
                    os.remove(download_result["file_path"])

                # Trigger Navidrome scan
                navidrome_result = navidrome_service.finalize_track(str(target_path))

                if navidrome_result.get("success"):
                    download_status[track_id] = {
                        "status": "completed",
                        "message": "Track successfully added to Navidrome library",
                        "file_path": str(target_path),
                        "stage": "completed",
                        "progress": 100,
                    }
                else:
                    download_status[track_id] = {
                        "status": "completed",
                        "message": f"Track added to library (scan may need manual trigger): {navidrome_result.get('error', '')}",
                        "file_path": str(target_path),
                        "stage": "completed",
                        "progress": 100,
                    }
            except Exception as e:
                download_status[track_id] = {
                    "status": "error",
                    "message": f"Failed to copy to Navidrome: {str(e)}",
                    "progress": 0,
                }
        else:
            # For local downloads, provide download URL for browser to handle
            # The file is ready, browser will download it to user's Downloads folder
            filename = os.path.basename(download_result["file_path"])
            # URL encode the filename to handle special characters (use query parameter)
            encoded_filename = quote(filename, safe="")
            download_url = f"api/download/file/{track_id}?filename={encoded_filename}"
            download_status[track_id] = {
                "status": "completed",
                "message": "Track ready for download",
                "file_path": download_result["file_path"],
                "download_url": download_url,  # URL to trigger browser download
                "stage": "completed",
                "progress": 100,
            }

    except Exception as e:
        download_status[track_id] = {
            "status": "error",
            "message": f"Error: {str(e)}",
            "progress": 0,
        }


def reverse_download_and_process(
    youtube_service: YouTubeService,
    spotify_service: SpotifyService,
    metadata_service: MetadataService,
    navidrome_service: NavidromeService,
    job_id: str,
    youtube_url: str,
    location: str,
    spotify_track_id: Optional[str],
    metadata: Optional[Dict],
):
    """Background task: download a specific YouTube URL and tag using either Spotify track or manual metadata."""
    try:
        download_status[job_id] = {
            "status": "processing",
            "message": "Extracting YouTube info...",
            "stage": "fetching",
            "progress": 10,
        }

        yt_info = youtube_service.extract_video_info(youtube_url)
        if not yt_info.get("success"):
            download_status[job_id] = {
                "status": "error",
                "message": f"Failed to read YouTube URL: {yt_info.get('error', 'Unknown error')}",
                "progress": 0,
            }
            return

        video_id = yt_info.get("video_id")
        if not video_id:
            download_status[job_id] = {
                "status": "error",
                "message": "Could not determine YouTube video id",
                "progress": 0,
            }
            return

        track_info: Optional[Dict] = None
        if spotify_track_id:
            download_status[job_id] = {
                "status": "processing",
                "message": "Fetching Spotify track info...",
                "stage": "fetching",
                "progress": 20,
            }
            track_info = spotify_service.get_track_details(spotify_track_id)
            if not track_info:
                download_status[job_id] = {
                    "status": "error",
                    "message": "Could not fetch Spotify track information",
                    "progress": 0,
                }
                return
        else:
            # Validate manual metadata (name + artist required)
            md = metadata or {}
            name = (md.get("name") or md.get("title") or "").strip()
            artist = (md.get("artist") or "").strip()
            if not name or not artist:
                download_status[job_id] = {
                    "status": "error",
                    "message": "Manual metadata requires 'name' (song title) and 'artist'",
                    "progress": 0,
                }
                return

            # Default album/album_artist to "YouTube" if not provided
            album_artist = (md.get("album_artist") or "").strip() or "YouTube"
            album = (md.get("album") or md.get("album_name") or "").strip() or "YouTube"

            # If user didn't provide album art, use YouTube thumbnail
            album_art = md.get("album_art") or yt_info.get("thumbnail") or None

            track_info = {
                "id": job_id,
                "name": name,
                "artist": artist,
                "artists": [a.strip() for a in re.split(r"[;,]", artist) if a.strip()],
                "album_artist": album_artist,
                "album": album,
                "track_number": int(md.get("track_number") or 1),
                "release_date": (md.get("release_date") or "").strip(),
                "album_art": album_art,
                "duration_ms": 0,
                "external_url": yt_info.get("webpage_url") or youtube_url,
                "preview_url": None,
            }

        download_status[job_id] = {
            "status": "processing",
            "message": "Preparing download location...",
            "stage": "preparing",
            "progress": 25,
        }

        # Determine download path
        temp_dir = os.path.join(config.DOWNLOAD_DIR, "temp")
        Path(temp_dir).mkdir(parents=True, exist_ok=True)
        download_path = get_download_path(track_info, temp_dir, config.OUTPUT_FORMAT)

        download_status[job_id] = {
            "status": "processing",
            "message": "Downloading from YouTube...",
            "stage": "downloading",
            "progress": 40,
        }
        download_result = youtube_service.download_by_video_id(video_id, download_path)
        if not download_result.get("success"):
            download_status[job_id] = {
                "status": "error",
                "message": f"Download failed: {download_result.get('error', 'Unknown error')}",
                "progress": 0,
            }
            return

        download_status[job_id] = {
            "status": "processing",
            "message": "Applying metadata...",
            "stage": "tagging",
            "progress": 85,
        }
        metadata_service.apply_metadata(download_result["file_path"], track_info)

        # Handle completion based on location
        if location == "navidrome":
            download_status[job_id] = {
                "status": "processing",
                "message": "Copying to Navidrome library...",
                "stage": "copying",
                "progress": 90,
            }
            try:
                target_path = navidrome_service.get_target_path(
                    track_info, config.OUTPUT_FORMAT
                )
                shutil.copy2(download_result["file_path"], target_path)
                if os.path.exists(download_result["file_path"]):
                    os.remove(download_result["file_path"])

                navidrome_result = navidrome_service.finalize_track(str(target_path))
                download_status[job_id] = {
                    "status": "completed",
                    "message": "Track successfully added to Navidrome library"
                    if navidrome_result.get("success")
                    else f"Track added to library (scan may need manual trigger): {navidrome_result.get('error', '')}",
                    "file_path": str(target_path),
                    "stage": "completed",
                    "progress": 100,
                }
            except Exception as e:
                download_status[job_id] = {
                    "status": "error",
                    "message": f"Failed to copy to Navidrome: {str(e)}",
                    "progress": 0,
                }
        else:
            filename = os.path.basename(download_result["file_path"])
            encoded_filename = quote(filename, safe="")
            download_url = f"api/download/file/{job_id}?filename={encoded_filename}"
            download_status[job_id] = {
                "status": "completed",
                "message": "Track ready for download",
                "file_path": download_result["file_path"],
                "download_url": download_url,
                "stage": "completed",
                "progress": 100,
            }

    except Exception as e:
        download_status[job_id] = {
            "status": "error",
            "message": f"Error: {str(e)}",
            "progress": 0,
        }


def download_album_track(
    youtube_service: YouTubeService,
    spotify_service: SpotifyService,
    metadata_service: MetadataService,
    navidrome_service: NavidromeService,
    track_id: str,
    location: str,
    album_id: str,
) -> None:
    """Download a single track as part of an album download"""
    try:
        # Update album status
        if album_id in album_download_status:
            album_download_status[album_id]["current_track"] = track_id

        # Use existing download function
        download_and_process(
            youtube_service=youtube_service,
            spotify_service=spotify_service,
            metadata_service=metadata_service,
            navidrome_service=navidrome_service,
            track_id=track_id,
            location=track_id,
            video_id=None,
        )

        # Update album completion status
        if album_id in album_download_status:
            status = download_status.get(track_id, {})
            if status.get("status") == "completed":
                album_download_status[album_id]["completed_tracks"] += 1
            else:
                album_download_status[album_id]["failed_tracks"] += 1

            # Check if album is complete
            total = album_download_status[album_id]["total_tracks"]
            completed = album_download_status[album_id]["completed_tracks"]
            failed = album_download_status[album_id]["failed_tracks"]

            if completed + failed >= total:
                album_download_status[album_id]["status"] = "completed"
                album_download_status[album_id]["current_track"] = None
    except Exception as e:
        if album_id in album_download_status:
            album_download_status[album_id]["failed_tracks"] += 1
        print(f"Error downloading album track {track_id}: {e}")


def cleanup_temp_file(file_path: str) -> None:
    """Clean up temporary download file after it's been served"""
    try:
        # Wait a moment to ensure file transfer is complete
        time.sleep(2)
        if os.path.exists(file_path):
            os.remove(file_path)
            print(f"Cleaned up temp file: {file_path}")
    except Exception as e:
        print(f"Error cleaning up temp file {file_path}: {e}")
