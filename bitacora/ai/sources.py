"""Reúne los registros vigentes de un período: es la única fuente del resumen."""
from __future__ import annotations

from ..calendar_logic import Period
from ..db import rows
from ..util import canonical_json, sha256_text

SOURCE_FIELDS = ("id", "fecha", "proyecto", "tarea_id", "tarea", "actividad", "avance", "tipo_avance",
                 "problemas", "solucion", "estado_problema", "proximos_pasos", "revision")


def collect_sources(conn, period: Period, pcfg) -> dict:
    sql = ("SELECT r.*, t.titulo AS tarea FROM registros r LEFT JOIN tareas t ON t.id = r.tarea_id "
           "WHERE r.fecha BETWEEN ? AND ? AND r.estado = 'guardado' AND r.archivado = 0 "
           "AND trim(r.actividad) <> ''")
    params: list = [period.inicio.isoformat(), period.fin.isoformat()]
    all_rows = rows(conn.execute(sql + " ORDER BY r.fecha, r.creado_utc, r.id", params))
    if pcfg.proyectos:
        wanted = {p.lower() for p in pcfg.proyectos}
        all_rows = [r for r in all_rows if r["proyecto"].lower() in wanted]
    included = [r for r in all_rows if r["incluir_ia"]]
    excluded = [r["id"] for r in all_rows if not r["incluir_ia"]]
    registros = []
    ids = [r["id"] for r in included]
    evid_by_rec: dict[str, list[str]] = {}
    evidencias = []
    if ids:
        marks = ",".join("?" * len(ids))
        for e in rows(conn.execute(
                f"SELECT id, nombre, mime, registro_id FROM evidencias WHERE archivado = 0 AND registro_id IN ({marks}) "
                "ORDER BY creado_utc, id", ids)):
            evidencias.append(e)
            evid_by_rec.setdefault(e["registro_id"], []).append(e["id"])
    for r in included:
        item = {k: r.get(k) for k in SOURCE_FIELDS}
        item["evidencias"] = evid_by_rec.get(r["id"], [])
        registros.append(item)
    declared = [x[0] for x in conn.execute(
        "SELECT fecha FROM dias_sin_actividad WHERE fecha BETWEEN ? AND ? ORDER BY fecha",
        (period.inicio.isoformat(), period.fin.isoformat())).fetchall()]
    return {
        "periodo": {"inicio": period.inicio.isoformat(), "fin": period.fin.isoformat()},
        "proyectos": sorted({r["proyecto"] for r in included}),
        "registros": registros,
        "evidencias": evidencias,
        "dias_sin_actividad": declared,
        "excluidos": excluded,
    }


def data_hash(sources: dict, pcfg) -> str:
    """Hash de los datos (independiente del modo): detecta cambios posteriores a un cierre."""
    cfg = {"proyectos": pcfg.proyectos, "audiencia": pcfg.audiencia, "max_diapositivas": pcfg.max_diapositivas}
    payload = {k: v for k, v in sources.items() if k != "excluidos"}
    return sha256_text(canonical_json({"fuentes": payload, "cfg": cfg}))


def input_hash(hash_datos: str, modo: str, modelo: str) -> str:
    return sha256_text(canonical_json({"datos": hash_datos, "modo": modo, "modelo": modelo}))
