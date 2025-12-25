from typing import List, Optional

from pydantic import BaseModel


class TrackResponse(BaseModel):
    id: str
    name: str
    artist: str
    artists: List[str]
    album: str
    duration_ms: int
    external_url: str
    preview_url: Optional[str]
    album_art: Optional[str]
    release_date: str


class DownloadStatusResponse(BaseModel):
    status: str
    message: str
    file_path: Optional[str] = None
