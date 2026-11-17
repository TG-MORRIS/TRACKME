
const API_BASE = window.TRACKME_API_BASE ||
    (window.location.port === "5500"
        ? `${window.location.protocol}//${window.location.hostname}:8000`
        : window.location.origin);

let accessToken = null;
let map;
let markers = {};
let selectedUserId = null;
let routeLine = null;
let refreshTimer = null;

// HTML elements
const loginForm = document.getElementById("dashboard-login");
const loginPanel = document.getElementById("login-panel");
const dashboardContent = document.getElementById("dashboard-content");
const loginMessage = document.getElementById("login-message");
const connectionStatus = document.getElementById("connection-status");
const logoutButton = document.getElementById("logout-btn");

// Initialise Leaflet map
map = L.map("map").setView([-0.607, 30.654], 13);

L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: "&copy; OpenStreetMap contributors",
    maxZoom: 19
}).addTo(map);

// API helper
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
        throw new Error(message || `Request failed: ${response.status}`);
    }

    return result;
}

// Login
// Load geofence alerts for authorized users
async function loadGeofenceAlerts(users) {
    const alertsContainer = document.getElementById("geofence-alerts");
    const allAlerts = [];

    for (const user of users) {
        if (!user.session_id) continue;

        try {
            const result = await apiRequest(
                `/geofences/alerts?session_id=${user.session_id}`
            );

            for (const alert of (result.alerts || [])) {
                allAlerts.push({
                    ...alert,
                    userName: user.full_name || user.email || "User"
                });
            }

        } catch (error) {
            console.warn(
                `Could not load alerts for ${user.full_name}:`,
                error
            );
        }
    }

    alertsContainer.innerHTML = "";

    allAlerts.sort(
        (a, b) => new Date(b.recorded_at) - new Date(a.recorded_at)
    );

    if (allAlerts.length === 0) {
        alertsContainer.textContent = "No geofence alerts yet.";
        return;
    }

    for (const alert of allAlerts.slice(0, 10)) {
        const item = document.createElement("div");

        const heading = document.createElement("strong");
        heading.textContent =
            `${alert.event_type}: ${alert.userName}`;

        const details = document.createElement("p");
        details.textContent =
            `${alert.userName} ${alert.event_type === "ENTER" ? "entered" : "left"} ${alert.geofence_name}`;

        const time = document.createElement("small");
        time.textContent = new Date(alert.recorded_at).toLocaleString();

        item.appendChild(heading);
        item.appendChild(details);
        item.appendChild(time);

        item.style.padding = "10px";
        item.style.borderBottom = "1px solid #ccc";

        alertsContainer.appendChild(item);
    }
}
loginForm.addEventListener("submit", async (event) => {
    event.preventDefault();

    const email = document.getElementById("email").value.trim();
    const password = document.getElementById("password").value;

    try {
        loginMessage.textContent = "Signing in...";

        const result = await apiRequest("/auth/login", "POST", {
            email,
            password
        });

        accessToken = result.access_token;

        if (!accessToken) {
            throw new Error("Login succeeded but no access token was returned.");
        }

        sessionStorage.setItem("trackme_token", accessToken);

        loginMessage.textContent = "Login successful.";

        await openDashboard();

    } catch (error) {
        loginMessage.textContent = error.message;
        console.error("Dashboard login error:", error);
    }
});

// Open dashboard
async function openDashboard() {
    try {
        await apiRequest("/users/me");

        loginPanel.classList.add("hidden");
        dashboardContent.classList.remove("hidden");
        logoutButton.style.display = "inline-block";

        connectionStatus.textContent = "Connected";
        connectionStatus.style.color = "green";

        await loadAuthorizedUsers();

        if (refreshTimer) {
            clearInterval(refreshTimer);
        }

        refreshTimer = setInterval(loadAuthorizedUsers, 10000);

        setTimeout(() => map.invalidateSize(), 200);

    } catch (error) {
        console.error("Dashboard initialization error:", error);
        connectionStatus.textContent = "Connection error";
        throw error;
    }
}

