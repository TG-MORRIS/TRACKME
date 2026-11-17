
/* =========================================
   TRACKME MOBILE TRACKING APPLICATION
========================================= */

// Backend address
const API_BASE = window.TRACKME_API_BASE ||
    `${window.location.protocol}//${window.location.hostname}:8000`;

// Authentication
let accessToken = null;
let currentUser = null;

// Tracking
let trackingSessionId = null;
let watchId = null;
let trackingActive = false;
let geofenceMap = null;
let geofenceDrawing = false;
let geofenceVertices = [];
let geofenceDraftLayer = null;
let savedGeofenceLayers = new Map();

let lastSentAt = 0;
let pointsCount = 0;
let locationUploadInProgress = false;

const UPDATE_INTERVAL = 10000; // 10 seconds
const savedToken = sessionStorage.getItem("trackme_token");

if (savedToken) {
    accessToken = savedToken;
}


// =========================================
// DOM ELEMENTS
// =========================================

const authSection = document.getElementById("auth-section");
const trackingSection = document.getElementById("tracking-section");

const loginForm = document.getElementById("login-form");
const registerForm = document.getElementById("register-form");

const loginTab = document.getElementById("login-tab");
const registerTab = document.getElementById("register-tab");


// =========================================
// API REQUEST FUNCTION
// =========================================

async function apiRequest(endpoint, method = "GET", data = null) {

    const headers = {};

    if (data !== null) {
        headers["Content-Type"] = "application/json";
    }

    if (accessToken) {
        headers["Authorization"] = `Bearer ${accessToken}`;
    }

    const response = await fetch(`${API_BASE}${endpoint}`, {
        method,
        headers,
        body: data !== null ? JSON.stringify(data) : undefined
    });

    const result = await response.json().catch(() => ({}));
    if (!response.ok) {
        const detail = result.detail;
        const message = Array.isArray(detail)
            ? detail.map(issue => {
                const field = issue.loc?.at(-1);
                return field ? `${field}: ${issue.msg}` : issue.msg;
            }).join(". ")
            : typeof detail === "string"
                ? detail
                : `Request failed: ${response.status}`;
        throw new Error(
            message || `Request failed: ${response.status}`
        );
    }

    return result;
}


// =========================================
// MESSAGE DISPLAY
// =========================================

function showMessage(elementId, message, type = "") {

    const element = document.getElementById(elementId);

    element.textContent = message;
    element.className = "message";

    if (type) {
        element.classList.add(type);
    }
}


// =========================================
// AUTHENTICATION TABS
// =========================================

loginTab.addEventListener("click", () => {

    loginForm.classList.remove("hidden");
    registerForm.classList.add("hidden");

    loginTab.classList.add("active");
    registerTab.classList.remove("active");

    showMessage("auth-message", "");
});


registerTab.addEventListener("click", () => {

    registerForm.classList.remove("hidden");
    loginForm.classList.add("hidden");

    registerTab.classList.add("active");
    loginTab.classList.remove("active");

    showMessage("auth-message", "");
});


// =========================================
// USER REGISTRATION
// =========================================

registerForm.addEventListener("submit", async (event) => {

    event.preventDefault();

    const full_name =
        document.getElementById("register-name").value.trim();

    const email =
        document.getElementById("register-email").value.trim();

    const password =
        document.getElementById("register-password").value;

    try {

        showMessage("auth-message", "Creating your account...");

        const result = await apiRequest(
            "/auth/register",
            "POST",
            {
                full_name,
                email,
                password
            }
        );

        showMessage(
            "auth-message",
            "Account created successfully! Please login.",
            "success"
        );

        registerForm.reset();

        loginTab.click();

        document.getElementById("login-email").value = email;

    } catch (error) {

        showMessage(
            "auth-message",
            error.message,
            "error"
        );

    }

});


// =========================================
// USER LOGIN
// =========================================

loginForm.addEventListener("submit", async (event) => {

    event.preventDefault();

    const email =
        document.getElementById("login-email").value.trim();

    const password =
        document.getElementById("login-password").value;

    try {

        showMessage("auth-message", "Signing in...");

        const result = await apiRequest(
            "/auth/login",
            "POST",
            {
                email,
                password
            }
        );

        accessToken = result.access_token;
        currentUser = result.user;
        sessionStorage.setItem("trackme_token", accessToken);

        await openTrackingInterface();

    } catch (error) {

        accessToken = null;
        currentUser = null;
        sessionStorage.removeItem("trackme_token");
        showMessage(
            "auth-message",
            error.message,
            "error"
        );

    }

});


// =========================================
// OPEN TRACKING INTERFACE
// =========================================

