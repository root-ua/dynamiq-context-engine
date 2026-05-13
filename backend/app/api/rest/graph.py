from __future__ import annotations

from dataclasses import asdict
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException

from app.api.content_negotiation import accept_jsonld
from app.api.rest.schemas import GraphEdgeOut, GraphNodeOut, GraphOut, GraphTraverseIn
from app.auth.deps import CurrentPrincipal, DbSession
from app.jsonld import BASE_CONTEXT, edge_iri, entity_iri, relation_iri
from app.retrieval.graph import traverse

router = APIRouter(prefix="/graph", tags=["graph"])


@router.post("/traverse")
async def traverse_route(
    payload: GraphTraverseIn,
    principal: CurrentPrincipal,
    session: DbSession,
    jsonld: Annotated[bool, Depends(accept_jsonld)] = False,
) -> dict[str, Any] | GraphOut:
    if not principal.workspace_id:
        raise HTTPException(400, "workspace required")

    sub = await traverse(
        session,
        workspace_id=principal.workspace_id,
        seeds=payload.seeds,
        max_hops=payload.max_hops,
        direction=payload.direction,
        predicate_slugs=payload.predicates,
        type_slugs=payload.types,
        as_of_valid=payload.as_of_valid.isoformat() if payload.as_of_valid else None,
        max_nodes=payload.max_nodes,
        principal=principal,
    )
    if jsonld:
        doc: dict[str, Any] = dict(BASE_CONTEXT)
        graph: list[dict[str, Any]] = []
        for n in sub.nodes:
            graph.append(
                {
                    "@id": entity_iri(n.id),
                    "@type": "Entity",
                    "prefLabel": n.canonical,
                    "label": n.canonical,
                    "dce:typeSlug": n.type,
                    "dce:internalIri": n.iri,
                    "dce:distance": n.distance,
                }
            )
        for e in sub.edges:
            graph.append(
                {
                    "@id": edge_iri(e.id),
                    "@type": ["Entity", "dce:Fact"],
                    "dce:subject": entity_iri(e.subject_id),
                    "dce:object": entity_iri(e.object_id),
                    "dce:predicate": relation_iri(e.predicate),
                    "dce:fact": e.fact,
                    "dce:validFrom": e.valid_from,
                    **({"dce:validTo": e.valid_to} if e.valid_to else {}),
                }
            )
        doc["@graph"] = graph
        return doc
    return GraphOut(
        nodes=[GraphNodeOut(**asdict(n)) for n in sub.nodes],
        edges=[GraphEdgeOut(**asdict(e)) for e in sub.edges],
    )
