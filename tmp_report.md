# BlindSpot Report

**Summary:** 2 meaningful / 2 total findings — 4 services, 2 resources
Graph: 6 nodes (4 services, 2 resources), 4 edges
Generated: 2026-09-04T15:38:15Z

## 1. api ↔ worker through `shared-data` (named_volume) — confidence 0.92 **meaningful**

**Reason:** shared shared-data coupling

**Resolution:** named volume `shared-data` — shared filesystem
**Filtering:** generic_variable=false same_value=false resolved_reference=named_volume

## 2. orders ↔ reports through `DB_HOST=postgres` (env_var) — confidence 0.95 **meaningful**

**Reason:** shared DB_HOST coupling

**Resolution:** `'postgres'` → Compose service `None` (image: unknown) — internal coupling
**Filtering:** generic_variable=false same_value=false resolved_reference=compose_service
