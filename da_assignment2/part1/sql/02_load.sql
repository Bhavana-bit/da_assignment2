-- Data Analytics I — Assignment 2, Part 1
-- ETL: Raw CSVs -> Snowflake Schema


-- =========================================================
-- STAGING TABLES
-- =========================================================

CREATE OR REPLACE TABLE stg_orders AS
SELECT * FROM read_csv_auto('data/orders.csv');

CREATE OR REPLACE TABLE stg_order_items AS
SELECT * FROM read_csv_auto('data/order_items.csv');

CREATE OR REPLACE TABLE stg_order_payments AS
SELECT * FROM read_csv_auto('data/order_payments.csv');

CREATE OR REPLACE TABLE stg_order_reviews AS
SELECT * FROM read_csv_auto('data/order_reviews.csv');

CREATE OR REPLACE TABLE stg_customers AS
SELECT * FROM read_csv_auto('data/customers.csv');

CREATE OR REPLACE TABLE stg_sellers AS
SELECT * FROM read_csv_auto('data/sellers.csv');

CREATE OR REPLACE TABLE stg_products AS
SELECT * FROM read_csv_auto('data/products.csv');

CREATE OR REPLACE TABLE stg_geolocation AS
SELECT * FROM read_csv_auto('data/geolocation.csv');

CREATE OR REPLACE TABLE stg_categories AS
SELECT * FROM read_csv_auto('data/categories.csv');

CREATE OR REPLACE TABLE stg_leads AS
SELECT * FROM read_csv_auto('data/leads.csv');

CREATE OR REPLACE TABLE stg_closed_deals AS
SELECT * FROM read_csv_auto('data/closed_deals.csv');


-- =========================================================
-- GEOGRAPHY
-- Region -> State -> City -> ZIP
-- =========================================================

INSERT INTO dim_region (region_id, region_name) VALUES
    (1, 'North'),
    (2, 'Northeast'),
    (3, 'Central-West'),
    (4, 'Southeast'),
    (5, 'South');


INSERT INTO dim_state (state_id, state_abbr, region_id) VALUES
    (1, 'AC', 1),
    (2, 'AM', 1),
    (3, 'AP', 1),
    (4, 'PA', 1),
    (5, 'RO', 1),
    (6, 'RR', 1),
    (7, 'TO', 1),

    (8, 'AL', 2),
    (9, 'BA', 2),
    (10, 'CE', 2),
    (11, 'MA', 2),
    (12, 'PB', 2),
    (13, 'PE', 2),
    (14, 'PI', 2),
    (15, 'RN', 2),
    (16, 'SE', 2),

    (17, 'DF', 3),
    (18, 'GO', 3),
    (19, 'MS', 3),
    (20, 'MT', 3),

    (21, 'ES', 4),
    (22, 'MG', 4),
    (23, 'RJ', 4),
    (24, 'SP', 4),

    (25, 'PR', 5),
    (26, 'RS', 5),
    (27, 'SC', 5);


CREATE OR REPLACE SEQUENCE seq_city START 1;


INSERT INTO dim_city (
    city_id,
    city_name,
    state_id
)
SELECT
    nextval('seq_city'),
    lower(trim(g.geolocation_city)),
    s.state_id
FROM (
    SELECT DISTINCT
        lower(trim(geolocation_city)) AS geolocation_city,
        upper(trim(geolocation_state)) AS geolocation_state
    FROM stg_geolocation
    WHERE geolocation_city IS NOT NULL
      AND geolocation_state IS NOT NULL
) g
JOIN dim_state s
    ON s.state_abbr = g.geolocation_state;


INSERT INTO dim_zip (
    zip_prefix,
    city_id
)
SELECT
    lpad(
        CAST(g.geolocation_zip_code_prefix AS VARCHAR),
        5,
        '0'
    ),
    c.city_id
FROM (
    SELECT DISTINCT
        geolocation_zip_code_prefix,
        lower(trim(geolocation_city)) AS geolocation_city,
        upper(trim(geolocation_state)) AS geolocation_state
    FROM stg_geolocation
    WHERE geolocation_zip_code_prefix IS NOT NULL
) g
JOIN dim_state s
    ON s.state_abbr = g.geolocation_state
