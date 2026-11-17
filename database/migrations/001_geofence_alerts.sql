USE trackme_db;

CREATE TABLE IF NOT EXISTS geofence_alerts (
    alert_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    session_id BIGINT NOT NULL,
    geofence_id INT NOT NULL,
    event_type ENUM('ENTER', 'EXIT') NOT NULL,
    recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (session_id)
        REFERENCES tracking_sessions(session_id)
        ON DELETE CASCADE,

    FOREIGN KEY (geofence_id)
        REFERENCES geofences(geofence_id)
        ON DELETE CASCADE,

    INDEX idx_alert_session_time (session_id, recorded_at)
);