// Load users who have granted access
async function loadAuthorizedUsers() {
    try {
        const result = await apiRequest("/sharing/accessible-users");
        const users = result.users || [];

        document.getElementById("total-users").textContent = users.length;

        const userList = document.getElementById("user-list");
        userList.innerHTML = "";

        const authorizedUserIds = new Set(
            users.map(user => String(user.user_id))
        );
        let activeCount = 0;

        if (users.length === 0) {
            userList.textContent = "No authorized users found.";
        }

        for (const user of users) {
            const userId = user.user_id;

            let location = null;

            try {
                location = await apiRequest(`/locations/latest/${userId}`);
            } catch (error) {
                console.warn(`No latest location for user ${userId}:`, error);
            }

            const lat = Number(location?.latitude);
            const lng = Number(location?.longitude);
            const hasCoordinates =
                location &&
                Number.isFinite(lat) &&
                Number.isFinite(lng);

            const isActive =
                user.tracking_status === "active" ||
                user.tracking_status === "running";

            if (isActive) activeCount++;

            const button = document.createElement("button");
            button.type = "button";
            button.className = "user-item user-card";
            button.textContent =
                `${user.full_name || user.email} - ${isActive ? "Active" : "Inactive"}`;

            button.addEventListener("click", () => {
                selectUser(user, location);
            });

            userList.appendChild(button);

            if (hasCoordinates) {
                updateMarker(user, lat, lng, isActive);
                if (String(selectedUserId) === String(userId)) {
                    document.getElementById("selected-location").textContent =
                        `Latitude: ${lat}, Longitude: ${lng}`;
                }
            } else if (markers[userId]) {
                map.removeLayer(markers[userId]);
                delete markers[userId];
            }

            if (!hasCoordinates &&
                String(selectedUserId) === String(userId)) {
                document.getElementById("selected-location").textContent =
                    "No location available yet.";
                document.getElementById("history-btn").disabled = true;
            }
        }

        for (const userId of Object.keys(markers)) {
            if (!authorizedUserIds.has(userId)) {
                map.removeLayer(markers[userId]);
                delete markers[userId];
            }
        }

        if (selectedUserId !== null &&
            !authorizedUserIds.has(String(selectedUserId))) {
            selectedUserId = null;
            if (routeLine) {
                map.removeLayer(routeLine);
                routeLine = null;
            }
            document.getElementById("selected-name").textContent = "None selected";
            document.getElementById("selected-location").textContent =
                "No location available";
            document.getElementById("selected-distance").textContent = "Distance: --";
            document.getElementById("history-btn").disabled = true;
        }

        await loadGeofenceAlerts(users);

        document.getElementById("active-users").textContent = activeCount;

        connectionStatus.textContent = "Connected";
    } catch (error) {
        connectionStatus.textContent = "Update failed";
        console.error("Could not load authorized users:", error);
    }
}

// Add or update map markers
function updateMarker(user, lat, lng, isActive) {
    const userId = user.user_id;

    const color = isActive ? "green" : "gray";

    const icon = L.divIcon({
        className: "",
        html: `<div style="
            background:${color};
            width:16px;
            height:16px;
            border:3px solid white;
            border-radius:50%;
            box-shadow:0 1px 5px #555;
        "></div>`,
        iconSize: [22, 22],
        iconAnchor: [11, 11]
    });

    const popup = document.createElement("div");
    const name = document.createElement("strong");
    name.textContent = user.full_name || user.email || "User";
    popup.appendChild(name);

    const marker = markers[userId];

    if (marker) {
        marker.setLatLng([lat, lng]);
        marker.setIcon(icon);
        marker.setPopupContent(popup);
    } else {
        markers[userId] = L.marker([lat, lng], { icon })
            .addTo(map)
            .bindPopup(popup);
    }
}

// Select user
function selectUser(user, location) {
    selectedUserId = user.user_id;

    document.getElementById("selected-name").textContent =
        user.full_name || user.email || "Unknown user";

    if (location && Number.isFinite(Number(location.latitude)) &&
        Number.isFinite(Number(location.longitude))) {

        const lat = Number(location.latitude);
        const lng = Number(location.longitude);

        document.getElementById("selected-location").textContent =
            `Latitude: ${lat}, Longitude: ${lng}`;

        map.setView([lat, lng], 16);

        if (markers[selectedUserId]) {
            markers[selectedUserId].openPopup();
        }

        document.getElementById("history-btn").disabled = false;

    } else {
        document.getElementById("selected-location").textContent =
            "No location available yet.";

        document.getElementById("history-btn").disabled = true;
    }
}

