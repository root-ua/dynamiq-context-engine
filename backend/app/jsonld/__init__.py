"""JSON-LD serializers for the public API.

Phase N — every primary read endpoint (entity, edge, episode, type,
relation, graph) can return a JSON-LD document when the caller asks for
``Accept: application/ld+json``. The graph itself doesn't change; only
the wire format does.

The ``@context`` carries the vocabularies enterprise agents actually
expect:

* ``prov:`` — W3C provenance (PROV-O). Already established for
  ``/api/provenance`` endpoints; this module is now the single source of
  truth for the namespace so the provenance module imports from here.
* ``owl:`` — entity types render as ``owl:Class``; relations as
  ``owl:ObjectProperty``; merged entities surface ``owl:sameAs`` to
  external refs; relations with ``inverse_of`` emit ``owl:inverseOf``.
* ``rdfs:`` — ``rdfs:subClassOf`` for the type hierarchy,
  ``rdfs:domain``/``rdfs:range`` for relations, ``rdfs:label`` /
  ``rdfs:comment`` everywhere.
* ``skos:`` — ``skos:prefLabel`` for canonical name,
  ``skos:altLabel`` for aliases. Standard practice for entity-naming
  interop.
* ``xsd:`` — typed literals (mostly datetime).
* ``dce:`` — Dynamiq-private terms for fields with no standard
  equivalent.

This module deliberately does NOT introduce a new triple store; it's a
serialization layer that re-shapes the existing dataclasses.
"""
from __future__ import annotations

from typing import Any
from urllib.parse import quote

from app.domain.edge import Edge
from app.domain.entity import Entity
from app.domain.episode import Episode
from app.domain.ontology import EntityType, OntologySnapshot, RelationType

# ---------------------------------------------------------------------------
# Context
# ---------------------------------------------------------------------------

# Public base used when minting HTTP-style IRIs. The hostname is mainly
# advisory — clients shouldn't dereference these; what matters is that
# IRIs are deterministic and unique. Override via ``DCE_IRI_BASE`` env if
# a customer wants their hostname embedded.
def _iri_base() -> str:
    import os
    return os.environ.get("DCE_IRI_BASE", "https://platform.dynamiq.ai/.well-known/dce")


BASE_CONTEXT: dict[str, Any] = {
    "@context": {
        "prov": "http://www.w3.org/ns/prov#",
        "owl": "http://www.w3.org/2002/07/owl#",
        "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
        "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
        "skos": "http://www.w3.org/2004/02/skos/core#",
        "xsd": "http://www.w3.org/2001/XMLSchema#",
        "dce": "https://dynamiq.ai/context/v1#",
        # Per-property typings the helpers rely on.
        "Entity": "prov:Entity",
        "Activity": "prov:Activity",
        "Agent": "prov:Agent",
        "Class": "owl:Class",
        "ObjectProperty": "owl:ObjectProperty",
        "sameAs": {"@id": "owl:sameAs", "@type": "@id"},
        "inverseOf": {"@id": "owl:inverseOf", "@type": "@id"},
        "subClassOf": {"@id": "rdfs:subClassOf", "@type": "@id"},
        "domain": {"@id": "rdfs:domain", "@type": "@id"},
        "range": {"@id": "rdfs:range", "@type": "@id"},
        "label": "rdfs:label",
        "comment": "rdfs:comment",
        "prefLabel": "skos:prefLabel",
        "altLabel": "skos:altLabel",
        "wasGeneratedBy": {"@id": "prov:wasGeneratedBy", "@type": "@id"},
        "wasDerivedFrom": {"@id": "prov:wasDerivedFrom", "@type": "@id"},
        "wasAttributedTo": {"@id": "prov:wasAttributedTo", "@type": "@id"},
        "wasAssociatedWith": {"@id": "prov:wasAssociatedWith", "@type": "@id"},
        "used": {"@id": "prov:used", "@type": "@id"},
        "startedAtTime": {"@id": "prov:startedAtTime", "@type": "xsd:dateTime"},
        "endedAtTime": {"@id": "prov:endedAtTime", "@type": "xsd:dateTime"},
    }
}


# ---------------------------------------------------------------------------
# IRI minting
# ---------------------------------------------------------------------------

def entity_iri(entity_id: str) -> str:
    return f"{_iri_base()}/entity/{entity_id}"


def edge_iri(edge_id: str) -> str:
    return f"{_iri_base()}/edge/{edge_id}"


def episode_iri(episode_id: str) -> str:
    return f"{_iri_base()}/episode/{episode_id}"


