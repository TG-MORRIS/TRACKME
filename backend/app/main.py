import logging
import re
from pathlib import Path

from fastapi.middleware.cors import CORSMiddleware
from fastapi import FastAPI, HTTPException, Depends, status, Query
from fastapi.responses import FileResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator
from sqlalchemy.orm import Session
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

import jwt

from app.database import get_db, test_database
from app.config import settings
from app.security import (
    hash_password,
    verify_password,
    create_access_token,
    decode_access_token
)


# =========================================
# APPLICATION INITIALIZATION
# =========================================

logger = logging.getLogger(__name__)
FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"

app = FastAPI(
    title="TRACKME API",
    description="Real-Time Mobile GPS Tracking System Using GIS",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin.strip()
        for origin in settings.FRONTEND_ORIGINS.split(",")
        if origin.strip()
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"]
)

security = HTTPBearer()


# =========================================
# PYDANTIC SCHEMAS
# =========================================

class UserRegister(BaseModel):
    full_name: str = Field(min_length=2, max_length=100)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)

    @field_validator("full_name", mode="before")
    @classmethod
    def strip_full_name(cls, value):
        return value.strip() if isinstance(value, str) else value


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class TrackingStop(BaseModel):
    session_id: int


class LocationCreate(BaseModel):
    session_id: int

    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)

    accuracy: float | None = Field(default=None, ge=0)
    speed: float | None = Field(default=None, ge=0)


class GeofenceVertex(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class GeofenceCreate(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    vertices: list[GeofenceVertex] = Field(min_length=3, max_length=100)

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, value):
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def require_three_distinct_vertices(self):
        distinct_vertices = {
            (vertex.latitude, vertex.longitude)
            for vertex in self.vertices
        }
        if len(distinct_vertices) < 3:
            raise ValueError("A geofence needs at least three distinct points")
        return self


class SharingGrant(BaseModel):
    viewer_id: int | None = None
    viewer_email: EmailStr | None = None

    @model_validator(mode="after")
    def require_viewer(self):
        if (self.viewer_id is None) == (self.viewer_email is None):
            raise ValueError("Provide exactly one of viewer_id or viewer_email")
        return self


# =========================================
# AUTHENTICATION DEPENDENCY
# =========================================

def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
):

    token = credentials.credentials

    try:
        payload = decode_access_token(token)
        user_id = int(payload["sub"])

    except (jwt.InvalidTokenError, ValueError, KeyError):
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired authentication token"
        )

    result = db.execute(
        text("""
            SELECT user_id, full_name, email, role
            FROM users
            WHERE user_id = :user_id
        """),
        {"user_id": user_id}
    ).mappings().first()

    if not result:
        raise HTTPException(
            status_code=401,
            detail="User account not found"
        )

    return dict(result)


# =========================================
# LOCATION ACCESS CONTROL
# =========================================

def check_location_access(db, owner_id, viewer_id):

    if owner_id == viewer_id:
        return True

    permission = db.execute(
        text("""
            SELECT permission_id
            FROM sharing_permissions
            WHERE user_id = :owner_id
            AND viewer_id = :viewer_id
            AND status = 'approved'
        """),
        {
            "owner_id": owner_id,
            "viewer_id": viewer_id
        }
    ).first()

    if not permission:
        raise HTTPException(
            status_code=403,
            detail="You do not have permission to view this user's location"
        )

    return True


# =========================================
# HOME AND HEALTH CHECK
# =========================================

@app.get("/")
def home():
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/health")
def health():

    try:
        database = test_database()

        return {
            "api": "healthy",
            "database": "connected",
            "database_name": database
        }

    except Exception:
        logger.exception("Database health check failed")
        raise HTTPException(
            status_code=503,
            detail="Database connection failed"
        )


# =========================================
# USER REGISTRATION
# =========================================

