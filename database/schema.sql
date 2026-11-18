
CREATE DATABASE IF NOT EXISTS trackme_db;

USE trackme_db;

-- =================================
-- 1. USERS TABLE
-- =================================

CREATE TABLE users (
    user_id INT AUTO_INCREMENT PRIMARY KEY,
    full_name VARCHAR(100) NOT NULL,
    email VARCHAR(150) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    role ENUM('admin', 'user') DEFAULT 'user',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- =================================
-- 2. TRACKING SESSIONS
-- =================================

CREATE TABLE tracking_sessions (
    session_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    ended_at TIMESTAMP NULL,
    status ENUM('active', 'stopped') DEFAULT 'active',

    FOREIGN KEY (user_id)
        REFERENCES users(user_id)
        ON DELETE CASCADE,

    INDEX idx_session_user (user_id),
    INDEX idx_session_status (status)
);

-- =================================
-- 3. LOCATION POINTS
-- =================================

CREATE TABLE location_points (
    location_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    session_id BIGINT NOT NULL,

    latitude DOUBLE NOT NULL,
    longitude DOUBLE NOT NULL,

    accuracy DOUBLE NULL,
    speed DOUBLE NULL,

    recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (session_id)
        REFERENCES tracking_sessions(session_id)
        ON DELETE CASCADE,

    INDEX idx_location_session_time (session_id, recorded_at),

    CHECK (latitude BETWEEN -90 AND 90),
    CHECK (longitude BETWEEN -180 AND 180)
);

-- =================================
-- 4. SHARING PERMISSIONS
-- =================================

CREATE TABLE sharing_permissions (
    permission_id BIGINT AUTO_INCREMENT PRIMARY KEY,

    user_id INT NOT NULL,
    viewer_id INT NOT NULL,

    status ENUM('pending', 'approved', 'revoked')
        DEFAULT 'pending',

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (user_id)
        REFERENCES users(user_id)
        ON DELETE CASCADE,

    FOREIGN KEY (viewer_id)
        REFERENCES users(user_id)
        ON DELETE CASCADE,

    UNIQUE KEY unique_permission (user_id, viewer_id),

    CHECK (user_id <> viewer_id)
);

-- =================================
-- 5. GEOFENCES
-- =================================

CREATE TABLE geofences (
    geofence_id INT AUTO_INCREMENT PRIMARY KEY,

    name VARCHAR(100) NOT NULL,

    boundary TEXT NULL,

    created_by INT NOT NULL,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (created_by)
        REFERENCES users(user_id)
        ON DELETE CASCADE

);

-- =================================
-- 6. GEOFENCE ALERTS
-- =================================

CREATE TABLE geofence_alerts (
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

-- =================================
-- DATABASE CREATED
-- =================================

SELECT 'TRACKME DATABASE CREATED SUCCESSFULLY'
AS MESSAGE;
