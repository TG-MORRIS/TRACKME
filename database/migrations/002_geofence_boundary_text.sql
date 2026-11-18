USE trackme_db;

ALTER TABLE geofences
    ADD COLUMN boundary TEXT NULL;
