# Deploying Admart (staging)

After the one-time setup below, every push to `staging` deploys itself:

- **Backend** (`.github/workflows/deploy-staging.yml`): runs the tests on PostgreSQL, then SSHes in and runs `deploy/deploy.sh` (pull, install, migrate, collectstatic, restart, health check).
- **Frontend** (`Admart-frontend/.github/workflows/deploy-staging.yml`): builds with the staging `VITE_*` values and rsyncs `dist/` to the server.

Layout on the server: `/srv/admart/backend` (git checkout), `/srv/admart/frontend` (built files). Needs Ubuntu 24.04+ (Python 3.12, required by Django 6).

## 1. Packages, user, database (as root)

```bash
apt update && apt install -y python3.12-venv git nginx certbot python3-certbot-nginx postgresql rsync curl
adduser --disabled-password --gecos "" deploy
usermod -aG www-data deploy
mkdir -p /srv/admart/frontend && chown -R deploy:www-data /srv/admart && chmod 750 /srv/admart

sudo -u postgres createuser admart
sudo -u postgres createdb -O admart admart
sudo -u postgres psql -c "ALTER USER admart PASSWORD '<strong random password>'"

# Let the deploy script restart only this service, without a password:
echo 'deploy ALL=NOPASSWD: /usr/bin/systemctl restart admart-backend, /usr/bin/systemctl status admart-backend *' > /etc/sudoers.d/admart
```

## 2. Code and `.env` (as deploy)

The server pulls from GitHub, so give it a **read-only deploy key**: `ssh-keygen -t ed25519`, then add `~/.ssh/id_ed25519.pub` to the backend repo under Settings → Deploy keys.

```bash
git clone -b staging git@github.com:CodeWithEhtisham/admart-backend.git /srv/admart/backend
cd /srv/admart/backend && python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env && chmod 600 .env && nano .env
```

Fill `.env` from `.env.example`. Production essentials:

```
DEBUG=False
SECRET_KEY=<python -c "import secrets; print(secrets.token_urlsafe(50))">
SOCIAL_TOKEN_ENCRYPTION_KEY=<python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())">
ALLOWED_HOSTS=api-staging.example.com
CSRF_TRUSTED_ORIGINS=https://api-staging.example.com
CORS_ORIGINS=https://staging.example.com
FRONTEND_URL=https://staging.example.com
MEDIA_BASE_URL=https://api-staging.example.com
POSTGRES_DB=admart
POSTGRES_USER=admart
POSTGRES_PASSWORD=<the password from step 1>
EMAIL_HOST=…  EMAIL_HOST_USER=…  EMAIL_HOST_PASSWORD=…  DEFAULT_FROM_EMAIL=…
FAL_KEY=…  GEMINI_API_KEY=…  plus each platform's client id/secret and *_OAUTH_REDIRECT_URI
```

Back up `SECRET_KEY` and `SOCIAL_TOKEN_ENCRYPTION_KEY` somewhere safe. Losing the encryption key disconnects every customer's social accounts.

```bash
.venv/bin/python manage.py migrate && .venv/bin/python manage.py collectstatic --noinput
.venv/bin/python manage.py createsuperuser
```

## 3. Service, nginx, HTTPS (as root)

```bash
cp /srv/admart/backend/deploy/admart-backend.service /etc/systemd/system/
systemctl daemon-reload && systemctl enable --now admart-backend

cp /srv/admart/backend/deploy/nginx-admart.conf /etc/nginx/sites-available/admart
sed -i 's/api-staging\.example\.com/<your api domain>/g; s/staging\.example\.com/<your app domain>/g' /etc/nginx/sites-available/admart
ln -s /etc/nginx/sites-available/admart /etc/nginx/sites-enabled/ && rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx
certbot --nginx -d <your app domain> -d <your api domain>
```

Point both domains' DNS A records at the server first. nginx serves `/media/` and `/static/` but **never** `private_media/` (payment proofs).

## 4. GitHub (both repos → Settings → Environments → `staging`)

| Kind | Name | Value |
|---|---|---|
| Secret | `SSH_HOST` | server IP or hostname |
| Secret | `SSH_USER` | `deploy` |
| Secret | `SSH_KEY` | private key of a CI-only keypair; its `.pub` goes in `~deploy/.ssh/authorized_keys` |
| Secret | `SSH_KNOWN_HOSTS` | output of `ssh-keyscan <server>`, run once from a trusted machine |
| Variable (frontend) | `VITE_API_URL` | `https://<your api domain>` |
| Variable (frontend) | `VITE_GOOGLE_CLIENT_ID` | Google OAuth web client id (public) |
| Variable (frontend) | `VITE_GOOGLE_REDIRECT_URI` | `https://<your app domain>/auth-callback` |

Platform keys (fal, Google secret, Meta, TikTok…) live **only** in the server's `.env`. Never put them in GitHub.

## 5. Nightly backups (as root)

`deploy/backup.sh` dumps PostgreSQL and archives `media/` + `private_media/` into `/var/backups/admart/<timestamp>/`, owner-only, with checksums, and keeps 14 days.

```bash
install -d -o deploy -g deploy -m 700 /var/backups/admart
cp /srv/admart/backend/deploy/admart-backup.service /srv/admart/backend/deploy/admart-backup.timer /etc/systemd/system/
systemctl daemon-reload && systemctl enable --now admart-backup.timer
systemctl start admart-backup.service && ls /var/backups/admart   # run one now to check
```

Backups on the same server are lost with the server, so also copy them offsite. Install `rclone`, configure a remote as the deploy user (`rclone config`, e.g. Backblaze B2 or S3, ideally with rclone's `crypt` encryption), then add to the service with `systemctl edit admart-backup.service`:

```
[Service]
Environment=BACKUP_REMOTE=<remote>:admart-backups/staging
```

`.env` is not in the backups. Keep a copy in your password manager: without `SOCIAL_TOKEN_ENCRYPTION_KEY`, restored social tokens can't be decrypted.

**Restore** (tested: data and files come back identical):

```bash
systemctl stop admart-backend
sudo -u postgres psql -c "DROP DATABASE admart WITH (FORCE)" -c "CREATE DATABASE admart OWNER admart"
PGPASSWORD=<db password> pg_restore --no-owner -h localhost -U admart -d admart /var/backups/admart/<stamp>/db.dump
tar -xzf /var/backups/admart/<stamp>/files.tar.gz -C /srv/admart/backend
systemctl start admart-backend
```

Practise a restore once on a spare machine before you need it.

## Rollback

Revert the bad commit on `staging` (`git revert <sha>`) and push; CI tests and redeploys it. Don't check out an old commit on the server by hand: the next deploy resets to `staging` anyway. Migrations are not undone automatically, so check before reverting one.
