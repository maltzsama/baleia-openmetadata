"""A Baleia semantic catalog as the gateway returns it (contract version 1)."""

MODEL = {
    "id": "m1",
    "slug": "orders",
    "label": "Orders",
    "description": "Orders exposed to external catalogs.",
    "url": "https://baleia.example/models/m1",
    "updated_at": "2026-11-24T00:00:00Z",
    "source": {"kind": "table", "table": "e2e_tpch.tiny.orders"},
    "columns": [
        {"name": "orderkey", "type": "int64"},
        {
            "name": "order_status",
            "label": "Order status",
            "type": "string",
            "expression": "orderstatus",
        },
        {"name": "payload", "type": "geometry"},
    ],
    "metrics": [
        {
            "name": "order_count",
            "label": "Orders",
            "sql": 'SELECT COUNT(*) AS "order_count" FROM "e2e_tpch"."tiny"."orders" "orders"',
        },
        {"name": "orderkey", "label": "Shadowed by a dimension"},
    ],
    "source_tables": ["e2e_tpch.tiny.orders"],
}

SQL_MODEL = {
    "id": "m2",
    "slug": "big_orders",
    "label": "",
    "updated_at": "2026-11-24T00:00:00Z",
    "source": {"kind": "sql", "sql": " SELECT * FROM tiny.orders WHERE totalprice > 1000 "},
    "columns": [],
    "metrics": [],
    "source_tables": ["e2e_tpch.tiny.orders"],
}

METRIC = {
    "id": "x1",
    "slug": "order_count",
    "label": "Order count",
    "description": "Orders, counted.",
    "url": "https://baleia.example/metrics/x1",
    "updated_at": "2026-11-24T00:00:00Z",
    "sql": 'SELECT COUNT(*) AS "order_count" FROM "e2e_tpch"."tiny"."orders"',
    "source_tables": ["e2e_tpch.tiny.orders"],
}

UNRENDERED_METRIC = {
    "id": "x2",
    "slug": "elsewhere",
    "label": "Elsewhere",
    "updated_at": "2026-11-24T00:00:00Z",
    "source_tables": [],
}