// Haversine distance in kilometres
function calculateDistance(points) {
    const earthRadius = 6371;
    let total = 0;

    for (let i = 1; i < points.length; i++) {
        const lat1 = Number(points[i - 1].latitude) * Math.PI / 180;
        const lat2 = Number(points[i].latitude) * Math.PI / 180;

        const dLat = lat2 - lat1;
        const dLng =
            (Number(points[i].longitude) -
            Number(points[i - 1].longitude)) * Math.PI / 180;

        const a =
            Math.sin(dLat / 2) ** 2 +
            Math.cos(lat1) * Math.cos(lat2) *
            Math.sin(dLng / 2) ** 2;

        total += 2 * earthRadius *
            Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
    }

    return total;
}

// Show movement history
async function showHistory() {
    if (!selectedUserId) return;

    try {
        const result = await apiRequest(
            `/locations/history/${selectedUserId}?limit=1000`
        );

        const points = result.locations || result.history || [];

        if (points.length < 2) {
            alert("Not enough location points to display a route.");
            return;
        }

        const validPoints = points.filter(point =>
            Number.isFinite(Number(point.latitude)) &&
            Number.isFinite(Number(point.longitude))
        );

        if (validPoints.length < 2) {
            alert("No valid GPS coordinates found.");
            return;
        }

        const coordinates = validPoints.map(point => [
            Number(point.latitude),
            Number(point.longitude)
        ]);

        if (routeLine) {
            map.removeLayer(routeLine);
        }

        routeLine = L.polyline(coordinates, {
            color: "blue",
            weight: 4
        }).addTo(map);

        map.fitBounds(routeLine.getBounds(), { padding: [30, 30] });

        const distance = calculateDistance(validPoints);

        document.getElementById("selected-distance").textContent =
            `Distance: ${distance.toFixed(2)} km`;

    } catch (error) {
        console.error("History error:", error);
        alert("Could not load movement history: " + error.message);
    }
}

document.getElementById("history-btn").addEventListener("click", showHistory);

// Clear route
document.getElementById("clear-route-btn").addEventListener("click", () => {
    if (routeLine) {
        map.removeLayer(routeLine);
        routeLine = null;
    }

    document.getElementById("selected-distance").textContent =
        "Distance: --";
});

// Logout
logoutButton.addEventListener("click", () => {
    if (refreshTimer) {
        clearInterval(refreshTimer);
    }

    sessionStorage.removeItem("trackme_token");
    accessToken = null;

    for (const marker of Object.values(markers)) {
        map.removeLayer(marker);
    }
    markers = {};
    if (routeLine) {
        map.removeLayer(routeLine);
        routeLine = null;
    }
    selectedUserId = null;

    loginPanel.classList.remove("hidden");
    dashboardContent.classList.add("hidden");
    document.getElementById("total-users").textContent = "0";
    document.getElementById("active-users").textContent = "0";
    document.getElementById("user-list").textContent = "Sign in to view shared users.";
    document.getElementById("selected-name").textContent = "None selected";
    document.getElementById("selected-location").textContent = "No location available";
    document.getElementById("selected-distance").textContent = "Distance: --";
    document.getElementById("history-btn").disabled = true;

    connectionStatus.textContent = "Disconnected";

    loginMessage.textContent = "";
});

// Initial connection state
logoutButton.style.display = "none";
connectionStatus.textContent = "Ready to connect";

const savedToken = sessionStorage.getItem("trackme_token");
if (savedToken) {
    accessToken = savedToken;
    openDashboard().catch(() => {
        sessionStorage.removeItem("trackme_token");
        accessToken = null;
        loginMessage.textContent = "Your session expired. Please sign in again.";
        connectionStatus.textContent = "Ready to connect";
    });
}
