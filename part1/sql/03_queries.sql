-- Data Analytics I — Assignment 2, Part 1
-- Task 3: OLAP Queries
-- Revenue = price + freight_value


-- =========================================================
-- Q1. Revenue: Year -> Quarter -> Month
-- =========================================================

SELECT
    d.year,
    d.quarter,
    d.month,

    SUM(f.revenue) AS total_revenue,

    COUNT(DISTINCT f.order_id) AS num_orders

FROM fact_order_items f

JOIN dim_date d
    ON f.order_date_id = d.date_id

GROUP BY ROLLUP(
    d.year,
    d.quarter,
    d.month
)

ORDER BY
    d.year NULLS LAST,
    d.quarter NULLS LAST,
    d.month NULLS LAST;


-- =========================================================
-- Q2. Month with highest revenue in each year
-- =========================================================

WITH monthly AS (

    SELECT
        d.year,
        d.month,
        SUM(f.revenue) AS total_revenue

    FROM fact_order_items f

    JOIN dim_date d
        ON f.order_date_id = d.date_id

    GROUP BY
        d.year,
        d.month
),

ranked AS (

    SELECT
        year,
        month,
        total_revenue,

        RANK() OVER (
            PARTITION BY year
            ORDER BY total_revenue DESC
        ) AS rnk

    FROM monthly
)

SELECT
    year,
    month,
    total_revenue

FROM ranked

WHERE rnk = 1

ORDER BY year;


-- =========================================================
-- Q3. Revenue by product category
-- =========================================================

SELECT
    c.category_name_en,

    SUM(f.revenue) AS total_revenue,

    COUNT(DISTINCT f.order_id) AS num_orders

FROM fact_order_items f

JOIN dim_product p
    ON f.product_id = p.product_id

JOIN dim_category c
    ON p.category_id = c.category_id

GROUP BY c.category_name_en

ORDER BY total_revenue DESC;


-- =========================================================
-- Q4. Drill-down: Category -> Product
-- =========================================================

SELECT
    c.category_name_en,

    f.product_id,

    SUM(f.revenue) AS total_revenue,

    COUNT(DISTINCT f.order_id) AS num_orders,

    GROUPING(f.product_id)
        AS is_category_subtotal

FROM fact_order_items f

JOIN dim_product p
    ON f.product_id = p.product_id

JOIN dim_category c
    ON p.category_id = c.category_id

GROUP BY GROUPING SETS (

    (c.category_name_en),

    (
        c.category_name_en,
        f.product_id
    )
)

ORDER BY
    c.category_name_en,
    is_category_subtotal DESC,
    total_revenue DESC;


-- =========================================================
-- Q5. Roll-up: City -> State -> Region
-- =========================================================

SELECT

    r.region_name,
    s.state_abbr,
    c.city_name,

    SUM(f.revenue) AS total_revenue,

    COUNT(DISTINCT f.order_id) AS num_orders

FROM fact_order_items f

JOIN dim_customer cu
    ON f.customer_id = cu.customer_id

JOIN dim_zip z
    ON cu.zip_prefix = z.zip_prefix

JOIN dim_city c
    ON z.city_id = c.city_id

JOIN dim_state s
    ON c.state_id = s.state_id

JOIN dim_region r
    ON s.region_id = r.region_id

GROUP BY ROLLUP(
    r.region_name,
    s.state_abbr,
    c.city_name
)

ORDER BY
    total_revenue DESC NULLS LAST;


-- =========================================================
-- Q6. Top 5 customers by total purchase
-- =========================================================

SELECT

    cu.customer_unique_id,

    SUM(f.revenue) AS total_spent,

    COUNT(DISTINCT f.order_id) AS num_orders

FROM fact_order_items f

JOIN dim_customer cu
    ON f.customer_id = cu.customer_id

GROUP BY cu.customer_unique_id

ORDER BY total_spent DESC

LIMIT 5;


-- =========================================================
-- Q7. Highest revenue seller within each state
-- =========================================================

