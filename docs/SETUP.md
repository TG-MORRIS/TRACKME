# TRACKME setup

TRACKME shares GPS coordinates only after the device owner signs in, grants a
viewer access, and explicitly starts tracking. The owner can revoke access or
stop tracking at any time.

## Requirements

- MySQL with spatial data support
- Python 3.10 or newer
- A modern browser

## Database

For a fresh installation, create the database and tables:

```sh
mysql -u root -p < database/schema.sql
```

Create an application user (not `root`) with a password of your choice:

Connect to MySQL with an administrator account:

```sh
mysql -u root -p
```

Then grant the application account access:

```sql
CREATE USER 'trackme_user'@'127.0.0.1' IDENTIFIED BY 'REPLACE_WITH_A_PASSWORD';
GRANT ALL PRIVILEGES ON trackme_db.* TO 'trackme_user'@'127.0.0.1';
```

If the database already exists, apply the missing geofence-alert table:

```sh
mysql -u YOUR_MYSQL_USER -p < database/migrations/001_geofence_alerts.sql
```

## Backend

From the project root, copy `backend/.env.example` to `backend/.env`, then set
the MySQL username, password, and a unique random signing key:

```sh
cd backend
cp .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Use a dedicated MySQL account with access only to `trackme_db`; do not run the
application using the MySQL root account. Keep `.env` private and never commit
it.

Install dependencies and run the API from the `backend` directory:

```sh
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

The API listens on port `8000`; interactive API documentation is available at
`/docs`.

## Tests

Run the backend unit tests from `backend/`:

```sh
python -m unittest discover -s tests -v
```

## Frontend

Serve `frontend/` over HTTP on port 5500 (for example with the VS Code Live
Server extension). Open the landing page at `/` to choose owner or viewer
workflow. The API address follows the hostname used to open the page;
you can override it by setting `window.TRACKME_API_BASE` before loading either
frontend script. For phone testing or public deployment, serve both the frontend and API using
HTTPS with a trusted certificate. Configure `FRONTEND_ORIGINS` with the exact
frontend origin and set `window.TRACKME_API_BASE` to the HTTPS API URL before
loading the frontend scripts. A plain HTTP LAN address does not enable GPS on
most phones. Do not expose MySQL to the public internet.

Open `tracking.html` to create accounts and manage GPS sharing. Each owner
can draw and manage their own geofences, and grants access by the viewer's
registered email. Geofences are private to their creator and only apply to
that owner's tracking sessions. The viewer then signs into `dashboard.html` to
see locations, movement history, and geofence alerts shared with them.

Browser geolocation requires the device owner's permission and a secure browser
context. Localhost is treated as secure by browsers; deployments must use HTTPS.

## Test on a phone without public hosting

The PC and phone must be connected to the same Wi-Fi. On Linux, launch
`TRACKME Phone Test.desktop` from the Desktop folder, or run
`./run_trackme_phone.sh` from the project directory. The launcher binds to the
PC's current LAN address, starts HTTPS for both the frontend and API, and prints
the phone URL and a local link for downloading the CA certificate. This keeps
the app on your local network; it does not publish it to the internet.

On each phone, first open the printed
`http://<PC-LAN-IP>:5501/trackme-root-ca.crt` link and install the downloaded
file as a trusted CA certificate. This temporary local HTTP server exposes only
the public certificate. Keep the matching `trackme-root-ca.key` on the PC and
do not copy or share it.

- **Android:** In Settings, search for “Install a certificate” or “CA
  certificate,” then select the `.crt` file. The menu names vary by Android
  version. Open the printed `https://<PC-LAN-IP>:5500/` URL in Chrome.
- **iPhone:** Open the downloaded `.crt` file to install its profile. Then go to
  **Settings → General → About → Certificate Trust
  Settings** and enable full trust for the TRACKME local test CA. Open the
  printed URL in Safari.

Allow the browser to access location when prompted. If the phone cannot load
the page, confirm both devices are on the same Wi-Fi and that the PC firewall
allows local connections on ports 5500, 5501, and 8000. Internet access may
still be needed for the external map tiles.
