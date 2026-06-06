# Schemas package — Pydantic models for API request/response bodies.
# These are separate from SQLAlchemy models (db/models/) and collector
# schemas (collectors/schemas.py). Each layer has its own schema:
#   - Collector layer: CollectedDocument (raw data from external sources)
#   - DB layer:        SQLAlchemy models (Document, Outbreak, Pathogen, ...)
#   - API layer:       DocumentRead, IngestionTriggerResponse, ... (this package)
