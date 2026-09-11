import duckdb
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from collections import defaultdict

# =========================================================
# CONNECT TO EXISTING DUCKDB DATABASE
# =========================================================

con = duckdb.connect("olist.duckdb", read_only=True)

# =========================================================
# GET TABLES
# Ignore staging tables because the ER diagram should show
# the final Snowflake schema only.
# =========================================================

tables = con.execute("""
    SELECT table_name
    FROM information_schema.tables
    WHERE table_schema = 'main'
      AND table_name NOT LIKE 'stg_%'
    ORDER BY table_name
""").fetchall()

table_names = [row[0] for row in tables]

# =========================================================
# GET COLUMNS
# =========================================================

column_rows = con.execute("""
    SELECT
        table_name,
        column_name,
        data_type,
        ordinal_position
    FROM information_schema.columns
    WHERE table_schema = 'main'
      AND table_name NOT LIKE 'stg_%'
    ORDER BY table_name, ordinal_position
""").fetchall()

schema = defaultdict(list)

for table, column, dtype, position in column_rows:
    schema[table].append((column, dtype))

# =========================================================
# GET PRIMARY KEYS
# =========================================================

pk_rows = con.execute("""
    SELECT
        tc.table_name,
        kcu.column_name
    FROM information_schema.table_constraints tc
    JOIN information_schema.key_column_usage kcu
        ON tc.constraint_name = kcu.constraint_name
       AND tc.table_schema = kcu.table_schema
    WHERE tc.table_schema = 'main'
      AND tc.constraint_type = 'PRIMARY KEY'
""").fetchall()

primary_keys = set(
    (table, column)
    for table, column in pk_rows
)

# =========================================================
# GET FOREIGN KEYS
# =========================================================

fk_rows = con.execute("""
    SELECT
        kcu.table_name,
        kcu.column_name,
        ccu.table_name AS referenced_table,
        ccu.column_name AS referenced_column
    FROM information_schema.key_column_usage kcu
    JOIN information_schema.referential_constraints rc
        ON kcu.constraint_name = rc.constraint_name
       AND kcu.constraint_schema = rc.constraint_schema
    JOIN information_schema.constraint_column_usage ccu
        ON rc.unique_constraint_name = ccu.constraint_name
       AND rc.unique_constraint_schema = ccu.constraint_schema
    WHERE kcu.table_schema = 'main'
""").fetchall()

foreign_keys = [
    (src_table, src_column, ref_table, ref_column)
    for src_table, src_column, ref_table, ref_column in fk_rows
]

con.close()

# =========================================================
# LAYOUT
# =========================================================

positions = {
    "dim_region":             (0.05, 0.86),
    "dim_state":              (0.05, 0.67),
    "dim_city":               (0.05, 0.48),
    "dim_zip":                (0.05, 0.29),

    "dim_category":           (0.38, 0.86),
    "dim_product":            (0.38, 0.65),

    "dim_seller_acquisition": (0.70, 0.86),
    "dim_seller":             (0.70, 0.64),

    "dim_customer":           (0.70, 0.39),

    "dim_date":               (0.38, 0.27),
    "dim_payment_type":       (0.70, 0.18),

    "fact_order_items":       (0.38, 0.48),
}

# =========================================================
# DRAWING SETTINGS
# =========================================================

fig, ax = plt.subplots(figsize=(20, 14))

ax.set_xlim(0, 1)
ax.set_ylim(0, 1)
ax.axis("off")

BOX_WIDTH = 0.22
HEADER_HEIGHT = 0.045
ROW_HEIGHT = 0.025

box_positions = {}

# =========================================================
# DRAW TABLES
# =========================================================

