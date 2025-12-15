import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
from typing import List, Dict, Optional
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

class SpotifyService:
    def __init__(self):
        if not config.SPOTIFY_CLIENT_ID or not config.SPOTIFY_CLIENT_SECRET:
            raise ValueError("Spotify credentials not configured. Set SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET")
        
        client_credentials_manager = SpotifyClientCredentials(
            client_id=config.SPOTIFY_CLIENT_ID,
            client_secret=config.SPOTIFY_CLIENT_SECRET
        )
        self.client = spotipy.Spotify(client_credentials_manager=client_credentials_manager)
    
    def search_tracks(self, query: str, limit: int = 20) -> List[Dict]:
        """Search for tracks on Spotify"""
        try:
            results = self.client.search(q=query, type='track', limit=limit)
            tracks = []
            
            for item in results['tracks']['items']:
                track = {
                    'id': item['id'],
                    'name': item['name'],
                    'artists': [artist['name'] for artist in item['artists']],
                    'artist': ', '.join([artist['name'] for artist in item['artists']]),
                    'album': item['album']['name'],
                    'album_id': item['album']['id'],
                    'duration_ms': item['duration_ms'],
                    'external_url': item['external_urls']['spotify'],
                    'preview_url': item.get('preview_url'),
                    # Get the largest image (first in array, sorted by size descending)
                    'album_art': item['album']['images'][0]['url'] if item['album']['images'] else None,
                    'release_date': item['album'].get('release_date', '')
                }
                tracks.append(track)
            
            return tracks
        except Exception as e:
            print(f"Spotify search error: {e}")
            raise
    
    def get_track_details(self, track_id: str) -> Optional[Dict]:
        """Get detailed information about a specific track"""
        try:
            track = self.client.track(track_id)
            return {
                'id': track['id'],
                'name': track['name'],
                'artists': [artist['name'] for artist in track['artists']],
                'artist': ', '.join([artist['name'] for artist in track['artists']]),
                'album': track['album']['name'],
                'album_id': track['album']['id'],
                'duration_ms': track['duration_ms'],
                'external_url': track['external_urls']['spotify'],
                'preview_url': track.get('preview_url'),
                # Get the largest image (first in array, sorted by size descending)
                'album_art': track['album']['images'][0]['url'] if track['album']['images'] else None,
                'release_date': track['album'].get('release_date', '')
            }
        except Exception as e:
            print(f"Error fetching track details: {e}")
            return None

