-- Data Analytics I — Assignment 2, Part 1
-- Snowflake Schema
-- Grain: one row per order item


-- =========================================================
-- GEOGRAPHY HIERARCHY
-- ZIP -> CITY -> STATE -> REGION
-- =========================================================

CREATE TABLE dim_region (
    region_id   INTEGER PRIMARY KEY,
    region_name VARCHAR NOT NULL
);

CREATE TABLE dim_state (
    state_id   INTEGER PRIMARY KEY,
    state_abbr VARCHAR(2) NOT NULL UNIQUE,
    region_id  INTEGER NOT NULL REFERENCES dim_region(region_id)
);

CREATE TABLE dim_city (
    city_id   INTEGER PRIMARY KEY,
    city_name VARCHAR NOT NULL,
    state_id  INTEGER NOT NULL REFERENCES dim_state(state_id)
);

CREATE TABLE dim_zip (
    zip_prefix VARCHAR(5) PRIMARY KEY,
    city_id    INTEGER NOT NULL REFERENCES dim_city(city_id)
);


-- =========================================================
-- PRODUCT HIERARCHY
-- PRODUCT -> CATEGORY
-- =========================================================

CREATE TABLE dim_category (
    category_id      INTEGER PRIMARY KEY,
    category_name_pt VARCHAR NOT NULL,
    category_name_en VARCHAR
);

CREATE TABLE dim_product (
    product_id         VARCHAR PRIMARY KEY,
    category_id        INTEGER REFERENCES dim_category(category_id),
    weight_g            DOUBLE,
    length_cm           DOUBLE,
    height_cm           DOUBLE,
    width_cm            DOUBLE,
    photos_qty          INTEGER,
    name_length        INTEGER,
    description_length INTEGER
);


-- =========================================================
-- SELLER ACQUISITION
-- =========================================================

CREATE TABLE dim_seller_acquisition (
    acq_id           INTEGER PRIMARY KEY,
    lead_origin      VARCHAR,
    business_segment VARCHAR,
    won_date         DATE
);

CREATE TABLE dim_seller (
    seller_id  VARCHAR PRIMARY KEY,
    zip_prefix VARCHAR(5) REFERENCES dim_zip(zip_prefix),
    acq_id     INTEGER NOT NULL REFERENCES dim_seller_acquisition(acq_id)
);


-- =========================================================
-- CUSTOMER
-- =========================================================

CREATE TABLE dim_customer (
    customer_id        VARCHAR PRIMARY KEY,
    customer_unique_id VARCHAR,
    zip_prefix         VARCHAR(5) REFERENCES dim_zip(zip_prefix)
);


-- =========================================================
-- DATE DIMENSION
-- =========================================================

CREATE TABLE dim_date (
    date_id   INTEGER PRIMARY KEY,
    full_date DATE NOT NULL,
    year      INTEGER NOT NULL,
    quarter   INTEGER NOT NULL,
    month     INTEGER NOT NULL,
    day       INTEGER NOT NULL
);


-- =========================================================
-- PAYMENT TYPE
-- =========================================================

CREATE TABLE dim_payment_type (
    payment_type_id INTEGER PRIMARY KEY,
    payment_type    VARCHAR NOT NULL UNIQUE
);


-- =========================================================
-- FACT TABLE
-- Grain: one row per product in one order
-- =========================================================

CREATE TABLE fact_order_items (
    fact_id              INTEGER PRIMARY KEY,
    order_id             VARCHAR NOT NULL,
    order_item_id        INTEGER NOT NULL,

    product_id           VARCHAR REFERENCES dim_product(product_id),
    seller_id            VARCHAR REFERENCES dim_seller(seller_id),
    customer_id          VARCHAR REFERENCES dim_customer(customer_id),

    order_date_id        INTEGER REFERENCES dim_date(date_id),
    delivery_date_id     INTEGER REFERENCES dim_date(date_id),
    estimated_date_id    INTEGER REFERENCES dim_date(date_id),

    payment_type_id      INTEGER REFERENCES dim_payment_type(payment_type_id),

    price                DOUBLE,
    freight_value        DOUBLE,

    revenue              DOUBLE
        GENERATED ALWAYS AS (price + freight_value) VIRTUAL,

    review_score         INTEGER,
    payment_value        DOUBLE,
    payment_installments INTEGER,

    UNIQUE(order_id, order_item_id)
);