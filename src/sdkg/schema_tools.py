"""Generate schema artefacts from the LinkML source, and validate against them."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "schema"
GENERATED_JSON_SCHEMA = SCHEMA_DIR / "generated" / "sdkg.schema.json"


def generate_json_schema(source: str | Path) -> dict[str, Any]:
    from linkml.generators.jsonschemagen import JsonSchemaGenerator

    return json.loads(JsonSchemaGenerator(str(source)).serialize())


def generate_all(source: str | Path, out: str | Path) -> None:
    """Requires the `dev` extra. Regenerate whenever the source schema changes."""
    from linkml.generators.jsonldcontextgen import ContextGenerator
    from linkml.generators.owlgen import OwlSchemaGenerator
    from linkml.generators.shaclgen import ShaclGenerator

    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    source = str(source)
    (out / "sdkg.schema.json").write_text(json.dumps(generate_json_schema(source), indent=2, sort_keys=True) + "\n", "utf-8")
    (out / "sdkg.context.jsonld").write_text(ContextGenerator(source, metadata=False).serialize() + "\n", "utf-8")
    (out / "sdkg.owl.ttl").write_text(OwlSchemaGenerator(source, metadata_profile=None).serialize() + "\n", "utf-8")
    (out / "sdkg.shacl.ttl").write_text(ShaclGenerator(source).serialize() + "\n", "utf-8")


def claim_validator():
    from jsonschema import Draft202012Validator

    schema = json.loads(GENERATED_JSON_SCHEMA.read_text("utf-8"))
    claim = dict(schema["$defs"]["Claim"])
    claim["$defs"] = schema["$defs"]
    return Draft202012Validator(claim)


def allowed_predicates() -> frozenset[str]:
    schema = json.loads(GENERATED_JSON_SCHEMA.read_text("utf-8"))
    return frozenset(schema["$defs"]["Predicate"]["enum"])
