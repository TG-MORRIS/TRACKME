# TRACKME

TRACKME is a consent-based GPS sharing and GIS tracking app. A device owner
chooses when to start sharing and which registered viewers can see their
location. Owners can stop tracking or revoke viewer access at any time.
Owners can also draw private geofences and see enter/exit alerts while sharing
their location.

## Get started

1. Follow [the setup guide](docs/SETUP.md) to configure MySQL and the API.
2. Serve the `frontend/` directory on port 5500.
3. Open `http://127.0.0.1:5500/` and choose whether to share a location or view
   a location that was shared with you.

On Linux, after completing setup, double-click `TRACKME.desktop` on your Desktop
to start both servers and open the app in your browser. Keep the terminal open
while using TRACKME; closing it stops the servers.

To deploy the frontend and API together on Render, follow the [Render setup
guide](docs/SETUP.md#deploy-on-render).

For phone GPS testing on the same Wi-Fi, use `TRACKME Phone Test.desktop`.
Open the local certificate download link printed in the terminal on each test
phone, install it, then open the printed HTTPS address. See [the setup guide](docs/SETUP.md)
for Android and iPhone certificate steps. This is local development only; it
does not publish the app to the internet.

## Test

From `backend/`, run:

```sh
python -m unittest discover -s tests -v
```

## GPS and deployment

Browser GPS requires permission and a secure context. Localhost is secure for
development; phones and public deployments require HTTPS with a trusted
certificate. See the setup guide for LAN and deployment configuration.
 
iV7dJrCbPuwJ7qNtA_ypJusNxTZCp638sE432flM84UgNBeUim1ScUksVkhHNO2u