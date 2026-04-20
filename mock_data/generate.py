"""
Generate mock data files for testing ETL Studio.

Usage:
    python mock_data/generate.py

Produces:
    mock_data/customers.csv
    mock_data/orders.csv
    mock_data/products.xlsx   (2 sheets: products, categories)
    mock_data/inventory.sql   (CREATE + INSERT statements)

The data has intentional quality issues for testing validation:
    - Duplicate rows in customers
    - Mixed encodings / mojibake in product names
    - Null-ish values (NULL, N/A, empty strings)
    - Long strings that trigger truncation warnings
    - Mixed numeric formats (commas in numbers)
"""

import csv
import os
import random
import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
random.seed(42)


def _date(days_ago_max=1000):
    d = datetime.date.today() - datetime.timedelta(days=random.randint(0, days_ago_max))
    return d.isoformat()


# ── Customers CSV ──────────────────────────────────────────────────
def gen_customers():
    path = os.path.join(SCRIPT_DIR, "customers.csv")
    first_names = [
        "Alice",
        "Bob",
        "Carla",
        "David",
        "Elena",
        "Fadi",
        "Gina",
        "Hassan",
        "Ivy",
        "James",
        "Kara",
        "Liam",
        "Mona",
        "Nour",
        "Oscar",
        "Petra",
        "Qasim",
        "Rosa",
        "Sami",
        "Tina",
    ]
    last_names = [
        "Smith",
        "Johnson",
        "García",
        "Müller",
        "Tanaka",
        "Al-Rashid",
        "Öztürk",
        "Björk",
        "Nguyen",
        "Kowalski",
        "Chen",
        "Fernández",
        "Ivanov",
        "Kim",
        "Santos",
    ]
    cities = [
        "New York",
        "Berlin",
        "Tokyo",
        "Istanbul",
        "São Paulo",
        "London",
        "Dubai",
        "Sydney",
        "Toronto",
        "Stockholm",
    ]

    rows = []
    for i in range(1, 51):
        rows.append(
            {
                "id": i,
                "first_name": random.choice(first_names),
                "last_name": random.choice(last_names),
                "email": f"user{i}@example.com",
                "city": random.choice(cities),
                "signup_date": _date(800),
                "lifetime_value": f"{random.uniform(50, 5000):.2f}",
                "status": random.choice(
                    ["active", "inactive", "N/A", "NULL", ""]
                ),  # intentional null-ish
            }
        )

    # Intentional duplicates (rows 3 and 7 repeated)
    rows.append(dict(rows[2]))
    rows.append(dict(rows[6]))

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    print(f"  {path} ({len(rows)} rows)")


# ── Orders CSV ─────────────────────────────────────────────────────
def gen_orders():
    path = os.path.join(SCRIPT_DIR, "orders.csv")
    rows = []
    for i in range(1, 201):
        qty = random.randint(1, 20)
        unit_price = round(random.uniform(5, 500), 2)
        rows.append(
            {
                "order_id": i,
                "customer_id": random.randint(1, 50),
                "product_id": random.randint(1, 30),
                "quantity": qty,
                "unit_price": f"{unit_price:,.2f}"
                if random.random() > 0.7
                else str(unit_price),  # mixed formats
                "total": f"{qty * unit_price:.2f}",
                "order_date": _date(400),
                "shipped": random.choice(
                    ["true", "false", "yes", "no", "1", "0"]
                ),  # mixed booleans
            }
        )

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    print(f"  {path} ({len(rows)} rows)")


# ── Products XLSX (2 sheets) ──────────────────────────────────────
def gen_products():
    try:
        import openpyxl
    except ImportError:
        print("  SKIP products.xlsx (openpyxl not installed)")
        return

    path = os.path.join(SCRIPT_DIR, "products.xlsx")
    wb = openpyxl.Workbook()

    # Sheet 1: products
    ws1 = wb.active
    ws1.title = "products"
    headers1 = [
        "product_id",
        "name",
        "category_id",
        "price",
        "weight_kg",
        "description",
    ]
    ws1.append(headers1)

    names_clean = [
        "Widget",
        "Gadget",
        "Sprocket",
        "Doohickey",
        "Thingamajig",
        "Gizmo",
        "Contraption",
        "Apparatus",
        "Device",
        "Module",
    ]
    adjectives = [
        "Turbo",
        "Mega",
        "Ultra",
        "Nano",
        "Quantum",
        "Hyper",
        "Micro",
        "Pro",
        "Elite",
        "Prime",
    ]

    for i in range(1, 31):
        name = f"{random.choice(adjectives)} {random.choice(names_clean)} {i}"
        # Intentional mojibake on some rows
        if i in (5, 12, 23):
            name = name.encode("utf-8").decode("latin-1", errors="replace")
        desc = f"Product description for item {i}."
        # A few long descriptions to trigger truncation warnings
        if i in (8, 19):
            desc = "A" * 300 + f" (product {i})"
        ws1.append(
            [
                i,
                name,
                random.randint(1, 6),
                round(random.uniform(5, 999), 2),
                round(random.uniform(0.1, 50), 2) if random.random() > 0.1 else None,
                desc,
            ]
        )

    # Sheet 2: categories
    ws2 = wb.create_sheet("categories")
    headers2 = ["category_id", "category_name", "active"]
    ws2.append(headers2)
    cats = ["Electronics", "Clothing", "Home & Garden", "Sports", "Books", "Toys"]
    for i, cat in enumerate(cats, 1):
        ws2.append([i, cat, random.choice([True, False])])

    wb.save(path)
    print(f"  {path} (products: 30 rows, categories: {len(cats)} rows)")


# ── Inventory SQL dump ─────────────────────────────────────────────
def gen_inventory_sql():
    path = os.path.join(SCRIPT_DIR, "inventory.sql")
    lines = [
        "-- Mock inventory data for ETL Studio testing",
        "",
        "CREATE TABLE warehouses (",
        "    warehouse_id INT PRIMARY KEY,",
        "    name VARCHAR(100),",
        "    city VARCHAR(50),",
        "    capacity INT",
        ");",
        "",
        "CREATE TABLE stock (",
        "    stock_id INT PRIMARY KEY,",
        "    warehouse_id INT,",
        "    product_id INT,",
        "    quantity INT,",
        "    last_updated DATE",
        ");",
        "",
    ]

    warehouses = [
        (1, "Main Warehouse", "New York", 10000),
        (2, "West Coast Hub", "Los Angeles", 7500),
        (3, "Europe Central", "Berlin", 5000),
        (4, "Asia Pacific", "Tokyo", 8000),
    ]
    for wid, name, city, cap in warehouses:
        lines.append(
            f"INSERT INTO warehouses (warehouse_id, name, city, capacity) VALUES ({wid}, '{name}', '{city}', {cap});"
        )

    lines.append("")

    for sid in range(1, 61):
        wid = random.choice([1, 2, 3, 4])
        pid = random.randint(1, 30)
        qty = random.randint(0, 500)
        date = _date(200)
        lines.append(
            f"INSERT INTO stock (stock_id, warehouse_id, product_id, quantity, last_updated) VALUES ({sid}, {wid}, {pid}, {qty}, '{date}');"
        )

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"  {path} (warehouses: 4, stock: 60 rows)")


# ── Main ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("Generating mock data:")
    gen_customers()
    gen_orders()
    gen_products()
    gen_inventory_sql()
    print("\nDone! Upload these files to ETL Studio to test the pipeline.")