@app.post("/auth/register", status_code=201)
def register_user(
    user: UserRegister,
    db: Session = Depends(get_db)
):

    hashed_password = hash_password(user.password)

    try:

        result = db.execute(
            text("""
                INSERT INTO users
                (full_name, email, password_hash, role)
                VALUES
                (:name, :email, :password, 'user')
            """),
            {
                "name": user.full_name.strip(),
                "email": str(user.email).lower(),
                "password": hashed_password
            }
        )

        db.commit()

        return {
            "message": "User registered successfully",
            "user_id": result.lastrowid
        }

    except IntegrityError:

        db.rollback()

        raise HTTPException(
            status_code=409,
            detail="Email address is already registered"
        )


# =========================================
# USER LOGIN
# =========================================

@app.post("/auth/login")
def login_user(
    user: UserLogin,
    db: Session = Depends(get_db)
):

    result = db.execute(
        text("""
            SELECT user_id, full_name, email, password_hash, role
            FROM users
            WHERE email = :email
        """),
        {"email": str(user.email).lower()}
    ).mappings().first()

    if not result or not verify_password(
        user.password,
        result["password_hash"]
    ):

        raise HTTPException(
            status_code=401,
            detail="Incorrect email or password"
        )

    token = create_access_token(result["user_id"])

    return {
        "message": "Login successful",
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "user_id": result["user_id"],
            "full_name": result["full_name"],
            "email": result["email"],
            "role": result["role"]
        }
    }


# =========================================
# CURRENT USER
# =========================================

@app.get("/users/me")
def get_me(
    current_user=Depends(get_current_user)
):

    return current_user


# =========================================
# START TRACKING
# =========================================

@app.post("/tracking/start", status_code=201)
def start_tracking(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):

    user_id = current_user["user_id"]

    active_session = db.execute(
        text("""
            SELECT session_id
            FROM tracking_sessions
            WHERE user_id = :user_id
            AND status = 'active'
            LIMIT 1
        """),
        {"user_id": user_id}
    ).mappings().first()

    if active_session:

        return {
            "message": "An active tracking session already exists",
            "session_id": active_session["session_id"]
        }

    result = db.execute(
        text("""
            INSERT INTO tracking_sessions (user_id, status)
            VALUES (:user_id, 'active')
        """),
        {"user_id": user_id}
    )

    db.commit()

    return {
        "message": "Tracking started successfully",
        "session_id": result.lastrowid,
        "status": "active"
    }