WITH seller_state AS (

    SELECT

        f.seller_id,

        s.state_abbr,

        SUM(f.revenue) AS total_revenue

    FROM fact_order_items f

    JOIN dim_seller sel
        ON f.seller_id = sel.seller_id

    JOIN dim_zip z
        ON sel.zip_prefix = z.zip_prefix

    JOIN dim_city c
        ON z.city_id = c.city_id

    JOIN dim_state s
        ON c.state_id = s.state_id

    GROUP BY
        f.seller_id,
        s.state_abbr
),

ranked AS (

    SELECT

        seller_id,
        state_abbr,
        total_revenue,

        RANK() OVER (
            PARTITION BY state_abbr
            ORDER BY total_revenue DESC
        ) AS rnk

    FROM seller_state
)

SELECT
    seller_id,
    state_abbr,
    total_revenue

FROM ranked

WHERE rnk = 1

ORDER BY total_revenue DESC;


-- =========================================================
-- Q8. CUBE: Region x Category x Year
-- =========================================================

SELECT

    r.region_name,
    c.category_name_en,
    d.year,

    SUM(f.revenue) AS total_revenue,

    COUNT(DISTINCT f.order_id) AS num_orders,

    GROUPING(r.region_name) AS grp_region,

    GROUPING(c.category_name_en) AS grp_category,

    GROUPING(d.year) AS grp_year

FROM fact_order_items f

JOIN dim_date d
    ON f.order_date_id = d.date_id

JOIN dim_product p
    ON f.product_id = p.product_id

JOIN dim_category c
    ON p.category_id = c.category_id

JOIN dim_customer cu
    ON f.customer_id = cu.customer_id

JOIN dim_zip z
    ON cu.zip_prefix = z.zip_prefix

JOIN dim_city ci
    ON z.city_id = ci.city_id

JOIN dim_state s
    ON ci.state_id = s.state_id

JOIN dim_region r
    ON s.region_id = r.region_id

GROUP BY CUBE(
    r.region_name,
    c.category_name_en,
    d.year
)

ORDER BY
    grp_region,
    grp_category,
    grp_year,
    r.region_name,
    c.category_name_en,
    d.year;


-- =========================================================
-- Q9. Average review score:
-- Early / On Time / Late
-- =========================================================

WITH order_level AS (

    SELECT

        order_id,

        MAX(review_score) AS review_score,

        MAX(delivery_date_id)
            AS delivery_date_id,

        MAX(estimated_date_id)
            AS estimated_date_id

    FROM fact_order_items

    WHERE review_score IS NOT NULL

    GROUP BY order_id
),

classified AS (

    SELECT

        order_id,
        review_score,

        CASE

            WHEN delivery_date_id < estimated_date_id
                THEN 'Early'

            WHEN delivery_date_id = estimated_date_id
                THEN 'On Time'

            WHEN delivery_date_id > estimated_date_id
                THEN 'Late'

        END AS delivery_status

    FROM order_level

    WHERE delivery_date_id IS NOT NULL
)

SELECT

    delivery_status,

    ROUND(
        AVG(review_score),
        3
    ) AS avg_review_score,

    COUNT(*) AS num_orders

FROM classified

GROUP BY delivery_status

ORDER BY avg_review_score DESC;


-- =========================================================
-- Q10. Lead origin generating highest seller revenue
-- =========================================================

SELECT
    a.lead_origin,
    SUM(f.revenue) AS total_revenue,
    COUNT(DISTINCT f.seller_id) AS num_sellers,
    ROUND(
        SUM(f.revenue) / COUNT(DISTINCT f.seller_id),
        2
    ) AS revenue_per_seller
FROM fact_order_items f
JOIN dim_seller sel
    ON f.seller_id = sel.seller_id
JOIN dim_seller_acquisition a
    ON sel.acq_id = a.acq_id
WHERE a.lead_origin <> 'unknown'
GROUP BY a.lead_origin
ORDER BY total_revenue DESC;