async function openTrackingInterface() {
    document.getElementById("user-name").textContent =
        currentUser.full_name;

    document.getElementById("user-email").textContent =
        currentUser.email;

    await loadSharingPermissions();

    const session = await apiRequest("/tracking/current");

    authSection.classList.add("hidden");
    trackingSection.classList.remove("hidden");

    initializeGeofenceMap();
    await loadGeofences();

    if (session.session_id !== null) {
        trackingSessionId = session.session_id;
        document.getElementById("session-id").textContent =
            trackingSessionId;
        pointsCount = session.points_count || 0;
        document.getElementById("points-count").textContent = pointsCount;
        document.getElementById("status-indicator").classList.add("active");
        document.getElementById("tracking-status").textContent =
            "Tracking session active";
        document.getElementById("status-description").textContent =
            "GPS updates are paused on this page. Resume tracking or stop the session.";
        document.getElementById("start-btn").textContent =
            "▶ Resume Tracking";
        document.getElementById("start-btn").disabled = false;
        document.getElementById("stop-btn").disabled = false;
        showMessage(
            "tracking-message",
            "An active session was found. Resume to share new GPS updates or stop it."
        );
        if (session.latest_location) {
            const location = session.latest_location;
            document.getElementById("latitude").textContent =
                Number(location.latitude).toFixed(6);
            document.getElementById("longitude").textContent =
                Number(location.longitude).toFixed(6);
            document.getElementById("accuracy").textContent =
                location.accuracy === null
                    ? "Unavailable"
                    : `${Math.round(location.accuracy)} metres`;
            document.getElementById("speed").textContent =
                location.speed === null
                    ? "Unavailable"
                    : `${Number(location.speed).toFixed(2)} m/s`;
            document.getElementById("last-update").textContent =
                new Date(location.recorded_at).toLocaleString();
        }
    }

}


function initializeGeofenceMap() {
    if (geofenceMap) {
        geofenceMap.invalidateSize();
        return;
    }

    geofenceMap = L.map("geofence-map").setView([-0.607, 30.654], 13);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        attribution: "&copy; OpenStreetMap contributors",
        maxZoom: 19
    }).addTo(geofenceMap);

    geofenceMap.on("click", event => {
        if (!geofenceDrawing) {
            return;
        }

        geofenceVertices.push({
            latitude: event.latlng.lat,
            longitude: event.latlng.lng
        });
        renderGeofenceDraft();
        document.getElementById("undo-geofence-point-btn").disabled = false;
        showMessage(
            "geofence-message",
            `${geofenceVertices.length} point(s) added. Add at least three, then finish the outline.`
        );
    });

    setTimeout(() => geofenceMap.invalidateSize(), 200);
}


function renderGeofenceDraft() {
    if (geofenceDraftLayer) {
        geofenceMap.removeLayer(geofenceDraftLayer);
    }

    const points = geofenceVertices.map(vertex => [
        vertex.latitude,
        vertex.longitude
    ]);
    geofenceDraftLayer = L.featureGroup();

    for (const point of points) {
        L.circleMarker(point, {
            radius: 5,
            color: "#12345a",
            fillColor: "#38bdf8",
            fillOpacity: 1
        }).addTo(geofenceDraftLayer);
    }

    if (points.length >= 3) {
        L.polygon(points, {
            color: "#2563eb",
            fillColor: "#3b82f6",
            fillOpacity: 0.2
        }).addTo(geofenceDraftLayer);
    } else if (points.length === 2) {
        L.polyline(points, { color: "#2563eb" }).addTo(geofenceDraftLayer);
    }

    geofenceDraftLayer.addTo(geofenceMap);
}


function clearGeofenceDraft() {
    geofenceDrawing = false;
    geofenceVertices = [];
    if (geofenceDraftLayer && geofenceMap) {
        geofenceMap.removeLayer(geofenceDraftLayer);
        geofenceDraftLayer = null;
    }

    document.getElementById("draw-geofence-btn").textContent =
        "Start drawing";
    document.getElementById("undo-geofence-point-btn").disabled = true;
    document.getElementById("clear-geofence-draft-btn").disabled = true;
    document.getElementById("save-geofence-btn").disabled = true;
    document.getElementById("geofence-draw-help").textContent =
        "Start drawing, then tap at least three points on the map. Finish the outline to save it.";
    geofenceMap?.doubleClickZoom.enable();
}


