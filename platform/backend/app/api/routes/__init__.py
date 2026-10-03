"""API routers, listed in registration order."""

from app.api.routes import (
    analytics,
    artifacts,
    auth,
    batches,
    datasets,
    health,
    imports,
    jobs,
    people,
    presets,
    runs,
    taxonomy,
    workspace,
)

ROUTE_MODULES = (
    health,
    auth,
    people,
    workspace,
    datasets,
    imports,
    presets,
    analytics,
    runs,
    batches,
    jobs,
    taxonomy,
    artifacts,
)