for table in table_names:

    if table not in positions:
        continue

    x, y = positions[table]

    columns = schema[table]

    total_height = HEADER_HEIGHT + (
        len(columns) * ROW_HEIGHT
    ) + 0.015

    is_fact = table == "fact_order_items"

    header_color = "#C0392B" if is_fact else "#2471A3"
    body_color = "#FDECEA" if is_fact else "#EAF4FB"

    # Header
    header = patches.FancyBboxPatch(
        (x, y),
        BOX_WIDTH,
        HEADER_HEIGHT,
        boxstyle="round,pad=0.004",
        facecolor=header_color,
        edgecolor="black",
        linewidth=1.2
    )

    ax.add_patch(header)

    ax.text(
        x + BOX_WIDTH / 2,
        y + HEADER_HEIGHT / 2,
        table,
        ha="center",
        va="center",
        fontsize=9,
        fontweight="bold",
        color="white"
    )

    # Body
    body_height = len(columns) * ROW_HEIGHT + 0.015

    body = patches.FancyBboxPatch(
        (x, y - body_height),
        BOX_WIDTH,
        body_height,
        boxstyle="round,pad=0.004",
        facecolor=body_color,
        edgecolor="black",
        linewidth=1.0
    )

    ax.add_patch(body)

    # Columns
    for i, (column, dtype) in enumerate(columns):

        cy = y - 0.015 - (i + 0.5) * ROW_HEIGHT

        if (table, column) in primary_keys:
            marker = "PK"
        elif any(
            fk[0] == table and fk[1] == column
            for fk in foreign_keys
        ):
            marker = "FK"
        else:
            marker = ""

        label = f"{marker}  {column}" if marker else column

        ax.text(
            x + 0.008,
            cy,
            label,
            ha="left",
            va="center",
            fontsize=7
        )

        short_dtype = (
            dtype
            .replace("CHARACTER VARYING", "VARCHAR")
            .replace("DOUBLE PRECISION", "DOUBLE")
        )

        ax.text(
            x + BOX_WIDTH - 0.008,
            cy,
            short_dtype,
            ha="right",
            va="center",
            fontsize=6,
            color="#555555"
        )

    box_positions[table] = (
        x,
        y - body_height,
        BOX_WIDTH,
        total_height
    )

# =========================================================
# DRAW FOREIGN KEY RELATIONSHIPS
# =========================================================

for (
    src_table,
    src_column,
    ref_table,
    ref_column
) in foreign_keys:

    if (
        src_table not in box_positions
        or ref_table not in box_positions
    ):
        continue

    sx, sy, sw, sh = box_positions[src_table]
    rx, ry, rw, rh = box_positions[ref_table]

    # Centers
    src_center_x = sx + sw / 2
    ref_center_x = rx + rw / 2

    src_center_y = sy + sh / 2
    ref_center_y = ry + rh / 2

    # Choose connection sides
    if src_center_x < ref_center_x:

        x1 = sx + sw
        y1 = src_center_y

        x2 = rx
        y2 = ref_center_y

    else:

        x1 = sx
        y1 = src_center_y

        x2 = rx + rw
        y2 = ref_center_y

    ax.annotate(
        "",
        xy=(x2, y2),
        xytext=(x1, y1),
        arrowprops=dict(
            arrowstyle="->",
            linewidth=1.2,
            color="#555555",
            connectionstyle="arc3,rad=0.08"
        )
    )

# =========================================================
# LEGEND
# =========================================================

fact_patch = patches.Patch(
    color="#C0392B",
    label="Fact Table"
)

dimension_patch = patches.Patch(
    color="#2471A3",
    label="Dimension Table"
)

ax.legend(
    handles=[
        fact_patch,
        dimension_patch
    ],
    loc="lower right",
    fontsize=9
)

# =========================================================
# TITLE
# =========================================================

ax.set_title(
    "Snowflake Schema – Olist E-Commerce Data Warehouse",
    fontsize=16,
    fontweight="bold",
    pad=15
)

# =========================================================
# SAVE
# =========================================================

output_file = "schema/snowflake_er_diagram.png"

plt.savefig(
    output_file,
    dpi=200,
    bbox_inches="tight"
)

plt.close()

print()
print("==========================================")
print("ER DIAGRAM CREATED SUCCESSFULLY")
print("==========================================")
print(f"Saved to: {output_file}")
print()
print("Tables included:")

for table in table_names:
    print(" -", table)

print()
print("Foreign-key relationships:", len(foreign_keys))