document.getElementById("draw-geofence-btn").addEventListener("click", () => {
    if (!geofenceDrawing) {
        clearGeofenceDraft();
        geofenceDrawing = true;
        geofenceMap.doubleClickZoom.disable();
        document.getElementById("draw-geofence-btn").textContent =
            "Finish outline";
        document.getElementById("clear-geofence-draft-btn").disabled = false;
        document.getElementById("geofence-draw-help").textContent =
            "Tap at least three points around the area. Tap Finish outline when done.";
        showMessage("geofence-message", "Tap the map to add boundary points.");
        return;
    }

    if (geofenceVertices.length < 3) {
        showMessage(
            "geofence-message",
            "Add at least three boundary points before finishing.",
            "error"
        );
        return;
    }

    geofenceDrawing = false;
    geofenceMap.doubleClickZoom.enable();
    document.getElementById("draw-geofence-btn").textContent =
        "Start new outline";
    document.getElementById("undo-geofence-point-btn").disabled = false;
    document.getElementById("save-geofence-btn").disabled = false;
    document.getElementById("geofence-draw-help").textContent =
        `${geofenceVertices.length} boundary points ready. Save the named zone or clear to redraw.`;
    showMessage("geofence-message", "Outline complete. Enter a name and save.");
});


document.getElementById("undo-geofence-point-btn").addEventListener("click", () => {
    if (geofenceVertices.length === 0) {
        return;
    }

    geofenceVertices.pop();
    renderGeofenceDraft();
    document.getElementById("undo-geofence-point-btn").disabled =
        geofenceVertices.length === 0;
    document.getElementById("save-geofence-btn").disabled =
        geofenceDrawing || geofenceVertices.length < 3;
    showMessage(
        "geofence-message",
        `${geofenceVertices.length} point(s) remain.`
    );
});


document.getElementById("clear-geofence-draft-btn").addEventListener(
    "click",
    () => {
        clearGeofenceDraft();
        showMessage("geofence-message", "Draft cleared.");
    }
);


function parseGeofenceBoundary(boundary) {
    const match = boundary?.match(/^POLYGON\s*\(\((.+)\)\)$/i);
    if (!match) {
        throw new Error("The server returned an invalid geofence boundary.");
    }

    return match[1].split(",").map(pair => {
        const [longitude, latitude] = pair.trim().split(/\s+/).map(Number);
        if (!Number.isFinite(latitude) || !Number.isFinite(longitude)) {
            throw new Error("The server returned invalid geofence coordinates.");
        }
        return [latitude, longitude];
    });
}


async function loadGeofences() {
    const list = document.getElementById("geofence-list");
    list.replaceChildren();

    for (const layer of savedGeofenceLayers.values()) {
        geofenceMap.removeLayer(layer);
    }
    savedGeofenceLayers.clear();

    try {
        const result = await apiRequest("/geofences");
        const geofences = result.geofences || [];

        if (geofences.length === 0) {
            list.textContent = "No geofences saved yet.";
            return;
        }

        for (const geofence of geofences) {
            const coordinates = parseGeofenceBoundary(geofence.boundary);
            const polygon = L.polygon(coordinates, {
                color: "#16a34a",
                fillColor: "#22c55e",
                fillOpacity: 0.18
            }).addTo(geofenceMap);
            const popup = document.createElement("strong");
            popup.textContent = geofence.name;
            polygon.bindPopup(popup);
            savedGeofenceLayers.set(geofence.geofence_id, polygon);

            const item = document.createElement("div");
            item.className = "geofence-item";
            const nameButton = document.createElement("button");
            nameButton.type = "button";
            nameButton.className = "geofence-name-btn";
            nameButton.textContent = geofence.name;
            nameButton.addEventListener("click", () => {
                geofenceMap.fitBounds(polygon.getBounds(), {
                    padding: [24, 24]
                });
                polygon.openPopup();
            });

            const deleteButton = document.createElement("button");
            deleteButton.type = "button";
            deleteButton.className = "revoke-btn";
            deleteButton.textContent = "Delete";
            deleteButton.addEventListener("click", async () => {
                deleteButton.disabled = true;
                try {
                    await apiRequest(
                        `/geofences/${geofence.geofence_id}`,
                        "DELETE"
                    );
                    showMessage("geofence-message", "Geofence deleted.", "success");
                    await loadGeofences();
                } catch (error) {
                    showMessage("geofence-message", error.message, "error");
                    deleteButton.disabled = false;
                }
            });

            item.append(nameButton, deleteButton);
            list.appendChild(item);
        }
    } catch (error) {
        list.textContent = "Could not load geofences.";
        showMessage("geofence-message", error.message, "error");
    }
}


