# Deployment Guide — Kross Autoresponder

Everything runs on a single VPS. The bot (`script.py`), the database
(`notifications.db`), and the web dashboard (`web/main.py`) all live on the
same machine and share the same file — no networking between components needed.

## Recommended setup
- Provider: OVH (or any Ubuntu VPS)
- Plan: VPS-1 (4 vCores, 8 GB RAM — more than enough)
- Location: France (Gravelines) or Germany (Limburg)
- OS: **Ubuntu 22.04 LTS**

---

## 1. First login & basic security

```bash
# SSH in as root
ssh root@YOUR_VPS_IP

# Create a non-root user
adduser ubuntu
usermod -aG sudo ubuntu

# Copy your SSH key to the new user, then log in as ubuntu from now on
rsync --archive --chown=ubuntu:ubuntu ~/.ssh /home/ubuntu/
```

---

## 2. Install system dependencies

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-pip python3-venv git nginx certbot python3-certbot-nginx
```

---

## 3. Clone the repo

```bash
cd /home/ubuntu
git clone git@github.com:fedmand/kross-autoresponder.git
cd kross-autoresponder
```

---

## 4. Set up the Python environment

```bash
python3 -m venv venv
source venv/bin/activate

# Bot dependencies
pip install -r requirements.txt

# Dashboard dependencies (add fastapi uvicorn jinja2 to web/requirements.txt when ready)
pip install -r web/requirements.txt
```

---

## 5. Create the .env file (credentials — never commit this)

```bash
nano .env
```

Paste and fill in:

```
KROSS_API_KEY=...
KROSS_HOTEL_ID=...
KROSS_USERNAME=...
KROSS_PASSWORD=...
ANTHROPIC_API_KEY=...
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
```

```bash
chmod 600 .env   # only the current user can read it
```

---

## 6. Run the bot as a systemd service

Create the service file:

```bash
sudo nano /etc/systemd/system/kross-bot.service
```

Paste:

```ini
[Unit]
Description=Kross Autoresponder Bot
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/kross-autoresponder
ExecStart=/home/ubuntu/kross-autoresponder/venv/bin/python -u script.py
Restart=always
RestartSec=10
EnvironmentFile=/home/ubuntu/kross-autoresponder/.env
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

Enable and start it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable kross-bot
sudo systemctl start kross-bot

# Verify it's running
sudo systemctl status kross-bot

# Tail the live logs
sudo journalctl -u kross-bot -f
```

---

## 7. Run the dashboard as a systemd service

```bash
sudo nano /etc/systemd/system/kross-web.service
```

Paste:

```ini
[Unit]
Description=Kross Host Dashboard (FastAPI)
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/kross-autoresponder
ExecStart=/home/ubuntu/kross-autoresponder/venv/bin/uvicorn web.main:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable kross-web
sudo systemctl start kross-web
```

Note: FastAPI listens on 127.0.0.1 (localhost only). Nginx in the next step
handles the public HTTPS connection and forwards it to FastAPI.

---

## 8. Configure Nginx as a reverse proxy

```bash
sudo nano /etc/nginx/sites-available/kross
```

Paste (replace `yourdomain.com` with your actual domain or VPS IP):

```nginx
server {
    listen 80;
    server_name yourdomain.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/kross /etc/nginx/sites-enabled/
sudo nginx -t          # check config is valid
sudo systemctl reload nginx
```

---

## 9. Add HTTPS with Let's Encrypt (mandatory before real guest data)

You need a domain pointing at the VPS IP first (set an A record with your
domain registrar). Then:

```bash
sudo certbot --nginx -d yourdomain.com
```

Certbot will automatically update the Nginx config and set up auto-renewal.
Test renewal with:

```bash
sudo certbot renew --dry-run
```

---

## 10. Add a login (mandatory before exposing to the internet)

The simplest option: HTTP Basic Auth via Nginx.

```bash
sudo apt install -y apache2-utils
sudo htpasswd -c /etc/nginx/.htpasswd matteo
sudo htpasswd /etc/nginx/.htpasswd nicolo
```

Add to the Nginx server block (inside `location /`):

```nginx
auth_basic "Kross Dashboard";
auth_basic_user_file /etc/nginx/.htpasswd;
```

Then reload Nginx:

```bash
sudo systemctl reload nginx
```

---

## Useful commands after deployment

```bash
# Check bot status / logs
sudo systemctl status kross-bot
sudo journalctl -u kross-bot -f

# Check dashboard status / logs
sudo systemctl status kross-web
sudo journalctl -u kross-web -f

# Restart after a code update
cd /home/ubuntu/kross-autoresponder && git pull
sudo systemctl restart kross-bot
sudo systemctl restart kross-web

# Inspect the database
sqlite3 notifications.db "SELECT id, home, guest_name, status, created_at FROM notifications ORDER BY created_at DESC LIMIT 20;"
```

---

## Decommission Streamlit Cloud

Once the VPS is live and verified, go to share.streamlit.io and delete the
deployed app. The `gui/` folder and Streamlit code can stay in the repo for
reference but are no longer the active frontend.
