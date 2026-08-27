# BlindSpot

BlindSpot detects hidden dependencies between microservices that do not appear as direct network calls, focusing on shared configuration such as environment variables and volumes in Docker Compose projects.

## Stage 1 — Ground-Truth Fixtures

Stage 1 prepares the development environment and synthetic ground-truth inputs for the BlindSpot pipeline:

```
Input → Parse+Normalize → Candidate Discovery → Candidate Filtering → LLM Judge → Dependency Model → Graph → Report
```

Stage 1 does not implement the detector — it provides the fixtures that the future implementation must correctly analyze.

### Fixtures

| Fixture | Path | Expected Result |
|---|---|---|
| **shared_env** | `fixtures/shared_env/docker-compose.yml` | `orders ↔ reports` = **potential real hidden dependency** — both services share `DB_HOST=shared-db` and `DB_NAME=orders` (shared database configuration) |
| **shared_volume** | `fixtures/shared_volume/docker-compose.yml` | `orders ↔ reports` = **potential real hidden dependency** — both mount the same named volume `shared-data:/data` |
| **near_miss** | `fixtures/near_miss/docker-compose.yml` | `orders ↔ reports` = **NOT a dependency** — both define `PORT` but with different values (`8000` vs `9000`); same variable name alone must not imply coupling |
