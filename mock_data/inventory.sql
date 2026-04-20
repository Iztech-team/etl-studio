-- Mock inventory data for ETL Studio testing

CREATE TABLE warehouses (
    warehouse_id INT PRIMARY KEY,
    name VARCHAR(100),
    city VARCHAR(50),
    capacity INT
);

CREATE TABLE stock (
    stock_id INT PRIMARY KEY,
    warehouse_id INT,
    product_id INT,
    quantity INT,
    last_updated DATE
);

INSERT INTO warehouses (warehouse_id, name, city, capacity) VALUES (1, 'Main Warehouse', 'New York', 10000);
INSERT INTO warehouses (warehouse_id, name, city, capacity) VALUES (2, 'West Coast Hub', 'Los Angeles', 7500);
INSERT INTO warehouses (warehouse_id, name, city, capacity) VALUES (3, 'Europe Central', 'Berlin', 5000);
INSERT INTO warehouses (warehouse_id, name, city, capacity) VALUES (4, 'Asia Pacific', 'Tokyo', 8000);

INSERT INTO stock (stock_id, warehouse_id, product_id, quantity, last_updated) VALUES (1, 4, 9, 18, '2025-10-10');
INSERT INTO stock (stock_id, warehouse_id, product_id, quantity, last_updated) VALUES (2, 2, 10, 182, '2025-10-03');
INSERT INTO stock (stock_id, warehouse_id, product_id, quantity, last_updated) VALUES (3, 1, 28, 335, '2026-01-26');
INSERT INTO stock (stock_id, warehouse_id, product_id, quantity, last_updated) VALUES (4, 3, 4, 409, '2026-01-16');
INSERT INTO stock (stock_id, warehouse_id, product_id, quantity, last_updated) VALUES (5, 4, 29, 204, '2025-10-12');
INSERT INTO stock (stock_id, warehouse_id, product_id, quantity, last_updated) VALUES (6, 4, 29, 489, '2026-01-12');
INSERT INTO stock (stock_id, warehouse_id, product_id, quantity, last_updated) VALUES (7, 3, 6, 254, '2025-10-25');
INSERT INTO stock (stock_id, warehouse_id, product_id, quantity, last_updated) VALUES (8, 4, 12, 473, '2025-12-09');
INSERT INTO stock (stock_id, warehouse_id, product_id, quantity, last_updated) VALUES (9, 3, 26, 42, '2025-10-16');
INSERT INTO stock (stock_id, warehouse_id, product_id, quantity, last_updated) VALUES (10, 4, 3, 220, '2025-11-17');
INSERT INTO stock (stock_id, warehouse_id, product_id, quantity, last_updated) VALUES (11, 2, 18, 150, '2026-01-28');
INSERT INTO stock (stock_id, warehouse_id, product_id, quantity, last_updated) VALUES (12, 1, 3, 167, '2025-11-02');
INSERT INTO stock (stock_id, warehouse_id, product_id, quantity, last_updated) VALUES (13, 3, 10, 228, '2025-11-17');
INSERT INTO stock (stock_id, warehouse_id, product_id, quantity, last_updated) VALUES (14, 4, 6, 353, '2025-12-28');
INSERT INTO stock (stock_id, warehouse_id, product_id, quantity, last_updated) VALUES (15, 3, 15, 21, '2025-10-16');
INSERT INTO stock (stock_id, warehouse_id, product_id, quantity, last_updated) VALUES (16, 3, 20, 222, '2026-02-09');
INSERT INTO stock (stock_id, warehouse_id, product_id, quantity, last_updated) VALUES (17, 1, 3, 343, '2025-11-08');
INSERT INTO stock (stock_id, warehouse_id, product_id, quantity, last_updated) VALUES (18, 4, 12, 262, '2025-10-11');
INSERT INTO stock (stock_id, warehouse_id, product_id, quantity, last_updated) VALUES (19, 2, 1, 73, '2025-11-16');
INSERT INTO stock (stock_id, warehouse_id, product_id, quantity, last_updated) VALUES (20, 4, 2, 64, '2026-04-03');
INSERT INTO stock (stock_id, warehouse_id, product_id, quantity, last_updated) VALUES (21, 2, 25, 330, '2026-01-17');
INSERT INTO stock (stock_id, warehouse_id, product_id, quantity, last_updated) VALUES (22, 3, 13, 486, '2025-11-26');
INSERT INTO stock (stock_id, warehouse_id, product_id, quantity, last_updated) VALUES (23, 1, 20, 78, '2025-10-29');
INSERT INTO stock (stock_id, warehouse_id, product_id, quantity, last_updated) VALUES (24, 4, 12, 190, '2025-12-28');
INSERT INTO stock (stock_id, warehouse_id, product_id, quantity, last_updated) VALUES (25, 1, 19, 70, '2025-12-06');
INSERT INTO stock (stock_id, warehouse_id, product_id, quantity, last_updated) VALUES (26, 3, 13, 160, '2025-11-05');
INSERT INTO stock (stock_id, warehouse_id, product_id, quantity, last_updated) VALUES (27, 3, 8, 491, '2026-03-22');
INSERT INTO stock (stock_id, warehouse_id, product_id, quantity, last_updated) VALUES (28, 1, 24, 95, '2025-12-14');
INSERT INTO stock (stock_id, warehouse_id, product_id, quantity, last_updated) VALUES (29, 4, 30, 287, '2026-03-21');
INSERT INTO stock (stock_id, warehouse_id, product_id, quantity, last_updated) VALUES (30, 3, 25, 133, '2025-10-22');
INSERT INTO stock (stock_id, warehouse_id, product_id, quantity, last_updated) VALUES (31, 4, 7, 313, '2026-02-06');
INSERT INTO stock (stock_id, warehouse_id, product_id, quantity, last_updated) VALUES (32, 4, 7, 62, '2026-03-17');
INSERT INTO stock (stock_id, warehouse_id, product_id, quantity, last_updated) VALUES (33, 1, 15, 88, '2025-10-20');
INSERT INTO stock (stock_id, warehouse_id, product_id, quantity, last_updated) VALUES (34, 4, 3, 414, '2025-10-28');
INSERT INTO stock (stock_id, warehouse_id, product_id, quantity, last_updated) VALUES (35, 3, 22, 177, '2025-10-21');
INSERT INTO stock (stock_id, warehouse_id, product_id, quantity, last_updated) VALUES (36, 1, 18, 277, '2026-02-05');
INSERT INTO stock (stock_id, warehouse_id, product_id, quantity, last_updated) VALUES (37, 3, 28, 80, '2025-10-20');
INSERT INTO stock (stock_id, warehouse_id, product_id, quantity, last_updated) VALUES (38, 2, 26, 185, '2025-12-11');
INSERT INTO stock (stock_id, warehouse_id, product_id, quantity, last_updated) VALUES (39, 2, 4, 102, '2026-03-16');
INSERT INTO stock (stock_id, warehouse_id, product_id, quantity, last_updated) VALUES (40, 2, 26, 252, '2026-04-14');
INSERT INTO stock (stock_id, warehouse_id, product_id, quantity, last_updated) VALUES (41, 3, 18, 293, '2026-01-16');
INSERT INTO stock (stock_id, warehouse_id, product_id, quantity, last_updated) VALUES (42, 4, 26, 282, '2026-03-18');
INSERT INTO stock (stock_id, warehouse_id, product_id, quantity, last_updated) VALUES (43, 1, 3, 158, '2026-01-09');
INSERT INTO stock (stock_id, warehouse_id, product_id, quantity, last_updated) VALUES (44, 4, 17, 210, '2025-10-06');
INSERT INTO stock (stock_id, warehouse_id, product_id, quantity, last_updated) VALUES (45, 4, 27, 294, '2026-04-02');
INSERT INTO stock (stock_id, warehouse_id, product_id, quantity, last_updated) VALUES (46, 2, 11, 328, '2026-04-02');
INSERT INTO stock (stock_id, warehouse_id, product_id, quantity, last_updated) VALUES (47, 4, 15, 348, '2025-12-09');
INSERT INTO stock (stock_id, warehouse_id, product_id, quantity, last_updated) VALUES (48, 3, 5, 449, '2025-10-03');
INSERT INTO stock (stock_id, warehouse_id, product_id, quantity, last_updated) VALUES (49, 2, 25, 494, '2026-03-18');
INSERT INTO stock (stock_id, warehouse_id, product_id, quantity, last_updated) VALUES (50, 4, 17, 466, '2026-04-06');
INSERT INTO stock (stock_id, warehouse_id, product_id, quantity, last_updated) VALUES (51, 1, 17, 78, '2026-02-02');
INSERT INTO stock (stock_id, warehouse_id, product_id, quantity, last_updated) VALUES (52, 2, 6, 165, '2025-10-21');
INSERT INTO stock (stock_id, warehouse_id, product_id, quantity, last_updated) VALUES (53, 2, 12, 485, '2025-12-09');
INSERT INTO stock (stock_id, warehouse_id, product_id, quantity, last_updated) VALUES (54, 3, 28, 40, '2026-02-15');
INSERT INTO stock (stock_id, warehouse_id, product_id, quantity, last_updated) VALUES (55, 2, 21, 489, '2025-11-30');
INSERT INTO stock (stock_id, warehouse_id, product_id, quantity, last_updated) VALUES (56, 3, 5, 320, '2026-02-02');
INSERT INTO stock (stock_id, warehouse_id, product_id, quantity, last_updated) VALUES (57, 1, 17, 328, '2026-03-08');
INSERT INTO stock (stock_id, warehouse_id, product_id, quantity, last_updated) VALUES (58, 2, 6, 337, '2025-11-12');
INSERT INTO stock (stock_id, warehouse_id, product_id, quantity, last_updated) VALUES (59, 3, 27, 473, '2025-11-27');
INSERT INTO stock (stock_id, warehouse_id, product_id, quantity, last_updated) VALUES (60, 1, 27, 442, '2026-04-13');