JOIN dim_city c
    ON c.city_name = g.geolocation_city
   AND c.state_id = s.state_id
QUALIFY ROW_NUMBER() OVER (
    PARTITION BY
        lpad(
            CAST(g.geolocation_zip_code_prefix AS VARCHAR),
            5,
            '0'
        )
    ORDER BY c.city_id
) = 1;


-- =========================================================
-- PRODUCT / CATEGORY
-- =========================================================

CREATE OR REPLACE SEQUENCE seq_cat START 1;


INSERT INTO dim_category (
    category_id,
    category_name_pt,
    category_name_en
)
SELECT
    nextval('seq_cat'),
    p.product_category_name,
    t.product_category_name_english
FROM (
    SELECT DISTINCT
        product_category_name
    FROM stg_products
    WHERE product_category_name IS NOT NULL
) p
LEFT JOIN stg_categories t
    ON p.product_category_name = t.product_category_name;


INSERT INTO dim_product (
    product_id,
    category_id,
    weight_g,
    length_cm,
    height_cm,
    width_cm,
    photos_qty,
    name_length,
    description_length
)
SELECT
    p.product_id,
    c.category_id,
    p.product_weight_g,
    p.product_length_cm,
    p.product_height_cm,
    p.product_width_cm,
    p.product_photos_qty,
    p.product_name_lenght,
    p.product_description_lenght
FROM stg_products p
LEFT JOIN dim_category c
    ON p.product_category_name = c.category_name_pt;


-- =========================================================
-- SELLER ACQUISITION
-- =========================================================

CREATE OR REPLACE TABLE tmp_seller_acq AS
WITH ranked_deals AS (
    SELECT
        cd.seller_id,

        COALESCE(l.origin, 'unknown') AS lead_origin,

        COALESCE(
            cd.business_segment,
            'unknown'
        ) AS business_segment,

        TRY_CAST(cd.won_date AS DATE) AS won_date,

        ROW_NUMBER() OVER (
            PARTITION BY cd.seller_id
            ORDER BY
                TRY_CAST(cd.won_date AS DATE) ASC NULLS LAST
        ) AS rn

    FROM stg_closed_deals cd

    LEFT JOIN stg_leads l
        ON cd.mql_id = l.mql_id
),

seller_acq AS (
    SELECT
        seller_id,
        lead_origin,
        business_segment,
        won_date
    FROM ranked_deals
    WHERE rn = 1
),

all_sellers AS (
    SELECT
        s.seller_id,

        COALESCE(
            a.lead_origin,
            'unknown'
        ) AS lead_origin,

        COALESCE(
            a.business_segment,
            'unknown'
        ) AS business_segment,

        a.won_date

    FROM stg_sellers s

    LEFT JOIN seller_acq a
        ON s.seller_id = a.seller_id
)

SELECT
    ROW_NUMBER() OVER (
        ORDER BY seller_id
    ) AS acq_id,

    seller_id,
    lead_origin,
    business_segment,
    won_date

FROM all_sellers;


INSERT INTO dim_seller_acquisition (
    acq_id,
    lead_origin,
    business_segment,
    won_date
)
SELECT
    acq_id,
    lead_origin,
    business_segment,
    won_date
FROM tmp_seller_acq;


INSERT INTO dim_seller (
    seller_id,
    zip_prefix,
    acq_id
)
SELECT
    s.seller_id,
    dz.zip_prefix,
    a.acq_id

FROM stg_sellers s

JOIN tmp_seller_acq a
    ON s.seller_id = a.seller_id

LEFT JOIN dim_zip dz
    ON lpad(
        CAST(s.seller_zip_code_prefix AS VARCHAR),
        5,
        '0'
    ) = dz.zip_prefix;


-- =========================================================
-- CUSTOMER
-- =========================================================

INSERT INTO dim_customer (
    customer_id,
    customer_unique_id,
    zip_prefix
)
SELECT
    c.customer_id,
    c.customer_unique_id,
    dz.zip_prefix

FROM stg_customers c

LEFT JOIN dim_zip dz
    ON lpad(
        CAST(c.customer_zip_code_prefix AS VARCHAR),
        5,
        '0'
    ) = dz.zip_prefix;


