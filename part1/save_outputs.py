import duckdb

con = duckdb.connect("olist.duckdb")

sql = open("sql/03_queries.sql").read()

queries = [q.strip() for q in sql.split(";") if q.strip()]

for i, query in enumerate(queries, 1):
    output = f"outputs/Q{i}.csv"
    con.execute(
        f"COPY ({query}) TO '{output}' (HEADER, DELIMITER ',')"
    )
    print(f"Q{i} saved -> {output}")

con.close()
