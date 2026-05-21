from fastapi import APIRouter

from app.api.rest import (
    actions,
    agent_tokens,
    audit,
    auth_sessions,
    documents,
    edges,
    entities,
    episodes,
    exports,
    graph,
    health,
    integrations_google_docs,
    integrations_permissions,
    labels,
    me,
    members,
    ontology,
    playground,
    proposals,
    provenance,
    search,
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
router.include_router(proposals.router)
router.include_router(provenance.router)
router.include_router(labels.router)
router.include_router(actions.router)
router.include_router(exports.router)
router.include_router(agent_tokens.router)
router.include_router(playground.router)
router.include_router(integrations_google_docs.router)
router.include_router(integrations_permissions.router)
