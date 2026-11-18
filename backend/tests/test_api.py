import unittest
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError

from app.main import (
    GeofenceCreate,
    LocationCreate,
    SharingGrant,
    UserRegister,
    accessible_users,
    check_geofences,
    check_location_access,
    current_tracking,
    create_geofence,
    delete_geofence,
    list_geofences,
    register_user,
    save_location,
)


class FakeResult:
    def __init__(
        self,
        *,
        first=None,
        rows=None,
        scalar=None,
        rowcount=0,
        lastrowid=None,
    ):
        self.first_value = first
        self.rows = rows or []
        self.scalar_value = scalar
        self.rowcount = rowcount
        self.lastrowid = lastrowid

    def mappings(self):
        return self

    def first(self):
        return self.first_value

    def all(self):
        return self.rows

    def scalar(self):
        return self.scalar_value

    def scalar_one(self):
        return self.scalar_value


class FakeDatabase:
    def __init__(self, *results):
        self.results = list(results)
        self.statements = []
        self.committed = False

    def execute(self, statement, params=None):
        self.statements.append((str(statement), params))
        if not self.results:
            raise AssertionError("Unexpected database query")
        return self.results.pop(0)

    def commit(self):
        self.committed = True


class SchemaTests(unittest.TestCase):
    def test_registration_trims_name_and_rejects_blank_name(self):
        user = UserRegister(
            full_name="  Alex Example  ",
            email="alex@example.com",
            password="long-enough-password",
        )
        self.assertEqual(user.full_name, "Alex Example")

        with self.assertRaises(ValidationError):
            UserRegister(
                full_name="   ",
                email="alex@example.com",
                password="long-enough-password",
            )

    def test_location_coordinates_are_bounded(self):
        LocationCreate(session_id=1, latitude=90, longitude=-180)
        with self.assertRaises(ValidationError):
            LocationCreate(session_id=1, latitude=90.1, longitude=0)

    def test_sharing_requires_exactly_one_viewer_identifier(self):
        self.assertEqual(
            SharingGrant(viewer_email="viewer@example.com").viewer_email,
            "viewer@example.com",
        )
        self.assertEqual(SharingGrant(viewer_id=7).viewer_id, 7)

        for payload in (
            {},
            {"viewer_id": 7, "viewer_email": "viewer@example.com"},
        ):
            with self.subTest(payload=payload):
                with self.assertRaises(ValidationError):
                    SharingGrant.model_validate(payload)

    def test_geofence_requires_a_named_polygon_with_distinct_points(self):
        zone = GeofenceCreate(
            name="  Office  ",
            vertices=[
                {"latitude": 0.3, "longitude": 32.5},
                {"latitude": 0.31, "longitude": 32.5},
                {"latitude": 0.3, "longitude": 32.51},
            ],
        )
        self.assertEqual(zone.name, "Office")

        with self.assertRaises(ValidationError):
            GeofenceCreate(
                name="Office",
                vertices=[
                    {"latitude": 0.3, "longitude": 32.5},
                    {"latitude": 0.3, "longitude": 32.5},
                    {"latitude": 0.3, "longitude": 32.5},
                ],
            )


class SharingTests(unittest.TestCase):
    def test_accessible_users_uses_tidb_compatible_latest_session_join(self):
        expected_user = {
            "user_id": 4,
            "full_name": "Alex Example",
            "email": "alex@example.com",
            "session_id": 11,
            "tracking_status": "active",
        }
        db = FakeDatabase(FakeResult(rows=[expected_user]))

        result = accessible_users(db, current_user={"user_id": 8})

        self.assertEqual(result["users"], [expected_user])
        query, params = db.statements[0]
        self.assertIn("MAX(session_id)", query)
        self.assertIn("GROUP BY user_id", query)
        self.assertNotIn("ON ts.session_id = (", query)
        self.assertEqual(params, {"viewer_id": 8})


