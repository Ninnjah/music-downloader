from typing import Dict, Optional

from pydantic import BaseModel


class SearchRequest(BaseModel):
    query: str
    limit: int = 20


class DownloadRequest(BaseModel):
    track_id: str
    location: Optional[str] = "local"  # 'local' or 'navidrome'
    video_id: Optional[str] = (
        None  # YouTube video ID if user selected a specific candidate
    )


class AlbumDownloadRequest(BaseModel):
    album_id: str
    location: Optional[str] = "local"  # 'local' or 'navidrome'


class ReverseLookupRequest(BaseModel):
    url: str


class ReverseDownloadRequest(BaseModel):
    youtube_url: str
    location: Optional[str] = "local"  # 'local' or 'navidrome'
    spotify_track_id: Optional[str] = None
    metadata: Optional[Dict] = None