-- =========================================================
-- DATE DIMENSION
-- =========================================================

INSERT INTO dim_date (
    date_id,
    full_date,
    year,
    quarter,
    month,
    day
)
SELECT DISTINCT

    CAST(
        strftime(d, '%Y%m%d')
        AS INTEGER
    ),

    d,

    YEAR(d),
    QUARTER(d),
    MONTH(d),
    DAY(d)

FROM (
    SELECT
        TRY_CAST(
            order_purchase_timestamp AS DATE
        ) AS d
    FROM stg_orders

    UNION

    SELECT
        TRY_CAST(
            order_delivered_customer_date AS DATE
        )
    FROM stg_orders

    UNION

    SELECT
        TRY_CAST(
            order_estimated_delivery_date AS DATE
        )
    FROM stg_orders
) dates

WHERE d IS NOT NULL;


-- =========================================================
-- PAYMENT TYPE
-- =========================================================

CREATE OR REPLACE SEQUENCE seq_ptype START 1;


INSERT INTO dim_payment_type (
    payment_type_id,
    payment_type
)
SELECT
    nextval('seq_ptype'),
    payment_type

FROM (
    SELECT DISTINCT
        payment_type
    FROM stg_order_payments
    WHERE payment_type IS NOT NULL
);


-- =========================================================
-- REVIEWS
-- Keep one review per order
-- =========================================================

CREATE OR REPLACE TABLE tmp_reviews AS
SELECT
    order_id,
    review_score

FROM stg_order_reviews

QUALIFY ROW_NUMBER() OVER (
    PARTITION BY order_id
    ORDER BY review_creation_date DESC
) = 1;


-- =========================================================
-- PAYMENTS
-- Aggregate payment information at order level
-- =========================================================

CREATE OR REPLACE TABLE tmp_payments AS
SELECT
    order_id,

    SUM(payment_value) AS payment_value,

    MAX(payment_installments)
        AS payment_installments,

    FIRST(
        payment_type
        ORDER BY payment_value DESC
    ) AS payment_type

FROM stg_order_payments

GROUP BY order_id;


-- =========================================================
-- FACT TABLE
-- =========================================================

CREATE OR REPLACE SEQUENCE seq_fact START 1;


INSERT INTO fact_order_items (
    fact_id,
    order_id,
    order_item_id,
    product_id,
    seller_id,
    customer_id,
    order_date_id,
    delivery_date_id,
    estimated_date_id,
    payment_type_id,
    price,
    freight_value,
    review_score,
    payment_value,
    payment_installments
)

SELECT

    nextval('seq_fact'),

    oi.order_id,
    oi.order_item_id,

    oi.product_id,
    oi.seller_id,
    o.customer_id,

    CAST(
        strftime(
            TRY_CAST(
                o.order_purchase_timestamp AS DATE
            ),
            '%Y%m%d'
        ) AS INTEGER
    ),

    CASE
        WHEN TRY_CAST(
            o.order_delivered_customer_date AS DATE
        ) IS NOT NULL

        THEN CAST(
            strftime(
                TRY_CAST(
                    o.order_delivered_customer_date AS DATE
                ),
                '%Y%m%d'
            ) AS INTEGER
        )
    END,

    CAST(
        strftime(
            TRY_CAST(
                o.order_estimated_delivery_date AS DATE
            ),
            '%Y%m%d'
        ) AS INTEGER
    ),

    pt.payment_type_id,

    oi.price,
    oi.freight_value,

    r.review_score,

    tp.payment_value,
    tp.payment_installments

FROM stg_order_items oi

JOIN stg_orders o
    ON oi.order_id = o.order_id

LEFT JOIN tmp_reviews r
    ON o.order_id = r.order_id

LEFT JOIN tmp_payments tp
    ON o.order_id = tp.order_id

LEFT JOIN dim_payment_type pt
    ON tp.payment_type = pt.payment_type;


-- =========================================================
-- CLEANUP
-- =========================================================

DROP TABLE IF EXISTS tmp_seller_acq;
DROP TABLE IF EXISTS tmp_reviews;
DROP TABLE IF EXISTS tmp_payments;