def type_iri(slug: str) -> str:
    return f"{_iri_base()}/type/{quote(slug, safe='')}"


def relation_iri(slug: str) -> str:
    return f"{_iri_base()}/relation/{quote(slug, safe='')}"


def activity_iri(activity_id: str) -> str:
    return f"{_iri_base()}/activity/{activity_id}"


def _external_iri(kind: str, value: str) -> str:
    """Map ``entity_external_ref(kind, value)`` rows to a stable IRI for
    ``owl:sameAs``. Falls back to a urn: form for unknown kinds.
    """
    if kind == "wikidata":
        return f"https://www.wikidata.org/entity/{value}"
    if kind == "email":
        return f"mailto:{value}"
    if kind == "slug":
        return f"{_iri_base()}/slug/{quote(value, safe='')}"
    return f"urn:dce:ref:{quote(kind, safe='')}/{quote(value, safe='')}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ctx_only() -> dict[str, Any]:
    """Standalone @context (no @graph) for embedding in compound docs."""
    return dict(BASE_CONTEXT)


def _ancestors(t: EntityType, snapshot: OntologySnapshot) -> list[EntityType]:
    """Walk ``extends_id`` upward to root, returning the chain (closest-first)."""
    chain: list[EntityType] = []
    cur = t
    seen: set[str] = set()
    while cur and cur.extends_id and cur.extends_id not in seen:
        seen.add(cur.id)
        parent = snapshot.type_by_id(cur.extends_id)
        if parent is None:
            break
        chain.append(parent)
        cur = parent
    return chain


# ---------------------------------------------------------------------------
# Public serializers
# ---------------------------------------------------------------------------

def to_jsonld_type(
    t: EntityType, *, snapshot: OntologySnapshot, embed_context: bool = True
) -> dict[str, Any]:
    """Render an entity type as ``owl:Class`` with ``rdfs:subClassOf`` chain."""
    doc: dict[str, Any] = {}
    if embed_context:
        doc.update(_ctx_only())
    doc["@id"] = type_iri(t.slug)
    doc["@type"] = "Class"
    doc["dce:slug"] = t.slug
    doc["label"] = t.name
    if t.description:
        doc["comment"] = t.description
    parent = (
        snapshot.type_by_id(t.extends_id) if t.extends_id else None
    )
    if parent is not None:
        doc["subClassOf"] = type_iri(parent.slug)
    if t.schema:
        doc["dce:jsonSchema"] = t.schema
    if t.system:
        doc["dce:system"] = True
    return doc


def to_jsonld_relation(
    r: RelationType, *, snapshot: OntologySnapshot, embed_context: bool = True
) -> dict[str, Any]:
    """Render a relation type as ``owl:ObjectProperty``."""
    doc: dict[str, Any] = {}
    if embed_context:
        doc.update(_ctx_only())
    doc["@id"] = relation_iri(r.slug)
    doc["@type"] = "ObjectProperty"
    doc["dce:slug"] = r.slug
    doc["label"] = r.name
    if r.description:
        doc["comment"] = r.description
    dom = snapshot.type_by_id(r.domain_type_id) if r.domain_type_id else None
    if dom is not None:
        doc["domain"] = type_iri(dom.slug)
    rng = snapshot.type_by_id(r.range_type_id) if r.range_type_id else None
    if rng is not None:
        doc["range"] = type_iri(rng.slug)
    if r.inverse_of_id:
        # Look up the inverse relation by id in the snapshot.
        inv = next(
            (x for x in snapshot.relations if x.id == r.inverse_of_id),
            None,
        )
        if inv is not None:
            doc["inverseOf"] = relation_iri(inv.slug)
    doc["dce:cardinalitySubject"] = r.cardinality_subject
    doc["dce:cardinalityObject"] = r.cardinality_object
    doc["dce:symmetric"] = r.symmetric
    doc["dce:transitive"] = r.transitive
    doc["dce:temporal"] = r.temporal
    doc["dce:highStakes"] = r.high_stakes
    if r.system:
        doc["dce:system"] = True
    return doc