@app.get("/tracking/current")
def current_tracking(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    active_session = db.execute(
        text("""
            SELECT session_id, started_at
            FROM tracking_sessions
            WHERE user_id = :user_id
            AND status = 'active'
            ORDER BY session_id DESC
            LIMIT 1
        """),
        {"user_id": current_user["user_id"]}
    ).mappings().first()

    if not active_session:
        return {
            "session_id": None,
            "status": "stopped",
            "points_count": 0,
            "latest_location": None
        }

    latest_location = db.execute(
        text("""
            SELECT latitude, longitude, accuracy, speed, recorded_at
            FROM location_points
            WHERE session_id = :session_id
            ORDER BY recorded_at DESC, location_id DESC
            LIMIT 1
        """),
        {"session_id": active_session["session_id"]}
    ).mappings().first()

    points_count = db.execute(
        text("""
            SELECT COUNT(*)
            FROM location_points
            WHERE session_id = :session_id
        """),
        {"session_id": active_session["session_id"]}
    ).scalar_one()

    return {
        **dict(active_session),
        "status": "active",
        "points_count": points_count,
        "latest_location": dict(latest_location) if latest_location else None
    }


# =========================================
# STOP TRACKING
# =========================================

@app.post("/tracking/stop")
def stop_tracking(
    data: TrackingStop,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):

    result = db.execute(
        text("""
            UPDATE tracking_sessions
            SET status = 'stopped',
                ended_at = CURRENT_TIMESTAMP
            WHERE session_id = :session_id
            AND user_id = :user_id
            AND status = 'active'
        """),
        {
            "session_id": data.session_id,
            "user_id": current_user["user_id"]
        }
    )

    db.commit()

    if result.rowcount == 0:

        raise HTTPException(
            status_code=404,
            detail="Active tracking session not found"
        )

    return {
        "message": "Tracking stopped successfully",
        "status": "stopped"
    }


def _orientation(first, second, third):
    return (
        (second[0] - first[0]) * (third[1] - first[1])
        - (second[1] - first[1]) * (third[0] - first[0])
    )


def _point_on_segment(point, start, end):
    epsilon = 1e-12
    return (
        abs(_orientation(start, end, point)) <= epsilon
        and min(start[0], end[0]) - epsilon <= point[0] <= max(start[0], end[0]) + epsilon
        and min(start[1], end[1]) - epsilon <= point[1] <= max(start[1], end[1]) + epsilon
    )


def _segments_intersect(first_start, first_end, second_start, second_end):
    epsilon = 1e-12
    orientations = (
        _orientation(first_start, first_end, second_start),
        _orientation(first_start, first_end, second_end),
        _orientation(second_start, second_end, first_start),
        _orientation(second_start, second_end, first_end),
    )

    if (
        (
            orientations[0] > epsilon
            and orientations[1] < -epsilon
            or orientations[0] < -epsilon
            and orientations[1] > epsilon
        )
        and (
            orientations[2] > epsilon
            and orientations[3] < -epsilon
            or orientations[2] < -epsilon
            and orientations[3] > epsilon
        )
    ):
        return True

    return (
        (abs(orientations[0]) <= epsilon and
         _point_on_segment(second_start, first_start, first_end))
        or (abs(orientations[1]) <= epsilon and
            _point_on_segment(second_end, first_start, first_end))
        or (abs(orientations[2]) <= epsilon and
            _point_on_segment(first_start, second_start, second_end))
        or (abs(orientations[3]) <= epsilon and
            _point_on_segment(first_end, second_start, second_end))
    )


def _is_valid_polygon(vertices):
    points = vertices[:-1] if vertices[0] == vertices[-1] else vertices
    count = len(points)
    if count < 3 or len(set(points)) < 3:
        return False

    area = sum(
        points[index][0] * points[(index + 1) % count][1]
        - points[(index + 1) % count][0] * points[index][1]
        for index in range(count)
    )
    if abs(area) <= 1e-12:
        return False

    for first_index in range(count):
        first_start = points[first_index]
        first_end = points[(first_index + 1) % count]
        if first_start == first_end:
            return False

        for second_index in range(first_index + 1, count):
            if (
                (first_index + 1) % count == second_index
                or (second_index + 1) % count == first_index
            ):
                continue

            if _segments_intersect(
                first_start,
                first_end,
                points[second_index],
                points[(second_index + 1) % count],
            ):
                return False

    return True


def _parse_polygon_boundary(boundary):
    match = re.fullmatch(
        r"\s*POLYGON\s*\(\(\s*(.*?)\s*\)\)\s*",
        boundary or "",
        re.IGNORECASE,
    )
    if not match:
        raise ValueError("Stored geofence boundary is not a polygon")

    try:
        vertices = [
            tuple(map(float, coordinate.split()))
            for coordinate in match.group(1).split(",")
        ]
    except ValueError as error:
        raise ValueError("Stored geofence boundary has invalid coordinates") from error

    if (
        any(len(vertex) != 2 for vertex in vertices)
        or len(vertices) < 4
        or vertices[0] != vertices[-1]
        or any(
            not -180 <= longitude <= 180 or not -90 <= latitude <= 90
            for longitude, latitude in vertices
        )
        or not _is_valid_polygon(vertices)
    ):
        raise ValueError("Stored geofence boundary is not a valid polygon")

    return vertices


def _point_in_polygon(longitude, latitude, vertices):
    point = (longitude, latitude)
    inside = False

    for index in range(len(vertices) - 1):
        start = vertices[index]
        end = vertices[index + 1]

        if _point_on_segment(point, start, end):
            return False

        if (start[1] > latitude) != (end[1] > latitude):
            crossing_longitude = (
                (end[0] - start[0])
                * (latitude - start[1])
                / (end[1] - start[1])
                + start[0]
            )
            if longitude < crossing_longitude:
                inside = not inside

    return inside


# =========================================
# GEOFENCE DETECTION
# =========================================

def check_geofences(db, session_id, owner_id, latitude, longitude):

    # Find all geofences and check whether the GPS point
    # falls inside each polygon.
    geofences = db.execute(
        text("""
            SELECT
                geofence_id,
                name,
                boundary
            FROM geofences
            WHERE created_by = :owner_id
            AND boundary IS NOT NULL
        """),
        {
            "owner_id": owner_id,
            "longitude": longitude,
            "latitude": latitude
        }
    ).mappings().all()

    alerts = []

    for fence in geofences:

        geofence_id = fence["geofence_id"]
        vertices = _parse_polygon_boundary(fence["boundary"])
        is_inside = _point_in_polygon(longitude, latitude, vertices)

        # Find the most recent alert for this session
        # and geofence.
        previous_event = db.execute(
            text("""
                SELECT event_type
                FROM geofence_alerts
                WHERE session_id = :session_id
                AND geofence_id = :geofence_id
                ORDER BY recorded_at DESC, alert_id DESC
                LIMIT 1
            """),
            {
                "session_id": session_id,
                "geofence_id": geofence_id
            }
        ).scalar()

        # Determine whether a boundary crossing occurred.
        event_type = None

        if is_inside and previous_event != "ENTER":
            event_type = "ENTER"

        elif not is_inside and previous_event == "ENTER":
            event_type = "EXIT"

        if event_type:

            db.execute(
                text("""
                    INSERT INTO geofence_alerts
                    (session_id, geofence_id, event_type)
                    VALUES
                    (:session_id, :geofence_id, :event_type)
                """),
                {
                    "session_id": session_id,
                    "geofence_id": geofence_id,
                    "event_type": event_type
                }
            )

            alerts.append({
                "geofence_id": geofence_id,
                "geofence_name": fence["name"],
                "event_type": event_type
            })

    return alerts


# =========================================
# SAVE GPS LOCATION + GEOFENCE DETECTION
# =========================================

@app.post("/locations", status_code=201)
def save_location(
    location: LocationCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):

    session = db.execute(
        text("""
            SELECT session_id
            FROM tracking_sessions
            WHERE session_id = :session_id
            AND user_id = :user_id
            AND status = 'active'
        """),
        {
            "session_id": location.session_id,
            "user_id": current_user["user_id"]
        }
    ).first()

    if not session:
        raise HTTPException(
            status_code=400,
            detail="No active tracking session found"
        )

    try:

        # Save the GPS location.
        db.execute(
            text("""
                INSERT INTO location_points
                (
                    session_id,
                    latitude,
                    longitude,
                    accuracy,
                    speed
                )
                VALUES
                (
                    :session_id,
                    :latitude,
                    :longitude,
                    :accuracy,
                    :speed
                )
            """),
            {
                "session_id": location.session_id,
                "latitude": location.latitude,
                "longitude": location.longitude,
                "accuracy": location.accuracy,
                "speed": location.speed
            }
        )

        # Check whether the user entered or exited a geofence.
        alerts = check_geofences(
            db,
            location.session_id,
            current_user["user_id"],
            location.latitude,
            location.longitude
        )

        db.commit()

        return {
            "message": "Location recorded successfully",
            "latitude": location.latitude,
            "longitude": location.longitude,
            "geofence_alerts": alerts
        }

    except Exception:
        db.rollback()
        raise

# =========================================
# GET LATEST LOCATION
# =========================================

@app.get("/locations/latest/{user_id}")
def latest_location(
    user_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):

    check_location_access(
        db,
        user_id,
        current_user["user_id"]
    )

    result = db.execute(
        text("""
            SELECT
                lp.latitude,
                lp.longitude,
                lp.accuracy,
                lp.speed,
                lp.recorded_at,
                ts.user_id
            FROM location_points lp
            JOIN tracking_sessions ts
                ON lp.session_id = ts.session_id
            WHERE ts.user_id = :user_id
            ORDER BY lp.recorded_at DESC, lp.location_id DESC
            LIMIT 1
        """),
        {"user_id": user_id}
    ).mappings().first()

    if not result:

        raise HTTPException(
            status_code=404,
            detail="No location records found"
        )

    return dict(result)


# =========================================
# LOCATION HISTORY
# =========================================

@app.get("/locations/history/{user_id}")
def location_history(
    user_id: int,
    limit: int = Query(default=100, ge=1, le=1000),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):

    check_location_access(
        db,
        user_id,
        current_user["user_id"]
    )

    result = db.execute(
        text("""
            SELECT
                lp.latitude,
                lp.longitude,
                lp.accuracy,
                lp.speed,
                lp.recorded_at
            FROM location_points lp
            JOIN tracking_sessions ts
                ON lp.session_id = ts.session_id
            WHERE ts.user_id = :user_id
            ORDER BY lp.recorded_at ASC, lp.location_id ASC
            LIMIT :limit
        """),
        {
            "user_id": user_id,
            "limit": limit
        }
    ).mappings().all()

    return {
        "user_id": user_id,
        "total_points": len(result),
        "locations": [dict(point) for point in result]
    }

    # =========================================
# GET GEOFENCE ALERTS
# =========================================

@app.get("/geofences/alerts")
def get_geofence_alerts(
    session_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):

    # Allow the session owner or an authorized viewer.
    session = db.execute(
        text("""
            SELECT ts.session_id
            FROM tracking_sessions ts
            WHERE ts.session_id = :session_id
            AND (
                ts.user_id = :user_id
                OR EXISTS (
                    SELECT 1
                    FROM sharing_permissions sp
                    WHERE sp.user_id = ts.user_id
                    AND sp.viewer_id = :user_id
                    AND sp.status = 'approved'
                )
            )
        """),
        {
            "session_id": session_id,
            "user_id": current_user["user_id"]
        }
    ).first()

    if not session:
        raise HTTPException(
            status_code=404,
            detail="Tracking session not found"
        )

    results = db.execute(
        text("""
            SELECT
                ga.alert_id,
                ga.session_id,
                ga.geofence_id,
                gf.name AS geofence_name,
                ga.event_type,
                ga.recorded_at
            FROM geofence_alerts ga
            JOIN geofences gf
                ON ga.geofence_id = gf.geofence_id
            WHERE ga.session_id = :session_id
            ORDER BY ga.recorded_at DESC, ga.alert_id DESC
        """),
        {"session_id": session_id}
    ).mappings().all()

    return {
        "session_id": session_id,
        "total_alerts": len(results),
        "alerts": [dict(alert) for alert in results]
    }


@app.get("/geofences")
def list_geofences(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    results = db.execute(
        text("""
            SELECT
                geofence_id,
                name,
                boundary,
                created_at
            FROM geofences
            WHERE created_by = :user_id
            AND boundary IS NOT NULL
            ORDER BY name
        """),
        {"user_id": current_user["user_id"]}
    ).mappings().all()

    return {"geofences": [dict(geofence) for geofence in results]}


@app.post("/geofences", status_code=201)
def create_geofence(
    data: GeofenceCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    vertices = [
        (vertex.longitude, vertex.latitude)
        for vertex in data.vertices
    ]
    if not _is_valid_polygon(vertices):
        raise HTTPException(
            status_code=422,
            detail="The geofence must form a valid, non-crossing polygon"
        )

    if vertices[0] != vertices[-1]:
        vertices.append(vertices[0])

    coordinates = ", ".join(f"{longitude} {latitude}" for longitude, latitude in vertices)
    boundary_wkt = f"POLYGON(({coordinates}))"

    result = db.execute(
        text("""
            INSERT INTO geofences (name, boundary, created_by)
            VALUES (:name, :boundary, :user_id)
        """),
        {
            "name": data.name,
            "boundary": boundary_wkt,
            "user_id": current_user["user_id"]
        }
    )
    db.commit()

    return {
        "message": "Geofence created successfully",
        "geofence_id": result.lastrowid,
        "name": data.name
    }


@app.delete("/geofences/{geofence_id}")
def delete_geofence(
    geofence_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    owned_geofence = db.execute(
        text("""
            SELECT geofence_id
            FROM geofences
            WHERE geofence_id = :geofence_id
            AND created_by = :user_id
        """),
        {
            "geofence_id": geofence_id,
            "user_id": current_user["user_id"]
        }
    ).first()
    if not owned_geofence:
        raise HTTPException(status_code=404, detail="Geofence not found")

    db.execute(
        text("""
            DELETE FROM geofence_alerts
            WHERE geofence_id = :geofence_id
        """),
        {"geofence_id": geofence_id}
    )

    result = db.execute(
        text("""
            DELETE FROM geofences
            WHERE geofence_id = :geofence_id
            AND created_by = :user_id
        """),
        {
            "geofence_id": geofence_id,
            "user_id": current_user["user_id"]
        }
    )
    db.commit()

    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Geofence not found")

    return {"message": "Geofence deleted successfully"}


# =========================================
# GRANT LOCATION SHARING
# =========================================

@app.post("/sharing/grant")
def grant_sharing(
    data: SharingGrant,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):

    owner_id = current_user["user_id"]

    if data.viewer_email is not None:
        viewer = db.execute(
            text("""
                SELECT user_id
                FROM users
                WHERE email = :email
            """),
            {"email": str(data.viewer_email).lower()}
        ).mappings().first()
        viewer_id = viewer["user_id"] if viewer else None
    else:
        viewer_id = data.viewer_id

    if owner_id == viewer_id:

        raise HTTPException(
            status_code=400,
            detail="You cannot grant access to yourself"
        )

    viewer = db.execute(
        text("""
            SELECT user_id
            FROM users
            WHERE user_id = :viewer_id
        """),
        {"viewer_id": viewer_id}
    ).first()

    if not viewer:

        raise HTTPException(
            status_code=404,
            detail="Viewer account not found"
        )

    db.execute(
        text("""
            INSERT INTO sharing_permissions
            (user_id, viewer_id, status)
            VALUES (:owner_id, :viewer_id, 'approved')
            ON DUPLICATE KEY UPDATE status = 'approved'
        """),
        {
            "owner_id": owner_id,
            "viewer_id": viewer_id
        }
    )

    db.commit()

    return {
        "message": "Location sharing granted successfully",
        "viewer_id": viewer_id
    }


@app.get("/sharing/granted-users")
def granted_users(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    results = db.execute(
        text("""
            SELECT
                u.user_id,
                u.full_name,
                u.email,
                sp.status
            FROM sharing_permissions sp
            JOIN users u ON u.user_id = sp.viewer_id
            WHERE sp.user_id = :owner_id
            AND sp.status = 'approved'
            ORDER BY u.full_name
        """),
        {"owner_id": current_user["user_id"]}
    ).mappings().all()

    return {"users": [dict(user) for user in results]}


# =========================================
# REVOKE LOCATION SHARING
# =========================================

@app.delete("/sharing/{viewer_id}")
def revoke_sharing(
    viewer_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):

    result = db.execute(
        text("""
            UPDATE sharing_permissions
            SET status = 'revoked'
            WHERE user_id = :owner_id
            AND viewer_id = :viewer_id
            AND status = 'approved'
        """),
        {
            "owner_id": current_user["user_id"],
            "viewer_id": viewer_id
        }
    )

    db.commit()

    if result.rowcount == 0:

        raise HTTPException(
            status_code=404,
            detail="Active sharing permission not found"
        )

    return {
        "message": "Location sharing revoked successfully"
    }

# =========================================
# AUTHORIZED USERS FOR GIS DASHBOARD
# =========================================

@app.get("/sharing/accessible-users")
def accessible_users(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):

    viewer_id = current_user["user_id"]

    results = db.execute(
        text("""
            SELECT
            u.user_id,
            u.full_name,
            u.email,
            ts.session_id,
            ts.status AS tracking_status
            FROM sharing_permissions sp

            JOIN users u
                ON u.user_id = sp.user_id

            LEFT JOIN (
                SELECT user_id, MAX(session_id) AS session_id
                FROM tracking_sessions
                GROUP BY user_id
            ) latest_session
                ON latest_session.user_id = u.user_id

            LEFT JOIN tracking_sessions ts
                ON ts.session_id = latest_session.session_id

            WHERE sp.viewer_id = :viewer_id
            AND sp.status = 'approved'

            ORDER BY u.full_name
        """),
        {"viewer_id": viewer_id}
    ).mappings().all()

    return {
        "users": [dict(user) for user in results]
    }


app.mount(
    "/",
    StaticFiles(directory=FRONTEND_DIR, html=True),
    name="frontend"
)