document.getElementById("geofence-form").addEventListener(
    "submit",
    async event => {
        event.preventDefault();
        if (geofenceDrawing || geofenceVertices.length < 3) {
            showMessage(
                "geofence-message",
                "Draw and finish a boundary with at least three points.",
                "error"
            );
            return;
        }

        const saveButton = document.getElementById("save-geofence-btn");
        saveButton.disabled = true;
        try {
            await apiRequest("/geofences", "POST", {
                name: document.getElementById("geofence-name").value.trim(),
                vertices: geofenceVertices
            });
            document.getElementById("geofence-form").reset();
            clearGeofenceDraft();
            showMessage(
                "geofence-message",
                "Geofence saved. Enter and exit alerts will be recorded during tracking.",
                "success"
            );
            await loadGeofences();
        } catch (error) {
            showMessage("geofence-message", error.message, "error");
            saveButton.disabled = false;
        }
    }
);


async function loadSharingPermissions() {
    const list = document.getElementById("shared-users");
    list.replaceChildren();

    try {
        const result = await apiRequest("/sharing/granted-users");
        const users = result.users || [];

        if (users.length === 0) {
            list.textContent = "You have not shared your location with anyone.";
            return;
        }

        for (const user of users) {
            const item = document.createElement("div");
            item.className = "shared-user";

            const details = document.createElement("p");
            details.textContent = `${user.full_name} (${user.email})`;

            const revokeButton = document.createElement("button");
            revokeButton.type = "button";
            revokeButton.className = "revoke-btn";
            revokeButton.textContent = "Revoke";
            revokeButton.addEventListener("click", async () => {
                revokeButton.disabled = true;
                try {
                    await apiRequest(`/sharing/${user.user_id}`, "DELETE");
                    showMessage("share-message", "Location access revoked.", "success");
                    await loadSharingPermissions();
                } catch (error) {
                    showMessage("share-message", error.message, "error");
                    revokeButton.disabled = false;
                }
            });

            item.append(details, revokeButton);
            list.appendChild(item);
        }
    } catch (error) {
        list.textContent = "Could not load sharing permissions.";
        showMessage("share-message", error.message, "error");
    }
}


document.getElementById("share-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const emailInput = document.getElementById("share-email");

    try {
        await apiRequest("/sharing/grant", "POST", {
            viewer_email: emailInput.value.trim()
        });
        emailInput.value = "";
        showMessage("share-message", "Location access granted.", "success");
        await loadSharingPermissions();
    } catch (error) {
        showMessage("share-message", error.message, "error");
    }
});


// =========================================
// TRACKING STATUS
// =========================================

function updateTrackingStatus(active) {

    const indicator =
        document.getElementById("status-indicator");

    const status =
        document.getElementById("tracking-status");

    const description =
        document.getElementById("status-description");

    indicator.classList.toggle("active", active);

    status.textContent = active
        ? "Tracking active"
        : "Tracking inactive";

    description.textContent = active
        ? "Your location is being shared with authorized viewers."
        : "Location sharing is currently stopped.";

    document.getElementById("start-btn").disabled = active;
    document.getElementById("stop-btn").disabled = !active;

}


// =========================================
// DISPLAY GPS COORDINATES
// =========================================

function displayCoordinates(position) {

    const coords = position.coords;

    document.getElementById("latitude").textContent =
        coords.latitude.toFixed(6);

    document.getElementById("longitude").textContent =
        coords.longitude.toFixed(6);

    document.getElementById("accuracy").textContent =
        `${Math.round(coords.accuracy)} metres`;

    document.getElementById("speed").textContent =
        coords.speed !== null
            ? `${coords.speed.toFixed(2)} m/s`
            : "Unavailable";

}


// =========================================
// SEND GPS DATA TO BACKEND
// =========================================

async function sendLocation(position) {

    if (!trackingActive || trackingSessionId === null) {
        return;
    }

    const now = Date.now();

    // Send updates at intervals of 10 seconds
    if (locationUploadInProgress || now - lastSentAt < UPDATE_INTERVAL) {
        return;
    }

    const coords = position.coords;

    const locationData = {

        session_id: trackingSessionId,

        latitude: coords.latitude,

        longitude: coords.longitude,

        accuracy: coords.accuracy,

        speed: coords.speed

    };

    locationUploadInProgress = true;
    try {

        await apiRequest(
            "/locations",
            "POST",
            locationData
        );

        lastSentAt = now;

        pointsCount++;

        document.getElementById("points-count").textContent =
            pointsCount;

        document.getElementById("last-update").textContent =
            new Date().toLocaleTimeString();

        showMessage(
            "tracking-message",
            "Location successfully synchronized.",
            "success"
        );

    } catch (error) {

        showMessage(
            "tracking-message",
            "Location upload failed: " + error.message,
            "error"
        );

    }
    finally {
        locationUploadInProgress = false;
    }

}