def to_jsonld_entity(
    entity: Entity,
    *,
    snapshot: OntologySnapshot,
    external_refs: list[tuple[str, str]] | None = None,
    embed_context: bool = True,
) -> dict[str, Any]:
    """Render an entity with skos:prefLabel/altLabel + rdfs:type + owl:sameAs.

    ``external_refs`` is the optional list of ``(kind, value)`` rows from
    ``entity_external_ref`` for this entity. The caller is responsible
    for fetching them — the helper has no DB access.
    """
    doc: dict[str, Any] = {}
    if embed_context:
        doc.update(_ctx_only())
    doc["@id"] = entity_iri(entity.id)
    doc["@type"] = "Entity"
    type_def = snapshot.type_by_id(entity.type_id)
    if type_def is not None:
        doc["rdf:type"] = type_iri(type_def.slug)
    doc["prefLabel"] = entity.canonical
    if entity.aliases:
        doc["altLabel"] = entity.aliases
    doc["label"] = entity.canonical
    if entity.summary:
        doc["comment"] = entity.summary
    if entity.props:
        doc["dce:props"] = entity.props
    if entity.merged_into_id:
        doc["sameAs"] = entity_iri(entity.merged_into_id)
    if external_refs:
        existing = doc.get("sameAs")
        same_as_list: list[str] = (
            [existing] if isinstance(existing, str)
            else list(existing or [])
        )
        for kind, value in external_refs:
            same_as_list.append(_external_iri(kind, value))
        doc["sameAs"] = same_as_list
    doc["dce:workspaceId"] = entity.workspace_id
    doc["dce:internalIri"] = entity.iri  # the urn:memory:... id is kept too
    doc["dce:createdAt"] = entity.created_at
    doc["dce:updatedAt"] = entity.updated_at
    return doc


def to_jsonld_edge(
    edge: Edge,
    *,
    snapshot: OntologySnapshot,
    embed_context: bool = True,
) -> dict[str, Any]:
    """Render an edge as ``prov:Entity`` of subtype ``dce:Fact``.

    The provenance helpers in ``app.domain.provenance`` already emit a
    rich JSON-LD doc for ``get_provenance``. This serializer is the
    plain-edge variant used by ``GET /api/edges/:id`` — keeps the fact
    content + bi-temporal envelope + a stub link to the activity.
    """
    doc: dict[str, Any] = {}
    if embed_context:
        doc.update(_ctx_only())
    doc["@id"] = edge_iri(edge.id)
    doc["@type"] = ["Entity", "dce:Fact"]
    doc["dce:fact"] = edge.fact
    doc["dce:subject"] = entity_iri(edge.subject_id)
    doc["dce:object"] = entity_iri(edge.object_id)
    if edge.predicate_slug:
        doc["dce:predicate"] = relation_iri(edge.predicate_slug)
    doc["dce:validFrom"] = edge.valid_from
    if edge.valid_to:
        doc["dce:validTo"] = edge.valid_to
    doc["dce:sysFrom"] = edge.sys_from
    if edge.sys_to:
        doc["dce:sysTo"] = edge.sys_to
    if edge.confidence is not None:
        doc["dce:confidence"] = edge.confidence
    if edge.props:
        doc["dce:props"] = edge.props
    doc["dce:workspaceId"] = edge.workspace_id
    return doc


def to_jsonld_episode(
    episode: Episode, *, embed_context: bool = True
) -> dict[str, Any]:
    """Render an episode as ``prov:Entity`` of subtype ``dce:Episode``."""
    doc: dict[str, Any] = {}
    if embed_context:
        doc.update(_ctx_only())
    doc["@id"] = episode_iri(episode.id)
    doc["@type"] = ["Entity", "dce:Episode"]
    if episode.content_text:
        doc["dce:contentText"] = episode.content_text
    doc["dce:sourceKind"] = episode.source_kind
    if episode.source_ref:
        doc["dce:sourceRef"] = episode.source_ref
    doc["dce:occurredAt"] = episode.occurred_at
    doc["dce:ingestedAt"] = episode.ingested_at
    doc["dce:processingStatus"] = episode.processing_status
    doc["dce:workspaceId"] = episode.workspace_id
    return doc


def to_jsonld_graph(
    *,
    entities: list[Entity],
    edges: list[Edge],
    snapshot: OntologySnapshot,
) -> dict[str, Any]:
    """Compound document for ``/api/graph/traverse`` results.

    Single ``@context`` at the top; ``@graph`` carries every node and
    edge as a separate node with its own ``@id`` — exactly the JSON-LD
    1.1 graph shape.
    """
    doc: dict[str, Any] = dict(_ctx_only())
    nodes: list[dict[str, Any]] = []
    for ent in entities:
        nodes.append(
            to_jsonld_entity(ent, snapshot=snapshot, embed_context=False)
        )
    for edge in edges:
        nodes.append(
            to_jsonld_edge(edge, snapshot=snapshot, embed_context=False)
        )
    doc["@graph"] = nodes
    return doc
