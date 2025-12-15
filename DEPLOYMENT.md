# Deployment Guide for Navidrome Server

This guide will help you deploy the Music Downloader to the same server that hosts Navidrome.

## Pre-Deployment Checklist

✅ **Code is ready!** The application now properly:
- Downloads directly to Navidrome's music directory when "navidrome" location is selected
- Organizes files in Artist/Album/ structure
- Triggers Navidrome library scans after adding files
- Cleans up temporary files

## Server Setup Steps

### 1. Transfer Files to Server

Copy the entire project directory to your Navidrome server:

```bash
# On your local machine
scp -r /home/andrej/projects/web/fullstack/musicDownloader user@your-server:/path/to/deployment/
```

Or use git:
```bash
# On server
git clone <your-repo-url> /path/to/musicDownloader
```

### 2. Install Dependencies on Server

```bash
# SSH into your server
ssh user@your-server

# Install system dependencies
sudo apt update
sudo apt install python3 python3-pip python3-venv ffmpeg -y

# Navigate to project
cd /path/to/musicDownloader/backend

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install Python dependencies
pip install -r requirements.txt
```

### 3. Configure Environment Variables

```bash
# Copy example env file
cp env.example .env

# Edit with your actual values
nano .env
```

**Important configuration values:**

```env
# Spotify API (required)
SPOTIFY_CLIENT_ID=your_actual_client_id
SPOTIFY_CLIENT_SECRET=your_actual_client_secret
SPOTIFY_REDIRECT_URI=https://your-domain.com/callback  # Or http://your-server-ip:8000/callback

# Navidrome Configuration (CRITICAL for production)
# This MUST be the actual path to Navidrome's music library
NAVIDROME_MUSIC_PATH=/path/to/navidrome/music  # e.g., /var/navidrome/music or /music

# Navidrome API (optional but recommended - triggers automatic library scans)
NAVIDROME_API_URL=http://localhost:4533  # Or https://your-navidrome-domain.com
NAVIDROME_USERNAME=admin  # Your Navidrome admin username
NAVIDROME_PASSWORD=your_admin_password  # Your Navidrome admin password

# Download Configuration
OUTPUT_FORMAT=mp3
AUDIO_QUALITY=128

# API Configuration
API_HOST=0.0.0.0  # Listen on all interfaces
API_PORT=8000  # Or another port if 8000 is taken
CORS_ORIGINS=http://localhost:8000,https://your-domain.com  # Add your actual domain(s)

# Download directory (used for temp files only - will be cleaned up)
DOWNLOAD_DIR=./downloads
```

### 4. Verify File Permissions

The user running the application must have write access to Navidrome's music directory:

```bash
# Check current permissions
ls -la /path/to/navidrome/music

# If needed, grant write permissions (adjust user/group as needed)
sudo chown -R $USER:navidrome /path/to/navidrome/music
sudo chmod -R 775 /path/to/navidrome/music
```

### 5. Test the Application

```bash
# Activate virtual environment
cd /path/to/musicDownloader/backend
source venv/bin/activate

# Test run
uvicorn app:app --host 0.0.0.0 --port 8000
```

Open `http://your-server-ip:8000` in a browser and test:
1. Search for a song
2. Select "Navidrome Server (Test)" option
3. Download a track
4. Verify it appears in Navidrome (may need to manually trigger a scan if API isn't configured)

### 6. Set Up as a System Service (Recommended)

Create a systemd service for automatic startup:

```bash
sudo nano /etc/systemd/system/music-downloader.service
```

Add:

```ini
[Unit]
Description=Music Downloader Service
After=network.target

[Service]
Type=simple
User=your-username
WorkingDirectory=/path/to/musicDownloader/backend
Environment="PATH=/path/to/musicDownloader/backend/venv/bin"
ExecStart=/path/to/musicDownloader/backend/venv/bin/uvicorn app:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable music-downloader
sudo systemctl start music-downloader
sudo systemctl status music-downloader
```

### 7. Set Up Reverse Proxy (Optional but Recommended)

If you want to use HTTPS and a domain name, set up nginx:

```bash
sudo nano /etc/nginx/sites-available/music-downloader
```

Add:

```nginx
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Enable and restart:

```bash
sudo ln -s /etc/nginx/sites-available/music-downloader /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

Then set up SSL with Let's Encrypt:

```bash
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d your-domain.com
```

### 8. Update Frontend Download Location Label

After confirming everything works, you can update the frontend label from "Navidrome Server (Test)" to "Navidrome Server":

```bash
nano frontend/index.html
```

Change:
```html
<option value="navidrome">Navidrome Server (Test)</option>
```

To:
```html
<option value="navidrome">Navidrome Server</option>
```

## Troubleshooting

### Files not appearing in Navidrome
- Check that `NAVIDROME_MUSIC_PATH` is correct
- Verify file permissions on the music directory
- Manually trigger a scan in Navidrome settings, or check if API credentials are correct

### Permission Denied Errors
- Ensure the user running the service has write access to Navidrome's music directory
- Check SELinux/AppArmor policies if applicable

### Port Already in Use
- Change `API_PORT` in `.env` to a different port (e.g., 8001)
- Update firewall rules if needed

### Spotify API Errors
- Verify credentials are correct in `.env`
- Check if your Spotify app has proper redirect URIs configured

## Security Considerations

1. **Firewall**: Only expose port 8000 if needed, or use a reverse proxy with authentication
2. **Authentication**: Consider adding authentication to the web interface if it will be publicly accessible
3. **Rate Limiting**: Consider adding rate limiting to prevent abuse
4. **File Cleanup**: Temp files are automatically cleaned up, but monitor disk space

## Maintenance

- Monitor logs: `sudo journalctl -u music-downloader -f`
- Check disk space in Navidrome music directory
- Keep dependencies updated: `pip install -r requirements.txt --upgrade`

