"""Esquema de la respuesta estructurada y validación contra las fuentes reales."""
from __future__ import annotations

import copy
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..secrets_guard import redact
from ..util import one_line


class Item(BaseModel):
    model_config = ConfigDict(extra="ignore")
    texto: str = Field(max_length=1500)
    registros: list[str] = Field(default_factory=list, max_length=60)


class Avance(Item):
    tipo: Literal["exploracion", "en_curso", "validado"] = "en_curso"


class Problema(BaseModel):
    model_config = ConfigDict(extra="ignore")
    descripcion: str = Field(max_length=1500)
    estado: Literal["abierto", "en_curso", "resuelto", "ambiguo"] = "abierto"
    solucion: str = Field("", max_length=1500)
    registros: list[str] = Field(default_factory=list, max_length=60)


class Resumen(BaseModel):
    model_config = ConfigDict(extra="ignore")
    objetivos: list[Item] = Field(default_factory=list, max_length=30)
    avances: list[Avance] = Field(default_factory=list, max_length=60)
    resultados: list[Item] = Field(default_factory=list, max_length=40)
    problemas: list[Problema] = Field(default_factory=list, max_length=40)
    proximos_pasos: list[Item] = Field(default_factory=list, max_length=40)
    informacion_faltante: list[str] = Field(default_factory=list, max_length=40)
    ambiguedades: list[Item] = Field(default_factory=list, max_length=30)
    evidencias_sugeridas: list[str] = Field(default_factory=list, max_length=40)


def _inline_refs(schema: dict) -> dict:
    """Gemini acepta JSON Schema; se resuelven $ref locales para máxima compatibilidad."""
    defs = schema.get("$defs", {})

    def walk(node):
        if isinstance(node, dict):
            if "$ref" in node:
                name = node["$ref"].split("/")[-1]
                return walk(copy.deepcopy(defs[name]))
            return {k: walk(v) for k, v in node.items() if k not in ("$defs", "title", "default")}
        if isinstance(node, list):
            return [walk(x) for x in node]
        return node
    return walk(schema)


def response_json_schema() -> dict:
    return _inline_refs(Resumen.model_json_schema())


class InvalidAIResponse(ValueError):
    pass


def validate_summary(data, sources: dict) -> tuple[Resumen, list[str]]:
    """Valida forma, IDs y coherencia. Lo que no tiene respaldo se descarta o se marca."""
    try:
        resumen = Resumen.model_validate(data)
    except ValidationError as exc:
        raise InvalidAIResponse(f"La respuesta no respeta el formato esperado ({exc.error_count()} error(es)).") from exc
    recs = {r["id"]: r for r in sources["registros"]}
    evid_ids = {e["id"] for e in sources["evidencias"]}
    warnings: list[str] = []

    def clean_refs(refs: list[str], where: str) -> list[str]:
        good = [r for r in dict.fromkeys(refs) if r in recs]
        bad = [r for r in refs if r not in recs]
        if bad:
            warnings.append(f"Se quitaron referencias inexistentes en {where}: {', '.join(sorted(set(bad)))[:200]}")
        return good

    def clean_items(items, where):
        out = []
        for it in items:
            it.texto = redact(one_line(it.texto, 1500))
            it.registros = clean_refs(it.registros, where)
            if not it.registros:
                warnings.append(f"Se descartó un elemento de {where} sin registros que lo respalden.")
                continue
            out.append(it)
        return out

    resumen.objetivos = clean_items(resumen.objetivos, "objetivos")
    resumen.avances = clean_items(resumen.avances, "avances")
    resumen.proximos_pasos = clean_items(resumen.proximos_pasos, "próximos pasos")
    resumen.ambiguedades = clean_items(resumen.ambiguedades, "ambigüedades")

    resultados = []
    for it in clean_items(resumen.resultados, "resultados"):
        if any(recs[r]["tipo_avance"] == "validado" for r in it.registros):
            resultados.append(it)
        else:
            warnings.append("Un «resultado» no tenía registros marcados como validados: se movió a avances en curso.")
            resumen.avances.append(Avance(texto=it.texto, registros=it.registros, tipo="en_curso"))
    resumen.resultados = resultados

    problemas = []
    for p in resumen.problemas:
        p.descripcion = redact(one_line(p.descripcion, 1500))
        p.solucion = redact(one_line(p.solucion, 1500))
        p.registros = clean_refs(p.registros, "problemas")
        if not p.registros:
            warnings.append("Se descartó un problema sin registros que lo respalden.")
            continue
        if p.estado == "resuelto" and not any(recs[r]["estado_problema"] == "resuelto" for r in p.registros):
            p.estado = "ambiguo"
            warnings.append("Un problema figuraba como resuelto sin un registro que lo confirme: se marcó como ambiguo.")
        problemas.append(p)
    resumen.problemas = problemas

    resumen.informacion_faltante = [redact(one_line(x, 600)) for x in resumen.informacion_faltante if x.strip()]
    good_ev = [e for e in dict.fromkeys(resumen.evidencias_sugeridas) if e in evid_ids]
    if len(good_ev) != len(set(resumen.evidencias_sugeridas)):
        warnings.append("Se quitaron evidencias sugeridas que no existen.")
    resumen.evidencias_sugeridas = good_ev
    return resumen, warnings
