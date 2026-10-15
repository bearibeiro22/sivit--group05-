CREATE TABLE IF NOT EXISTS vigilancia_reading (
    id            BIGSERIAL PRIMARY KEY,
    device_serial TEXT             NOT NULL,
    instant       TIMESTAMPTZ      NOT NULL,
    parameter     TEXT             NOT NULL,
    value         DOUBLE PRECISION NOT NULL,
    unit          TEXT             NOT NULL,
    unvalidated   BOOLEAN          NOT NULL DEFAULT FALSE,
    CONSTRAINT uq_reading UNIQUE (device_serial, instant, parameter)
);
