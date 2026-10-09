"""Resumen determinístico sin IA: se usa en el modo «plantilla», como respaldo y en la demo."""
from __future__ import annotations

from datetime import date, timedelta

from ..util import one_line
from .schema import Avance, Item, Problema, Resumen

TIPO_TXT = {"exploracion": "Exploración", "en_curso": "En curso", "validado": "Validado"}


def _group_key(r: dict) -> str:
    return r["tarea_id"] or r["id"]


def build_template_summary(sources: dict) -> Resumen:
    regs = sources["registros"]
    res = Resumen()
    if not regs:
        res.informacion_faltante.append("No hay registros válidos en el período.")
        return res

    groups: dict[str, list[dict]] = {}
    for r in regs:
        groups.setdefault(_group_key(r), []).append(r)

    for key, items in groups.items():
        first = items[0]
        nombre = first["tarea"] or one_line(first["actividad"], 120)
        res.objetivos.append(Item(texto=f"{first['proyecto']}: {nombre}", registros=[x["id"] for x in items]))

    for r in regs:
        texto = one_line(r["actividad"], 500)
        if r["avance"]:
            texto += f" — {one_line(r['avance'], 500)}"
        res.avances.append(Avance(texto=texto, registros=[r["id"]], tipo=r["tipo_avance"]))
        if r["tipo_avance"] == "validado" and r["avance"]:
            res.resultados.append(Item(texto=one_line(r["avance"], 600), registros=[r["id"]]))
        if not r["avance"]:
            res.informacion_faltante.append(f"El registro {r['id']} no indica avance o resultado.")

    for key, items in groups.items():
        with_problem = [x for x in items if x["problemas"] or x["estado_problema"] != "sin_problema"]
        if not with_problem:
            continue
        ordered = sorted(with_problem, key=lambda x: (x["fecha"], x["revision"]))
        last = ordered[-1]
        estados = [x["estado_problema"] for x in ordered]
        descripcion = "; ".join(one_line(x["problemas"], 300).rstrip(".") for x in ordered if x["problemas"]) or "Problema sin descripción"
        refs = [x["id"] for x in ordered]
        solucion = next((one_line(x["solucion"], 500) for x in reversed(ordered) if x["solucion"]), "")
        estado = {"resuelto": "resuelto", "en_curso": "en_curso"}.get(last["estado_problema"], "abierto")
        if "resuelto" in estados[:-1] and last["estado_problema"] in ("abierto", "en_curso"):
            estado = "ambiguo"
            res.ambiguedades.append(Item(texto="Un problema figuró como resuelto y luego volvió a aparecer abierto.",
                                         registros=refs))
        res.problemas.append(Problema(descripcion=descripcion, estado=estado, solucion=solucion, registros=refs))
        if estado in ("abierto", "en_curso") and not solucion:
            res.informacion_faltante.append(f"Falta el plan o la solución del problema registrado en {last['id']}.")

    for key, items in groups.items():
        last_steps = next((x for x in reversed(items) if x["proximos_pasos"]), None)
        if last_steps:
            res.proximos_pasos.append(Item(texto=one_line(last_steps["proximos_pasos"], 600),
                                           registros=[last_steps["id"]]))

    inicio = date.fromisoformat(sources["periodo"]["inicio"])
    fin = date.fromisoformat(sources["periodo"]["fin"])
    with_data = {r["fecha"] for r in regs} | set(sources.get("dias_sin_actividad", []))
    missing = []
    d = inicio
    while d <= fin:
        if d.weekday() < 5 and d.isoformat() not in with_data:
            missing.append(d.strftime("%d/%m"))
        d += timedelta(days=1)
    if missing:
        res.informacion_faltante.append("Días hábiles sin registro en el período: " + ", ".join(missing) + ".")
    res.evidencias_sugeridas = [e["id"] for e in sources["evidencias"]][:10]
    return res
