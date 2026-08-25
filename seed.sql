-- Sample schema: a small e-commerce-style dataset, so the MCP server
-- has something realistic to query, explain, and summarize.

CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    email VARCHAR(150) UNIQUE NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS products (
    id SERIAL PRIMARY KEY,
    name VARCHAR(150) NOT NULL,
    price NUMERIC(10,2) NOT NULL,
    category VARCHAR(50)
);

CREATE TABLE IF NOT EXISTS orders (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id),
    product_id INTEGER REFERENCES products(id),
    quantity INTEGER NOT NULL DEFAULT 1,
    order_date TIMESTAMP DEFAULT NOW(),
    status VARCHAR(20) DEFAULT 'completed'
);

CREATE INDEX IF NOT EXISTS idx_orders_user_id ON orders(user_id);
CREATE INDEX IF NOT EXISTS idx_orders_order_date ON orders(order_date);

-- Seed data
INSERT INTO users (name, email)
SELECT 'User ' || i, 'user' || i || '@example.com'
FROM generate_series(1, 200) AS i
ON CONFLICT DO NOTHING;

INSERT INTO products (name, price, category)
SELECT 'Product ' || i, (random() * 100 + 5)::numeric(10,2),
       (ARRAY['electronics','books','clothing','home','toys'])[floor(random()*5+1)]
FROM generate_series(1, 50) AS i
ON CONFLICT DO NOTHING;

INSERT INTO orders (user_id, product_id, quantity, order_date, status)
SELECT
    (floor(random() * 200) + 1)::int,
    (floor(random() * 50) + 1)::int,
    (floor(random() * 5) + 1)::int,
    NOW() - (random() * interval '90 days'),
    (ARRAY['completed','pending','cancelled'])[floor(random()*3+1)]
FROM generate_series(1, 2000) AS i;
