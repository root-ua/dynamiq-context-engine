from fastapi import APIRouter

from app.api.rest import (
    agent_tokens,
    audit,
    auth_sessions,
    connectors,
    documents,
    edges,
    entities,
    episodes,
    graph,
    health,
    identity,
    me,
    members,
    ontology,
    search,
    sources,
    workspaces,
)

router = APIRouter()
router.include_router(health.router)
router.include_router(me.router)
router.include_router(auth_sessions.router)
router.include_router(workspaces.router)
router.include_router(members.router)
router.include_router(ontology.router)
router.include_router(entities.router)
router.include_router(edges.router)
router.include_router(documents.router)
router.include_router(episodes.router)
router.include_router(search.router)
router.include_router(graph.router)
router.include_router(audit.router)
router.include_router(agent_tokens.router)
router.include_router(connectors.router)
router.include_router(identity.router)
router.include_router(sources.router)