class AuthenticationTests(unittest.TestCase):
    def test_registration_commits_user_and_returns_created_id(self):
        db = FakeDatabase(FakeResult(lastrowid=12))

        with patch("app.main.hash_password", return_value="hashed-password"):
            result = register_user(
                UserRegister(
                    full_name="Alex Example",
                    email="alex@example.com",
                    password="long-enough-password",
                ),
                db,
            )

        self.assertTrue(db.committed)
        self.assertEqual(result["user_id"], 12)
        self.assertEqual(
            db.statements[0][1],
            {
                "name": "Alex Example",
                "email": "alex@example.com",
                "password": "hashed-password",
            },
        )


class PermissionTests(unittest.TestCase):
    def test_owner_can_access_without_permission_lookup(self):
        db = FakeDatabase()
        self.assertTrue(check_location_access(db, owner_id=4, viewer_id=4))
        self.assertEqual(db.statements, [])

    def test_unapproved_viewer_is_denied(self):
        db = FakeDatabase(FakeResult(first=None))
        with self.assertRaises(HTTPException) as raised:
            check_location_access(db, owner_id=4, viewer_id=8)
        self.assertEqual(raised.exception.status_code, 403)


class TrackingTests(unittest.TestCase):
    def test_save_location_does_not_require_spatial_column(self):
        db = FakeDatabase(
            FakeResult(first={"session_id": 11}),
            FakeResult(),
            FakeResult(rows=[]),
        )

        result = save_location(
            LocationCreate(
                session_id=11,
                latitude=0.3,
                longitude=32.5,
                accuracy=8,
                speed=0,
            ),
            db,
            current_user={"user_id": 4},
        )

        insert_sql, params = db.statements[1]
        self.assertIn("INSERT INTO location_points", insert_sql)
        self.assertNotIn("ST_SRID", insert_sql)
        self.assertNotIn("location,", insert_sql)
        self.assertEqual(params["latitude"], 0.3)
        self.assertEqual(params["longitude"], 32.5)
        self.assertEqual(result["message"], "Location recorded successfully")
        self.assertTrue(db.committed)

    def test_current_tracking_returns_latest_point_and_count(self):
        db = FakeDatabase(
            FakeResult(first={
                "session_id": 11,
                "started_at": "2026-11-09 12:00:00",
            }),
            FakeResult(first={
                "latitude": 0.3,
                "longitude": 32.5,
                "accuracy": 8,
                "speed": 0,
                "recorded_at": "2026-11-09 12:00:10",
            }),
            FakeResult(scalar=2),
        )

        result = current_tracking(db, current_user={"user_id": 4})

        self.assertEqual(result["status"], "active")
        self.assertEqual(result["points_count"], 2)
        self.assertEqual(result["latest_location"]["latitude"], 0.3)

    def test_current_tracking_reports_no_active_session(self):
        db = FakeDatabase(FakeResult(first=None))
        result = current_tracking(db, current_user={"user_id": 4})
        self.assertEqual(result["session_id"], None)
        self.assertEqual(result["status"], "stopped")
        self.assertEqual(result["points_count"], 0)
        self.assertEqual(result["latest_location"], None)

    def test_geofence_entry_and_exit_are_recorded(self):
        for previous_event, longitude, expected in (
            (None, 32.5, "ENTER"),
            ("ENTER", 32.7, "EXIT"),
        ):
            with self.subTest(expected=expected):
                db = FakeDatabase(
                    FakeResult(rows=[{
                        "geofence_id": 3,
                        "name": "Office",
                        "boundary": (
                            "POLYGON((32.4 0.2, 32.6 0.2, 32.6 0.4, "
                            "32.4 0.4, 32.4 0.2))"
                        ),
                    }]),
                    FakeResult(scalar=previous_event),
                    FakeResult(),
                )

                alerts = check_geofences(
                    db,
                    session_id=11,
                    owner_id=4,
                    latitude=0.3,
                    longitude=longitude,
                )

                self.assertEqual(alerts[0]["event_type"], expected)
                self.assertEqual(db.statements[0][1]["owner_id"], 4)
                self.assertIn("INSERT INTO geofence_alerts", db.statements[-1][0])
                self.assertEqual(db.statements[-1][1]["event_type"], expected)
                self.assertNotIn("ST_Contains", db.statements[0][0])

    def test_staying_inside_does_not_repeat_entry_alert(self):
        db = FakeDatabase(
            FakeResult(rows=[{
                "geofence_id": 3,
                "name": "Office",
                "boundary": (
                    "POLYGON((32.4 0.2, 32.6 0.2, 32.6 0.4, "
                    "32.4 0.4, 32.4 0.2))"
                ),
            }]),
            FakeResult(scalar="ENTER"),
        )

        alerts = check_geofences(
            db, session_id=11, owner_id=4, latitude=0.3, longitude=32.5
        )

        self.assertEqual(alerts, [])
        self.assertEqual(len(db.statements), 2)

    def test_create_geofence_stores_text_boundary(self):
        db = FakeDatabase(FakeResult(lastrowid=7))
        data = GeofenceCreate(
            name="Office",
            vertices=[
                {"latitude": 0.2, "longitude": 32.4},
                {"latitude": 0.2, "longitude": 32.6},
                {"latitude": 0.4, "longitude": 32.6},
                {"latitude": 0.4, "longitude": 32.4},
            ],
        )

        result = create_geofence(data, db, current_user={"user_id": 4})

        query, params = db.statements[0]
        self.assertIn("INSERT INTO geofences", query)
        self.assertNotIn("ST_GeomFromText", query)
        self.assertEqual(
            params["boundary"],
            "POLYGON((32.4 0.2, 32.6 0.2, 32.6 0.4, "
            "32.4 0.4, 32.4 0.2))",
        )
        self.assertEqual(result["geofence_id"], 7)
        self.assertTrue(db.committed)

    def test_create_geofence_rejects_self_intersecting_polygon(self):
        db = FakeDatabase()
        data = GeofenceCreate(
            name="Bow tie",
            vertices=[
                {"latitude": 0, "longitude": 0},
                {"latitude": 1, "longitude": 1},
                {"latitude": 1, "longitude": 0},
                {"latitude": 0, "longitude": 1},
            ],
        )

        with self.assertRaises(HTTPException) as raised:
            create_geofence(data, db, current_user={"user_id": 4})

        self.assertEqual(raised.exception.status_code, 422)
        self.assertEqual(db.statements, [])

    def test_list_geofences_returns_wkt_boundary_directly(self):
        boundary = "POLYGON((32.4 0.2, 32.6 0.2, 32.6 0.4, 32.4 0.2))"
        db = FakeDatabase(FakeResult(rows=[{
            "geofence_id": 3,
            "name": "Office",
            "boundary": boundary,
            "created_at": "2026-11-18 00:00:00",
        }]))

        result = list_geofences(db, current_user={"user_id": 4})

        self.assertEqual(result["geofences"][0]["boundary"], boundary)
        self.assertNotIn("ST_AsText", db.statements[0][0])

    def test_owner_can_delete_geofence_and_its_alerts(self):
        db = FakeDatabase(
            FakeResult(first={"geofence_id": 3}),
            FakeResult(),
            FakeResult(rowcount=1),
        )

        result = delete_geofence(
            geofence_id=3,
            db=db,
            current_user={"user_id": 4},
        )

        self.assertEqual(result["message"], "Geofence deleted successfully")
        self.assertIn("DELETE FROM geofence_alerts", db.statements[1][0])
        self.assertIn("DELETE FROM geofences", db.statements[2][0])
        self.assertTrue(db.committed)

    def test_owner_cannot_delete_another_users_geofence(self):
        db = FakeDatabase(FakeResult(first=None))
        with self.assertRaises(HTTPException) as raised:
            delete_geofence(
                geofence_id=3,
                db=db,
                current_user={"user_id": 4},
            )
        self.assertEqual(raised.exception.status_code, 404)
        self.assertEqual(len(db.statements), 1)


if __name__ == "__main__":
    unittest.main()