// =========================================
// GPS SUCCESS CALLBACK
// =========================================

function onLocationSuccess(position) {

    displayCoordinates(position);

    sendLocation(position);

}


// =========================================
// GPS ERROR CALLBACK
// =========================================

function onLocationError(error) {

    let message = "Unable to obtain location.";

    switch (error.code) {

        case error.PERMISSION_DENIED:
            message = "Location permission was denied.";
            break;

        case error.POSITION_UNAVAILABLE:
            message = "GPS position is unavailable.";
            break;

        case error.TIMEOUT:
            message = "GPS request timed out.";
            break;

    }

    showMessage(
        "tracking-message",
        message,
        "error"
    );

}


// =========================================
// START TRACKING
// =========================================

document.getElementById("start-btn").addEventListener(
    "click",
    async () => {

        if (!navigator.geolocation) {

            showMessage(
                "tracking-message",
                "Your browser does not support GPS location.",
                "error"
            );

            return;
        }

        try {

            showMessage(
                "tracking-message",
                "Waiting for your device location permission..."
            );

            const initialPosition = await new Promise((resolve, reject) => {
                navigator.geolocation.getCurrentPosition(
                    resolve,
                    reject,
                    {
                        enableHighAccuracy: true,
                        maximumAge: 0,
                        timeout: 20000
                    }
                );
            });

            const result = await apiRequest(
                "/tracking/start",
                "POST"
            );

            const isResumingSession =
                trackingSessionId === result.session_id;
            trackingSessionId = result.session_id;

            trackingActive = true;

            lastSentAt = 0;
            if (!isResumingSession) {
                pointsCount = 0;
            }

            document.getElementById("session-id").textContent =
                trackingSessionId;

            document.getElementById("points-count").textContent = "0";

            updateTrackingStatus(true);
            document.getElementById("start-btn").textContent =
                "▶ Start Tracking";

            watchId = navigator.geolocation.watchPosition(
                onLocationSuccess,
                onLocationError,
                {
                    enableHighAccuracy: true,
                    maximumAge: 0,
                    timeout: 20000
                }
            );

            onLocationSuccess(initialPosition);

            showMessage(
                "tracking-message",
                "GPS tracking started. Waiting for location...",
                "success"
            );

        } catch (error) {

            showMessage(
                "tracking-message",
                error.message,
                "error"
            );

        }

    }
);


// =========================================
// STOP TRACKING
// =========================================

document.getElementById("stop-btn").addEventListener(
    "click",
    async () => {

        if (trackingSessionId === null) {
            return;
        }

        const sessionToStop = trackingSessionId;

        // Stop collecting GPS updates immediately
        trackingActive = false;

        if (watchId !== null) {

            navigator.geolocation.clearWatch(watchId);

            watchId = null;

        }

        try {

            await apiRequest(
                "/tracking/stop",
                "POST",
                {
                    session_id: sessionToStop
                }
            );

            trackingSessionId = null;

            updateTrackingStatus(false);
            document.getElementById("start-btn").textContent =
                "▶ Start Tracking";

            showMessage(
                "tracking-message",
                "Tracking stopped successfully.",
                "success"
            );

        } catch (error) {

            showMessage(
                "tracking-message",
                "Tracking stopped locally, but server confirmation failed: "
                + error.message,
                "error"
            );

            document.getElementById("start-btn").disabled = true;
            document.getElementById("stop-btn").disabled = false;

        }

    }
);


// =========================================
// LOGOUT
// =========================================

document.getElementById("logout-btn").addEventListener(
    "click",
    async () => {

        if (trackingSessionId !== null) {

            alert("Please stop the active tracking session before logging out.");

            return;

        }

        accessToken = null;
        currentUser = null;
        sessionStorage.removeItem("trackme_token");

        trackingSessionId = null;

        trackingSection.classList.add("hidden");
        authSection.classList.remove("hidden");

        loginForm.reset();

        showMessage("auth-message", "You have logged out successfully.", "success");

    }
);


async function restoreSession() {
    if (!accessToken) {
        return;
    }

    try {
        currentUser = await apiRequest("/users/me");
        await openTrackingInterface();
    } catch (error) {
        accessToken = null;
        currentUser = null;
        sessionStorage.removeItem("trackme_token");
        trackingSection.classList.add("hidden");
        authSection.classList.remove("hidden");
        showMessage(
            "auth-message",
            `Your session could not be restored. Please sign in again. ${error.message}`,
            "error"
        );
    }
}

restoreSession();
