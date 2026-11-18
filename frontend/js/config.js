if (
    window.location.port !== "5500" &&
    window.location.hostname !== "localhost" &&
    window.location.hostname !== "127.0.0.1"
) {
    window.TRACKME_API_BASE = "https://trackmeapp.onrender.com";
}
