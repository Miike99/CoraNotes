'use strict';
/* CoraNotes — interfaz sin frameworks. Todo el texto de usuario se inserta con textContent
   (nunca como HTML), así una nota con HTML o <script> se muestra como texto. */

const estado = { csrf: null, demo: false, zona: null, sucio: false, temporizador: null };
const DIAS = ['Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom'];
const DIAS_LARGO = ['lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado', 'domingo'];
const TIPO_AVANCE = { exploracion: 'Exploración', en_curso: 'En curso', validado: 'Validado' };
const EST_PROBLEMA = { sin_problema: 'Sin problema', abierto: 'Abierto', en_curso: 'En curso', resuelto: 'Resuelto' };
const EST_PROMPT = {
  actualizado: ['ok', 'Actualizado'], actualizando: ['info', 'Actualizando'],
  cambios_pendientes: ['alerta', 'Cambios pendientes'], error: ['error', 'Error'], sin_contenido: ['alerta', 'Sin contenido'],
};
const EST_DOC = {
  importado: ['ok', 'Importado'], pendiente_clasificar: ['alerta', 'Pendiente de clasificar'], error: ['error', 'Error'],
  duplicado: ['info', 'Duplicado'], evidencia: ['info', 'Evidencia (imagen)'], ignorado: ['', 'Ignorado'],
  conflicto: ['alerta', 'Conflicto'],
};
const EST_CIERRE = {
  listo: ['ok', 'Prompt listo'], listo_respaldo: ['alerta', 'Listo con plantilla de respaldo'],
  preparando: ['info', 'Preparando'], pendiente: ['error', 'Pendiente'], sin_contenido: ['alerta', 'Sin contenido'],
  error: ['error', 'Error'],
};
const ENTREGA = {
  entregada_al_sistema: 'Entregada a Windows (si «No molestar» está activo puede quedar solo en el centro de notificaciones).',
  desactivada: 'Windows tiene las notificaciones desactivadas para esta app: no se mostró.',
  no_disponible: 'Notificaciones nativas no disponibles: solo aviso dentro de la app.',
  error: 'No se pudo entregar a Windows: solo aviso dentro de la app.',
  solo_app: 'Solo aviso dentro de la app.', simulada: 'Simulada (prueba automática).', pendiente: 'Pendiente.',
};

// ---------- utilidades DOM ----------
function h(tag, attrs, ...hijos) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2), v);
    else if (k === 'class') el.className = v;
    else if (k === 'text') el.textContent = v;
    else if (k === 'value') el.value = v;
    else if (k === 'checked') el.checked = !!v;
    else el.setAttribute(k, v === true ? '' : String(v));
  }
  for (const c of hijos.flat()) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}
const $ = (sel, raiz = document) => raiz.querySelector(sel);
const limpiar = (xs) => xs.flat().filter(x => x !== null && x !== undefined && x !== false);
function poner(el, ...xs) { el.append(...limpiar(xs)); return el; }
function reemplazar(el, ...xs) { el.replaceChildren(...limpiar(xs)); return el; }
function insignia(clase, texto) { return h('span', { class: `insignia ${clase || ''}`, text: texto }); }
function fechaLocal(iso) { if (!iso) return '—'; const [y, m, d] = iso.slice(0, 10).split('-'); return `${d}/${m}/${y}`; }
function momento(iso) {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleString('es-AR', { timeZone: estado.zona || undefined, hourCycle: 'h23',
      day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' });
  } catch { return iso; }
}
function hoyISO() { const d = new Date(); d.setMinutes(d.getMinutes() - d.getTimezoneOffset()); return d.toISOString().slice(0, 10); }
function sumarDias(iso, n) { const d = new Date(iso + 'T12:00:00'); d.setDate(d.getDate() + n); return d.toISOString().slice(0, 10); }
function campo(etiqueta, control, ayuda) {
  const id = control.id || ('c' + Math.random().toString(36).slice(2, 9));
  control.id = id;
  return h('div', { class: 'campo' }, h('label', { for: id, text: etiqueta }), control, ayuda ? h('span', { class: 'ayuda', text: ayuda }) : null);
}
function guardarLocal(clave, valor) { try { localStorage.setItem(clave, JSON.stringify(valor)); } catch { /* sin almacenamiento */ } }
function leerLocal(clave) { try { return JSON.parse(localStorage.getItem(clave) || 'null'); } catch { return null; } }
function borrarLocal(clave) { try { localStorage.removeItem(clave); } catch { /* nada */ } }

function mensaje(texto, tipo = 'ok', ms = 7000) {
  const caja = h('div', { class: `mensaje ${tipo}`, role: tipo === 'error' ? 'alert' : 'status' },
    h('span', { text: texto }), h('button', { type: 'button', 'aria-label': 'Cerrar mensaje', text: '×', onclick: () => caja.remove() }));
  $('#mensajes').append(caja);
  if (ms) setTimeout(() => caja.remove(), ms);
}

// ---------- API ----------
async function iniciarSesion() {
  const r = await fetch('/api/sesion', { credentials: 'same-origin' });
  const d = await r.json();
  estado.csrf = d.csrf; estado.demo = d.demo; estado.zona = d.zona;
  $('#insignia-demo').hidden = !d.demo;
}
async function api(metodo, url, cuerpo, reintentar = true) {
  const opts = { method: metodo, credentials: 'same-origin', headers: {} };
  if (metodo !== 'GET') opts.headers['X-CSRF-Token'] = estado.csrf || '';
  if (cuerpo instanceof FormData) opts.body = cuerpo;
  else if (cuerpo !== undefined) { opts.headers['Content-Type'] = 'application/json'; opts.body = JSON.stringify(cuerpo); }
  let r;
  try { r = await fetch(url, opts); } catch {
    throw new Error('No hay conexión con el backend local. ¿Está iniciado CoraNotes? (Iniciar CoraNotes.bat)');
  }
  let datos = null;
  try { datos = await r.json(); } catch { datos = null; }
  if (r.status === 403 && datos && datos.codigo === 'csrf' && reintentar) { await iniciarSesion(); return api(metodo, url, cuerpo, false); }
  if (!r.ok) throw new Error((datos && datos.detalle) || `Error ${r.status}`);
  return datos;
}
async function accion(fn, exito) {
  try { const r = await fn(); if (exito) mensaje(typeof exito === 'function' ? exito(r) : exito, 'ok'); return r; }
  catch (e) { mensaje(e.message, 'error', 12000); return null; }
}
async function copiar(texto) {
  try { await navigator.clipboard.writeText(texto); mensaje('Copiado al portapapeles.'); }
  catch {
    const t = h('textarea', { value: texto }); document.poner(body, t); t.select();
    try { document.execCommand('copy'); mensaje('Copiado al portapapeles.'); } catch { mensaje('No se pudo copiar: seleccioná el texto y usá Ctrl+C.', 'alerta'); }
    t.remove();
  }
}
function enlaceClaude() {
  return h('a', { class: 'boton', href: 'https://claude.ai/new', target: '_blank', rel: 'noopener noreferrer',
    text: 'Abrir Claude (pegás el prompt vos)' });
}

// ---------- Markdown seguro (sin HTML crudo) ----------
function enLinea(texto) {
  const frag = document.createDocumentFragment();
  texto.split(/(\*\*[^*]+\*\*)/g).forEach(p => {
    if (p.startsWith('**') && p.endsWith('**') && p.length > 4) poner(frag, h('strong', { text: p.slice(2, -2) }));
    else if (p) poner(frag, document.createTextNode(p));
  });
  return frag;
}
function markdown(texto) {
  const cont = h('div', { class: 'md' });
  let lista = null;
  for (const linea of (texto || '').split('\n')) {
    const m = linea.match(/^(#{1,3})\s+(.*)$/);
    if (m) { lista = null; poner(cont, h('h' + m[1].length, {}, enLinea(m[2]))); continue; }
    const li = linea.match(/^\s*(?:[-*]|\d+\.)\s+(.*)$/);
    if (li) { if (!lista) { lista = h('ul'); poner(cont, lista); } poner(lista, h('li', {}, enLinea(li[1]))); continue; }
    lista = null;
    if (linea.startsWith('>')) { poner(cont, h('blockquote', {}, enLinea(linea.replace(/^>\s?/, '')))); continue; }
    if (linea.trim()) poner(cont, h('p', {}, enLinea(linea)));
  }
  return cont;
}

// ---------- enrutador ----------
function parametros() {
  const [ruta, qs] = (location.hash.replace(/^#\/?/, '') || 'inicio').split('?');
  return { ruta: ruta || 'inicio', p: new URLSearchParams(qs || '') };
}
async function navegar() {
  if (estado.temporizador) { clearInterval(estado.temporizador); estado.temporizador = null; }
  const { ruta, p } = parametros();
  document.querySelectorAll('nav a').forEach(a => {
    if (a.dataset.ruta === ruta) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current');
  });
  const vista = $('#vista');
  const vistas = { inicio: vistaInicio, registro: vistaRegistro, historial: vistaHistorial, prompt: vistaPrompt, config: vistaConfig };
  const fn = vistas[ruta] || vistaInicio;
  reemplazar(vista, h('p', { text: 'Cargando…' }));
  try { await fn(vista, p); } catch (e) { reemplazar(vista, h('div', { class: 'panel' }, h('h1', { text: 'No se pudo cargar' }), h('p', { text: e.message }))); }
  vista.focus();
}
window.addEventListener('hashchange', (ev) => {
  if (estado.sucio && !confirm('Hay texto sin guardar en el formulario. Queda guardado en este navegador, ¿salir igual?')) {
    history.replaceState(null, '', ev.oldURL.slice(ev.oldURL.indexOf('#'))); return;
  }
  estado.sucio = false; navegar();
});
window.addEventListener('beforeunload', (e) => { if (estado.sucio) { e.preventDefault(); e.returnValue = ''; } });

// ---------- Inicio ----------
async function vistaInicio(vista) {
  const pintar = async () => {
    const e = await api('GET', '/api/estado');
    const avisos = await api('GET', '/api/avisos');
    const cont = $('#contador-avisos');
    cont.hidden = !e.avisos_no_leidos; cont.textContent = e.avisos_no_leidos;
    const hoy = e.hoy;
    const dia = h('div', { class: 'panel' }, h('h2', { text: `Hoy, ${fechaLocal(hoy.fecha)}` }));
    if (hoy.registrado) {
      poner(dia, h('p', {}, insignia('ok', hoy.motivo === 'sin_actividad' ? 'Registrado: sin actividad' : `Registrado (${hoy.validos} registro/s)`)));
    } else {
      poner(dia, h('p', {}, insignia('alerta', 'Todavía sin registrar'),
        hoy.borradores ? h('span', { class: 'meta', text: ` · ${hoy.borradores} borrador(es): un borrador no completa el día` }) : null));
    }
    poner(dia, h('div', { class: 'acciones' },
      h('a', { class: 'boton primario', href: `#/registro?fecha=${hoy.fecha}`, text: 'Registrar actividad' }),
      !hoy.registrado ? h('button', { type: 'button', text: 'Hoy no hubo actividad para registrar', onclick: async () => {
        if (await accion(() => api('POST', '/api/dias/sin-actividad', { fecha: hoy.fecha }), 'Día marcado sin actividad.')) pintar();
      } }) : null,
      hoy.sin_actividad ? h('button', { type: 'button', text: 'Corregir: quitar «sin actividad»', onclick: async () => {
        if (await accion(() => api('POST', '/api/dias/quitar-sin-actividad', { fecha: hoy.fecha }), 'Declaración quitada.')) pintar();
      } }) : null));

    const rec = h('div', { class: 'panel' }, h('h2', { text: 'Recordatorios' }));
    const r = e.recordatorios;
    poner(rec, h('p', {}, r.pausado ? insignia('alerta', r.pausa_hasta ? `Pausados hasta ${fechaLocal(r.pausa_hasta)}` : 'Pausados')
      : insignia('ok', 'Activos'), h('span', { class: 'meta', text: ` ${r.dias.map(d => DIAS[d]).join(', ')} a las ${r.hora} (${r.zona})` })));
    for (const a of r.activos) {
      poner(rec, h('div', { class: 'mensaje alerta' },
        h('span', { text: a.estado === 'pospuesto' ? `Recordatorio pospuesto hasta ${momento(a.pospuesto_hasta_utc)}` : 'Recordatorio activo: todavía no registraste el día.' }),
        h('span', { class: 'acciones' },
          h('button', { type: 'button', text: 'Posponer 15 min', onclick: async () => { if (await accion(() => api('POST', '/api/recordatorios/posponer', { clave: a.clave }), 'Pospuesto.')) pintar(); } }),
          h('button', { type: 'button', text: 'Descartar aviso', title: 'Descartar no registra actividad', onclick: async () => {
            if (await accion(() => api('POST', '/api/recordatorios/descartar', { clave: a.clave }), 'Aviso descartado. El día sigue sin registrar.')) pintar(); } }))));
    }
    poner(rec, h('h3', { text: 'Próximas ejecuciones' }),
      h('ul', {}, e.proximas.length ? e.proximas.map(x => h('li', { text: x.descripcion })) : h('li', { text: 'Ninguna en los próximos días.' })));
    if (e.advertencia_cierre) poner(rec, h('p', { class: 'ayuda', text: e.advertencia_cierre }));

    const g = e.gemini; const pr = e.prompt;
    const ia = h('div', { class: 'panel' }, h('h2', { text: 'Prompt semanal e IA' }),
      h('p', {}, 'Período ', h('strong', { text: pr.periodo.etiqueta }), ' · ', insignia(...EST_PROMPT[pr.estado] || ['', pr.estado])),
      h('p', { class: 'meta', text: `${pr.mensaje} Modo: ${pr.modo_etiqueta}. Última actualización: ${momento(pr.ultima_actualizacion_utc)}.` }),
      h('p', { class: 'meta' }, 'Gemini: ', g.lista ? insignia('ok', `listo (${g.modelo})`) : insignia('', g.motivo || 'no configurado'),
        g.bloqueado_hasta_utc ? insignia('error', `cuota agotada hasta ${momento(g.bloqueado_hasta_utc)}`) : null,
        ` · llamadas hoy ${g.llamadas_hoy}/${g.max_llamadas_diarias}`,
        g.ultima_llamada ? ` · último resultado: ${g.ultima_llamada.resultado}` : ''),
      h('div', { class: 'acciones' }, h('a', { class: 'boton', href: '#/prompt', text: 'Ver resumen y prompt' })));

    const proc = h('div', { class: 'panel' }, h('h2', { text: 'Proceso local' }),
      h('p', { class: 'meta', text: `Backend activo desde ${momento(e.proceso.iniciado_utc)}.` }),
      h('ul', {}, Object.entries(e.proceso.hilos).map(([k, v]) => h('li', { text: `${k}: ${v}` })),
        h('li', { text: `Carpeta de entrada: ${e.proceso.carpeta.estado}${e.proceso.carpeta.detalle ? ' — ' + e.proceso.carpeta.detalle : ''}` }),
        h('li', { text: `Cora: ${!e.mascota.habilitada ? 'desactivada' : e.mascota.visible ? 'visible en el escritorio' : e.mascota.conectada ? 'oculta en la bandeja' : 'cerrada'} · avisos por ${({ mascota: 'Cora', windows: 'notificación de Windows', app: 'solo la app' })[e.mascota.canal_recordatorio]}` })),
      e.mascota.habilitada && !e.mascota.visible ? h('button', { type: 'button', text: 'Mostrar a Cora', onclick: () => accion(() => api('POST', '/api/mascota/abrir'), (x) => x.mensaje) }) : null,
      h('p', { class: 'ayuda', text: 'Podés cerrar esta pestaña: el backend sigue trabajando y avisa con notificaciones de Windows. Si la PC se apaga o suspende, no hay avisos; al volver se muestra un aviso agrupado.' }));

    const lista = h('ul', { class: 'lista' });
    for (const a of avisos.slice(0, 15)) {
      poner(lista, h('li', {}, h('div', {}, a.leido ? null : insignia('info', 'nuevo'), ' ', h('strong', { text: a.titulo })),
        h('div', { text: a.mensaje }),
        h('div', { class: 'meta', text: `${momento(a.creado_utc)} · Notificación: ${ENTREGA[a.entrega] || a.entrega}` }),
        h('div', { class: 'acciones' }, a.enlace ? h('a', { href: a.enlace, text: 'Abrir' }) : null,
          !a.leido ? h('button', { type: 'button', text: 'Marcar leído', onclick: async () => { await accion(() => api('POST', '/api/avisos/leidos', { aviso_id: a.id })); pintar(); } }) : null)));
    }
    const pAvisos = h('div', { class: 'panel' }, h('h2', { text: 'Avisos' }),
      avisos.length ? lista : h('p', { class: 'meta', text: 'No hay avisos.' }),
      avisos.some(a => !a.leido) ? h('button', { type: 'button', text: 'Marcar todos como leídos', onclick: async () => { await accion(() => api('POST', '/api/avisos/leidos', {})); pintar(); } }) : null);

    const demo = estado.demo ? h('div', { class: 'panel' }, h('h2', { text: 'Demostración' }),
      h('p', { text: 'Carga registros ficticios de un proyecto de VR industrial, un recordatorio dentro de 2 minutos y un cierre dentro de 6 minutos. No consume la API de Gemini.' }),
      e.demo_cargada ? h('p', {}, insignia('ok', 'Datos ficticios cargados')) : h('button', { type: 'button', class: 'primario', text: 'Cargar datos ficticios', onclick: async (ev) => {
        ev.target.disabled = true;
        const r2 = await accion(() => api('POST', '/api/demo/cargar'), (x) => `Datos cargados. Recordatorio a las ${x.recordatorio || '—'}, cierre a las ${x.cierre || '—'}.`);
        if (r2) pintar(); else ev.target.disabled = false; } })) : null;
    reemplazar(vista, h('h1', { text: 'Inicio' }), demo, h('div', { class: 'rejilla' }, dia, rec, ia, proc), h('div', { class: 'separador' }), pAvisos);
  };
  await pintar();
  estado.temporizador = setInterval(() => { if (document.visibilityState === 'visible') pintar().catch(() => {}); }, 30000);
}

// ---------- Registro diario ----------
const CAMPOS_TEXTO = [
  ['actividad', 'Actividad realizada *', 'Qué hiciste. Obligatorio para guardar el registro.'],
  ['avance', 'Avance o resultado', 'Qué se logró o se comprobó.'],
  ['problemas', 'Problemas', 'Bloqueos o dificultades.'],
  ['solucion', 'Solución o estado del problema', 'Cómo se resolvió o en qué estado quedó.'],
  ['proximos_pasos', 'Próximos pasos', ''],
];
async function vistaRegistro(vista, p) {
  const id = p.get('id');
  const proy = await api('GET', '/api/proyectos');
  let rec = id ? await api('GET', `/api/registros/${encodeURIComponent(id)}`) : null;
  const claveLocal = `bitacora-form-${id || 'nuevo'}`;
  const guardado = leerLocal(claveLocal);
  const base = rec ? { ...rec, tarea_titulo: rec.tarea_titulo || '' } : { fecha: p.get('fecha') || hoyISO(), proyecto: '', tarea_titulo: '', tipo_avance: 'en_curso', estado_problema: 'sin_problema', incluir_ia: true };
  const datos = guardado && (!rec || guardado._revision === rec.revision) ? { ...base, ...guardado } : base;

  const form = h('form', { class: 'panel', novalidate: true });
  const ctrl = {};
  ctrl.fecha = h('input', { type: 'date', required: true, value: datos.fecha });
  ctrl.proyecto = h('input', { type: 'text', maxlength: 120, list: 'lista-proyectos', value: datos.proyecto || '' });
  ctrl.tarea_titulo = h('input', { type: 'text', maxlength: 200, list: 'lista-tareas', value: datos.tarea_titulo || '' });
  ctrl.tipo_avance = h('select', {}, Object.entries(TIPO_AVANCE).map(([k, v]) => h('option', { value: k, text: v })));
  ctrl.tipo_avance.value = datos.tipo_avance;
  ctrl.estado_problema = h('select', {}, Object.entries(EST_PROBLEMA).map(([k, v]) => h('option', { value: k, text: v })));
  ctrl.estado_problema.value = datos.estado_problema;
  ctrl.incluir_ia = h('input', { type: 'checkbox', checked: datos.incluir_ia !== false });
  for (const [k] of CAMPOS_TEXTO) ctrl[k] = h('textarea', { maxlength: 10000, value: datos[k] || '' });
  const archivos = h('input', { type: 'file', multiple: true, accept: '.png,.jpg,.jpeg,.pdf,.pptx' });
  const estadoDia = h('div', { class: 'meta' });

  const leer = (est) => ({
    fecha: ctrl.fecha.value, proyecto: ctrl.proyecto.value, tarea_titulo: ctrl.tarea_titulo.value,
    tipo_avance: ctrl.tipo_avance.value, estado_problema: ctrl.estado_problema.value, incluir_ia: ctrl.incluir_ia.checked,
    ...Object.fromEntries(CAMPOS_TEXTO.map(([k]) => [k, ctrl[k].value])), estado: est,
    revision_base: rec ? rec.revision : null,
  });
  form.addEventListener('input', () => { estado.sucio = true; guardarLocal(claveLocal, { ...leer('borrador'), _revision: rec ? rec.revision : null }); });
  const refrescarDia = async () => {
    if (!ctrl.fecha.value) return;
    const [d] = await api('GET', `/api/dias?desde=${ctrl.fecha.value}&hasta=${ctrl.fecha.value}`);
    const regs = await api('GET', `/api/registros?desde=${ctrl.fecha.value}&hasta=${ctrl.fecha.value}`);
    reemplazar(estadoDia, d.registrado ? insignia('ok', d.motivo === 'sin_actividad' ? 'Día declarado sin actividad' : 'Día registrado') : insignia('alerta', 'Día sin registrar'),
      ' ', regs.length ? `${regs.length} registro(s) ese día: ` : '',
      ...regs.map(r => h('a', { href: `#/registro?id=${r.id}`, text: `${r.id}${r.estado === 'borrador' ? ' (borrador)' : ''} ` })));
    sinAct.hidden = d.registrado; quitarSinAct.hidden = !d.sin_actividad;
  };
  ctrl.fecha.addEventListener('change', refrescarDia);

  const subirArchivos = async (registroId) => {
    for (const f of archivos.files) {
      const fd = new FormData(); poner(fd, 'archivo', f); poner(fd, 'registro_id', registroId);
      await accion(() => api('POST', '/api/evidencias', fd), `Evidencia «${f.name}» guardada.`);
    }
  };
  const guardar = async (est) => {
    const body = leer(est);
    const r = await accion(() => rec ? api('PUT', `/api/registros/${rec.id}`, body) : api('POST', '/api/registros', body),
      est === 'guardado' ? 'Registro guardado en esta computadora.' : 'Borrador guardado (no completa el día).');
    if (!r) return; // el texto sigue en el formulario y en el navegador
    for (const ef of r.efectos || []) mensaje(ef, 'alerta');
    await subirArchivos(r.registro.id);
    borrarLocal(claveLocal); estado.sucio = false;
    location.hash = `#/registro?id=${r.registro.id}`;
    if (rec) navegar();
  };
  const sinAct = h('button', { type: 'button', text: 'Hoy no hubo actividad para registrar', onclick: async () => {
    if (await accion(() => api('POST', '/api/dias/sin-actividad', { fecha: ctrl.fecha.value }), 'Día marcado sin actividad.')) refrescarDia();
  } });
  const quitarSinAct = h('button', { type: 'button', text: 'Quitar declaración «sin actividad»', onclick: async () => {
    if (await accion(() => api('POST', '/api/dias/quitar-sin-actividad', { fecha: ctrl.fecha.value }), 'Declaración quitada.')) refrescarDia();
  } });
  form.addEventListener('submit', (ev) => { ev.preventDefault(); guardar('guardado'); });

  poner(form, 
    h('datalist', { id: 'lista-proyectos' }, proy.proyectos.map(x => h('option', { value: x }))),
    h('datalist', { id: 'lista-tareas' }, proy.tareas.map(t => h('option', { value: t.titulo, label: `${t.proyecto} · ${t.id}` }))),
    rec ? h('p', { class: 'meta' }, `ID ${rec.id} · revisión ${rec.revision} · origen ${rec.origen} · `, rec.valido ? insignia('ok', 'válido') : insignia('alerta', rec.estado === 'borrador' ? 'borrador' : 'no válido'),
      rec.archivado ? insignia('error', 'en papelera') : null) : null,
    guardado && (!rec || guardado._revision === rec.revision) ? h('p', { class: 'mensaje alerta', text: 'Se recuperó texto no guardado de este navegador.' }) : null,
    h('div', { class: 'fila2' }, campo('Fecha de actividad *', ctrl.fecha), campo('Proyecto *', ctrl.proyecto),
      campo('Tarea (opcional)', ctrl.tarea_titulo, 'Usá el mismo nombre para vincular avances del mismo trabajo.'),
      campo('Tipo de avance', ctrl.tipo_avance), campo('Estado del problema', ctrl.estado_problema)),
    estadoDia,
    ...CAMPOS_TEXTO.map(([k, et, ay]) => campo(et, ctrl[k], ay)),
    campo('Evidencias opcionales (PNG, JPEG, PDF, PPTX)', archivos, 'Se guardan solo en esta computadora. No se envían a Gemini.'),
    rec && rec.evidencias && rec.evidencias.length ? h('ul', {}, rec.evidencias.map(e => h('li', {}, h('a', { href: `/api/evidencias/${e.id}/archivo`, target: '_blank', rel: 'noopener', text: `${e.id} · ${e.nombre}` })))) : null,
    h('label', {}, ctrl.incluir_ia, ' Incluir en el resumen semanal (podés excluirlo del envío a la IA)'),
    h('div', { class: 'acciones' },
      h('button', { type: 'submit', class: 'primario', text: 'Guardar registro' }),
      h('button', { type: 'button', text: 'Guardar borrador', onclick: () => guardar('borrador') }),
      sinAct, quitarSinAct,
      rec ? h('a', { class: 'boton', href: `/api/registros/${rec.id}/markdown`, text: 'Descargar .md' }) : null,
      rec ? h('a', { class: 'boton', href: '#/registro', text: 'Nuevo registro' }) : null));
  reemplazar(vista, h('h1', { text: rec ? 'Editar registro' : 'Registro diario' }),
    h('p', { class: 'ayuda', text: 'Guardar registro solo guarda en esta computadora: no llama a Gemini ni necesita internet. Un borrador no completa el día.' }), form);
  if (rec && rec.archivado) form.querySelectorAll('input,select,textarea,button[type=submit]').forEach(x => { x.disabled = true; });
  refrescarDia().catch(() => {});
}

// ---------- Historial y documentos ----------
async function vistaHistorial(vista, p) {
  const filtros = { desde: p.get('desde') || sumarDias(hoyISO(), -30), hasta: p.get('hasta') || hoyISO(), proyecto: p.get('proyecto') || '', archivados: p.get('archivados') || 'no' };
  const qs = new URLSearchParams({ desde: filtros.desde, hasta: filtros.hasta, archivados: filtros.archivados });
  if (filtros.proyecto) qs.set('proyecto', filtros.proyecto);
  const [regs, dias, docs, evids] = await Promise.all([
    api('GET', `/api/registros?${qs}`), api('GET', `/api/dias?desde=${sumarDias(hoyISO(), -27)}&hasta=${hoyISO()}`),
    api('GET', '/api/documentos'), api('GET', '/api/evidencias')]);

  const f = {
    desde: h('input', { type: 'date', value: filtros.desde }), hasta: h('input', { type: 'date', value: filtros.hasta }),
    proyecto: h('input', { type: 'text', value: filtros.proyecto }),
    archivados: h('select', {}, [['no', 'Vigentes'], ['si', 'Todos'], ['solo', 'Papelera']].map(([v, t]) => h('option', { value: v, text: t }))),
  };
  f.archivados.value = filtros.archivados;
  const formFiltros = h('form', { class: 'panel', onsubmit: (ev) => { ev.preventDefault();
    location.hash = '#/historial?' + new URLSearchParams({ desde: f.desde.value, hasta: f.hasta.value, proyecto: f.proyecto.value, archivados: f.archivados.value }); } },
  h('div', { class: 'fila2' }, campo('Desde', f.desde), campo('Hasta', f.hasta), campo('Proyecto', f.proyecto), campo('Mostrar', f.archivados)),
  h('button', { type: 'submit', class: 'primario', text: 'Filtrar' }));

  const tira = h('div', { class: 'panel' }, h('h2', { text: 'Últimas 4 semanas' }),
    h('div', { class: 'tira' }, dias.map(d => h('a', { href: `#/registro?fecha=${d.fecha}`, title: `${fechaLocal(d.fecha)}: ${d.registrado ? (d.motivo === 'sin_actividad' ? 'sin actividad' : 'registrado') : 'sin registro'}` },
      h('span', { class: d.registrado ? (d.motivo === 'sin_actividad' ? 'sa' : 'si') : 'no', text: d.fecha.slice(8) })))),
    h('p', { class: 'ayuda', text: 'Verde: registrado · Azul: sin actividad declarada · Rojo: sin registro (incluye fines de semana).' }));

  const lista = h('ul', { class: 'lista' });
  for (const r of regs) {
    const revs = h('div');
    poner(lista, h('li', {},
      h('div', {}, h('strong', { text: `${fechaLocal(r.fecha)} · ${r.proyecto || '(sin proyecto)'}` }), ' ',
        r.valido ? insignia('ok', 'válido') : insignia('alerta', r.estado), r.archivado ? insignia('error', 'papelera') : null,
        !r.incluir_ia ? insignia('', 'excluido del resumen') : null, insignia('info', TIPO_AVANCE[r.tipo_avance]),
        r.estado_problema !== 'sin_problema' ? insignia(r.estado_problema === 'resuelto' ? 'ok' : 'alerta', `Problema: ${EST_PROBLEMA[r.estado_problema]}`) : null),
      h('div', { text: r.actividad.slice(0, 280) }),
      h('div', { class: 'meta', text: `${r.id} · rev. ${r.revision}${r.tarea_titulo ? ' · Tarea: ' + r.tarea_titulo : ''} · origen ${r.origen}` }),
      h('div', { class: 'acciones' },
        !r.archivado ? h('a', { class: 'boton', href: `#/registro?id=${r.id}`, text: 'Editar' }) : null,
        h('button', { type: 'button', text: 'Revisiones', onclick: async () => {
          const rv = await api('GET', `/api/registros/${r.id}/revisiones`);
          reemplazar(revs, h('table', {}, h('tr', {}, h('th', { text: 'Rev.' }), h('th', { text: 'Motivo' }), h('th', { text: 'Fecha' }), h('th', { text: 'Actividad' })),
            rv.map(x => h('tr', {}, h('td', { text: x.revision }), h('td', { text: x.motivo }), h('td', { text: momento(x.creado_utc) }), h('td', { text: (x.datos.actividad || '').slice(0, 120) })))));
        } }),
        h('a', { class: 'boton', href: `/api/registros/${r.id}/markdown`, text: '.md' }),
        !r.archivado ? h('button', { type: 'button', text: r.incluir_ia ? 'Excluir del resumen' : 'Incluir en resumen', onclick: async () => {
          if (await accion(() => api('POST', `/api/registros/${r.id}/incluir-ia`, { incluir: !r.incluir_ia }), 'Actualizado.')) navegar(); } }) : null,
        !r.archivado ? h('button', { type: 'button', text: 'Mandar a la papelera', onclick: async () => {
          if (confirm('¿Mandar este registro a la papelera? Podés restaurarlo después.') && await accion(() => api('POST', `/api/registros/${r.id}/archivar`), 'Enviado a la papelera.')) navegar(); } })
          : h('button', { type: 'button', text: 'Restaurar', onclick: async () => { if (await accion(() => api('POST', `/api/registros/${r.id}/restaurar`), 'Restaurado.')) navegar(); } }),
        r.archivado ? h('button', { type: 'button', class: 'peligro', text: 'Eliminar definitivamente', onclick: async () => {
          if (confirm('Esto borra el registro y sus revisiones de esta computadora y no se puede deshacer. ¿Continuar?') &&
            await accion(() => api('POST', `/api/registros/${r.id}/eliminar-definitivo`), 'Eliminado definitivamente.')) navegar(); } }) : null),
      revs));
  }
  const pRegs = h('div', { class: 'panel' }, h('h2', { text: `Registros (${regs.length})` }), regs.length ? lista : h('p', { class: 'meta', text: 'No hay registros con esos filtros.' }));

  const listaDocs = h('ul', { class: 'lista' });
  for (const d of docs) {
    const [cls, txt] = EST_DOC[d.estado] || ['', d.estado];
    const item = h('li', {}, h('div', {}, h('strong', { text: d.ruta_relativa }), ' ', insignia(cls, txt), !d.origen_presente ? insignia('error', 'quitado de la carpeta') : null),
      d.motivo ? h('div', { class: 'meta', text: d.motivo }) : null,
      h('div', { class: 'meta', text: `${d.id} · versión ${d.version}${d.registro_id ? ' · registro ' + d.registro_id : ''}${d.evidencia_id ? ' · evidencia ' + d.evidencia_id : ''} · ${momento(d.actualizado_utc)}` }));
    if (d.extracto) poner(item, h('details', {}, h('summary', { text: 'Ver extracto' }), h('pre', { class: 'diff', text: d.extracto })));
    if (d.estado === 'pendiente_clasificar') {
      const fc = h('input', { type: 'date', required: true, value: d.metadatos.fecha && /^\d{4}-\d{2}-\d{2}$/.test(d.metadatos.fecha) ? d.metadatos.fecha : '' });
      const pc = h('input', { type: 'text', required: true, maxlength: 120, value: d.metadatos.proyecto || '', list: 'lista-proy-hist' });
      const tc = h('input', { type: 'text', maxlength: 200, value: d.metadatos.tarea_titulo || '' });
      poner(item, h('form', { class: 'acciones', onsubmit: async (ev) => { ev.preventDefault();
        if (await accion(() => api('POST', `/api/documentos/${d.id}/clasificar`, { fecha: fc.value, proyecto: pc.value, tarea_titulo: tc.value }), 'Documento clasificado: se creó el registro.')) navegar(); } },
      campo('Fecha de actividad', fc), campo('Proyecto', pc), campo('Tarea', tc), h('button', { type: 'submit', class: 'primario', text: 'Confirmar clasificación' })));
    }
    const acts = h('div', { class: 'acciones' });
    if (d.registro_id) poner(acts, h('a', { class: 'boton', href: `#/registro?id=${d.registro_id}`, text: 'Ver registro' }));
    if (!d.origen_presente && d.registro_id) poner(acts, h('button', { type: 'button', text: 'Archivar el registro importado', onclick: async () => {
      if (confirm('¿Mandar a la papelera el registro importado desde este archivo?') && await accion(() => api('POST', `/api/documentos/${d.id}/archivar-registro`), 'Registro archivado.')) navegar(); } }));
    if (['pendiente_clasificar', 'error', 'duplicado', 'conflicto'].includes(d.estado)) poner(acts, h('button', { type: 'button', text: 'Ignorar', onclick: async () => {
      if (await accion(() => api('POST', `/api/documentos/${d.id}/ignorar`), 'Ignorado.')) navegar(); } }));
    poner(item, acts);
    poner(listaDocs, item);
  }
  const pDocs = h('div', { class: 'panel' }, h('h2', { text: 'Documentos de la carpeta de entrada' }),
    h('datalist', { id: 'lista-proy-hist' }),
    h('div', { class: 'acciones' }, h('button', { type: 'button', text: 'Reescanear carpeta', onclick: async () => { if (await accion(() => api('POST', '/api/documentos/reescanear'), (x) => x.estado === 'inactiva' ? 'La carpeta de entrada no está activa (Configuración).' : `Reescaneo listo (${x.procesados} archivo/s).`)) navegar(); } })),
    docs.length ? listaDocs : h('p', { class: 'meta', text: 'Sin documentos. Configurá una carpeta de entrada en Configuración.' }));

  const listaEv = h('ul', { class: 'lista' });
  for (const e of evids) {
    const regIn = h('input', { type: 'text', placeholder: 'REG-XXXXXXXX', value: e.registro_id || '', maxlength: 12, 'aria-label': 'Registro a vincular' });
    poner(listaEv, h('li', {}, h('strong', { text: `${e.id} · ${e.nombre}` }), h('div', { class: 'meta', text: `${e.mime} · ${(e.tamano / 1024).toFixed(0)} KB · ${e.registro_id ? 'registro ' + e.registro_id : 'sin registro'} · origen ${e.origen}` }),
      e.mime.startsWith('image/') ? h('img', { class: 'miniatura', src: `/api/evidencias/${e.id}/archivo`, alt: `Evidencia ${e.nombre}` }) : null,
      h('div', { class: 'acciones' }, h('a', { class: 'boton', href: `/api/evidencias/${e.id}/archivo`, target: '_blank', rel: 'noopener', text: 'Abrir' }), regIn,
        h('button', { type: 'button', text: 'Vincular', onclick: async () => { if (await accion(() => api('POST', `/api/evidencias/${e.id}/vincular`, { registro_id: regIn.value.trim() || null }), 'Vínculo actualizado.')) navegar(); } }))));
  }
  const pEv = h('div', { class: 'panel' }, h('h2', { text: 'Evidencias locales' }), h('p', { class: 'ayuda', text: 'Las imágenes y archivos nunca se envían a Gemini. Para usarlos en Claude, adjuntalos a mano.' }),
    evids.length ? listaEv : h('p', { class: 'meta', text: 'Sin evidencias.' }));
  reemplazar(vista, h('h1', { text: 'Historial y documentos' }), formFiltros, tira, pRegs, pDocs, pEv);
}

// ---------- Resumen y prompt ----------
async function vistaPrompt(vista, p) {
  const ref = p.get('ref') || '';
  const q = ref ? `?ref=${ref}` : '';
  const d = await api('GET', `/api/prompt${q}`);
  const st = d.estado; const per = st.periodo;
  const versiones = await api('GET', `/api/prompt/versiones?periodo=${per.clave}`);
  const regs = await api('GET', `/api/registros?desde=${per.inicio}&hasta=${per.fin}`);
  const refIn = h('input', { type: 'date', value: ref || hoyISO() });
  const cabecera = h('div', { class: 'panel' },
    h('div', { class: 'acciones' }, campo('Semana o período que contiene la fecha', refIn), h('button', { type: 'button', text: 'Ver período', onclick: () => { location.hash = `#/prompt?ref=${refIn.value}`; } })),
    h('h2', {}, `Período ${per.etiqueta} `, insignia(...EST_PROMPT[st.estado] || ['', st.estado])),
    h('p', { class: 'meta', text: `${st.mensaje} · Modo: ${st.modo_etiqueta} · ${st.registros} registro(s) incluidos, ${st.excluidos.length} excluido(s), ${st.evidencias} evidencia(s).` }),
    per.cierre_local ? h('p', { class: 'meta', text: `Cierre programado: ${momento(per.cierre_local)}` }) : null,
    h('div', { class: 'acciones' },
      h('button', { type: 'button', class: 'primario', text: 'Actualizar prompt', onclick: async () => {
        const r = await accion(() => api('POST', '/api/prompt/actualizar', { ref: ref || null }), (x) => x.mensaje); if (r) setTimeout(navegar, 600); } }),
      h('button', { type: 'button', text: 'Regenerar aunque no haya cambios', onclick: async () => {
        const r = await accion(() => api('POST', '/api/prompt/actualizar', { ref: ref || null, forzar: true }), (x) => x.mensaje); if (r) setTimeout(navegar, 600); } }),
      h('button', { type: 'button', class: 'primario', text: 'Preparar para Claude', onclick: async () => {
        const r = await accion(() => api('POST', '/api/preparar', { ref: ref || null }), (x) => x.mensaje); if (r) navegar(); } }),
      h('button', { type: 'button', text: 'Recargar estado', onclick: navegar })),
    h('p', { class: 'ayuda', text: '«Actualizar prompt» regenera el borrador si hay cambios. «Preparar para Claude» crea una instantánea para copiar. Ninguno envía nada a Claude ni genera la presentación: eso lo hacés vos en Claude.' }));
  if (st.trabajos.length) poner(cabecera, h('details', {}, h('summary', { text: 'Trabajos recientes de la cola' }),
    h('table', {}, st.trabajos.map(t => h('tr', {}, h('td', { text: `#${t.id}` }), h('td', { text: t.motivo }), h('td', { text: t.estado }), h('td', { text: t.error_mensaje || '' }), h('td', { text: momento(t.actualizado_utc) }))))));

  const borr = d.borrador;
  const pBorr = h('div', { class: 'panel' }, h('h2', { text: 'Borrador automático' }));
  if (borr) {
    poner(pBorr, h('p', { class: 'meta', text: `${borr.id} · ${borr.modo}${borr.es_respaldo ? ' (respaldo)' : ''} · ${momento(borr.creado_utc)} · fuentes: ${borr.fuentes.map(f => f.id).join(', ')}` }),
      borr.advertencias.length ? h('details', {}, h('summary', { text: `Notas de validación (${borr.advertencias.length})` }), h('ul', {}, borr.advertencias.map(a => h('li', { text: a })))) : null,
      markdown(borr.contenido),
      h('div', { class: 'acciones' }, h('button', { type: 'button', text: 'Copiar prompt', onclick: () => copiar(borr.contenido) }),
        h('a', { class: 'boton', href: `/api/prompt/versiones/${borr.id}/descargar?formato=md`, text: 'Descargar .md' }),
        h('a', { class: 'boton', href: `/api/prompt/versiones/${borr.id}/descargar?formato=txt`, text: 'Descargar .txt' }), enlaceClaude()));
  } else poner(pBorr, h('p', { class: 'meta', text: 'Todavía no hay borrador para este período. Usá «Actualizar prompt».' }));

  const mi = d.mi_version;
  const area = h('textarea', { class: 'grande', value: mi ? mi.contenido : (borr ? borr.contenido : '') });
  area.addEventListener('input', () => { estado.sucio = true; guardarLocal(`bitacora-prompt-${per.clave}`, area.value); });
  const local = leerLocal(`bitacora-prompt-${per.clave}`);
  if (local && local !== area.value) { area.value = local; }
  const pMi = h('div', { class: 'panel' }, h('h2', { text: 'Mi versión editada' }),
    mi ? h('p', { class: 'meta', text: `${mi.id} · ${momento(mi.creado_utc)} · ${mi.nota}` }) : h('p', { class: 'meta', text: 'Aún no editaste una versión propia. Tus ediciones nunca se sobrescriben con borradores nuevos.' }),
    d.mi_version_desactualizada ? h('p', { class: 'mensaje alerta', text: 'Hay un borrador nuevo con datos más recientes que tu versión. Revisalo y, si querés, reemplazá tu versión (la actual queda guardada en el historial). No se hace fusión automática.' }) : null,
    local && local !== (mi ? mi.contenido : '') ? h('p', { class: 'meta', text: 'Se recuperó texto no guardado de este navegador.' }) : null,
    campo('Contenido', area),
    h('div', { class: 'acciones' },
      h('button', { type: 'button', class: 'primario', disabled: !borr, text: 'Guardar mi versión', onclick: async () => {
        const r = await accion(() => api('POST', '/api/prompt/manual', { periodo: per.clave, contenido: area.value, base_version_id: borr ? borr.id : null }), 'Tu versión quedó guardada (la anterior se conserva).');
        if (r) { borrarLocal(`bitacora-prompt-${per.clave}`); estado.sucio = false; navegar(); } } }),
      borr && mi ? h('button', { type: 'button', text: 'Reemplazar mi versión por el borrador', onclick: async () => {
        if (!confirm('Tu versión actual queda en el historial. ¿Reemplazarla por el borrador automático?')) return;
        const r = await accion(() => api('POST', `/api/prompt/versiones/${borr.id}/recuperar`), 'Reemplazada. Podés recuperar la anterior desde Versiones.');
        if (r) { borrarLocal(`bitacora-prompt-${per.clave}`); estado.sucio = false; navegar(); } } }) : null,
      h('button', { type: 'button', text: 'Copiar', onclick: () => copiar(area.value) }), enlaceClaude()));

  const pCierres = h('div', { class: 'panel' }, h('h2', { text: 'Instantáneas «Preparar para Claude» y cierres' }));
  if (!d.cierres.length) poner(pCierres, h('p', { class: 'meta', text: 'Sin instantáneas para este período.' }));
  const ulC = h('ul', { class: 'lista' });
  for (const c of d.cierres) {
    const li = h('li', {}, h('div', {}, h('strong', { text: `${c.id} · ${c.disparo === 'programado' ? 'Cierre programado' : 'Preparado manualmente'}` }), ' ',
      insignia(...EST_CIERRE[c.estado] || ['', c.estado]), c.cambios_posteriores ? insignia('alerta', 'Hay cambios posteriores al cierre') : null),
    h('div', { class: 'meta', text: `${momento(c.creado_utc)} · ${c.mensaje}` }));
    const acts = h('div', { class: 'acciones' });
    if (c.version_id) {
      poner(acts, h('button', { type: 'button', text: 'Copiar prompt', onclick: async () => { const v = await api('GET', `/api/prompt/versiones/${c.version_id}`); copiar(v.contenido); } }),
        h('a', { class: 'boton', href: `/api/prompt/versiones/${c.version_id}/descargar?formato=md`, text: '.md' }),
        h('a', { class: 'boton', href: `/api/prompt/versiones/${c.version_id}/descargar?formato=txt`, text: '.txt' }), enlaceClaude());
    }
    if (c.estado === 'pendiente' || c.estado === 'error') {
      poner(acts, h('button', { type: 'button', text: 'Reintentar con Gemini', onclick: async () => { if (await accion(() => api('POST', `/api/cierres/${c.id}/reintentar`), 'Reintento en curso.')) navegar(); } }),
        h('button', { type: 'button', text: 'Usar plantilla sin IA (respaldo)', onclick: async () => { if (await accion(() => api('POST', `/api/cierres/${c.id}/respaldo`), 'Prompt de respaldo listo (identificado como tal).')) navegar(); } }));
    }
    if (c.cambios_posteriores) poner(acts, h('button', { type: 'button', class: 'primario', text: 'Crear otra versión', onclick: async () => { if (await accion(() => api('POST', '/api/preparar', { ref: per.inicio }), 'Nueva instantánea en preparación.')) navegar(); } }));
    poner(li, acts);
    if (c.version_id) {
      const ref2 = h('input', { type: 'text', maxlength: 500, value: c.presentacion_ref || '', placeholder: 'Enlace o nota de la presentación terminada' });
      poner(li, h('details', {}, h('summary', { text: c.presentacion_ref ? `Presentación registrada: ${c.presentacion_ref}` : 'Registrar la presentación terminada (opcional)' }),
        h('form', { class: 'acciones', onsubmit: async (ev) => { ev.preventDefault();
          if (await accion(() => api('POST', `/api/cierres/${c.id}/presentacion`, { version_usada_id: c.version_id, referencia: ref2.value }), 'Referencia guardada.')) navegar(); } },
        campo('Referencia', ref2), h('button', { type: 'submit', text: 'Guardar referencia' }))));
    }
    poner(ulC, li);
  }
  poner(pCierres, ulC);

  const pVers = h('div', { class: 'panel' }, h('h2', { text: `Versiones (${versiones.length})` }));
  const verDiff = h('div');
  const ulV = h('ul', { class: 'lista' });
  for (const v of versiones) {
    poner(ulV, h('li', {}, h('strong', { text: `${v.id} · ${v.tipo_texto}` }), ' ', v.es_respaldo ? insignia('alerta', 'respaldo sin IA') : null,
      h('div', { class: 'meta', text: `${momento(v.creado_utc)} · ${v.modo} · hash ${v.hash_entrada.slice(0, 10)} · fuentes ${v.fuentes.length}${v.nota ? ' · ' + v.nota : ''}` }),
      h('div', { class: 'acciones' },
        h('button', { type: 'button', text: 'Ver', onclick: async () => { const x = await api('GET', `/api/prompt/versiones/${v.id}`); reemplazar(verDiff, h('h3', { text: v.id }), markdown(x.contenido)); verDiff.scrollIntoView(); } }),
        borr && borr.id !== v.id ? h('button', { type: 'button', text: 'Diferencias con el borrador actual', onclick: async () => {
          const x = await api('GET', `/api/prompt/diferencias?a=${v.id}&b=${borr.id}`); reemplazar(verDiff, h('h3', { text: `${v.id} → ${borr.id}` }), h('pre', { class: 'diff', text: x.diff })); verDiff.scrollIntoView(); } }) : null,
        h('button', { type: 'button', text: 'Recuperar como copia', onclick: async () => { if (await accion(() => api('POST', `/api/prompt/versiones/${v.id}/recuperar`), 'Recuperada como «mi versión editada».')) navegar(); } }),
        h('a', { class: 'boton', href: `/api/prompt/versiones/${v.id}/descargar?formato=md`, text: 'Descargar' }))));
  }
  poner(pVers, versiones.length ? ulV : h('p', { class: 'meta', text: 'Sin versiones.' }), verDiff);

  const pFuentes = h('div', { class: 'panel' }, h('h2', { text: 'Registros del período (revisá qué se incluye)' }),
    h('ul', { class: 'lista' }, regs.filter(r => r.valido).map(r => h('li', {}, h('label', {},
      h('input', { type: 'checkbox', checked: r.incluir_ia, onchange: async (ev) => { if (!await accion(() => api('POST', `/api/registros/${r.id}/incluir-ia`, { incluir: ev.target.checked }), 'Actualizado.')) ev.target.checked = !ev.target.checked; } }),
      ` ${fechaLocal(r.fecha)} · ${r.proyecto} · ${r.actividad.slice(0, 120)} (${r.id})`)))),
    h('button', { type: 'button', text: 'Ver exactamente qué texto se enviaría a Gemini', onclick: async () => {
      const x = await api('GET', `/api/ia/vista-previa${q}`);
      poner(pFuentes, h('p', { class: 'ayuda', text: x.nota }), h('pre', { class: 'diff', text: x.texto }));
    } }));
  reemplazar(vista, h('h1', { text: 'Resumen y prompt para Claude' }),
    h('p', { class: 'mensaje alerta', text: 'Esta pantalla prepara el PROMPT. La presentación no se genera aquí: copiá el prompt en Claude, donde ya tenés el diseño configurado.' }),
    cabecera, pBorr, pMi, pCierres, pFuentes, pVers);
  if (st.estado === 'actualizando') estado.temporizador = setInterval(async () => {
    const x = await api('GET', `/api/prompt${q}`).catch(() => null);
    if (x && x.estado.estado !== 'actualizando' && !estado.sucio) navegar();
  }, 4000);
}

// ---------- Configuración ----------
function calendarioExcepciones(seleccion, alCambiar) {
  let mes = new Date(); mes.setDate(1);
  const caja = h('div');
  const pintar = () => {
    const y = mes.getFullYear(); const m = mes.getMonth();
    const primero = (new Date(y, m, 1).getDay() + 6) % 7;
    const dias = new Date(y, m + 1, 0).getDate();
    const grilla = h('div', { class: 'calendario', role: 'group', 'aria-label': 'Fechas de excepción' }, DIAS.map(d => h('div', { class: 'cab', text: d })));
    for (let i = 0; i < primero; i++) poner(grilla, h('div'));
    for (let d = 1; d <= dias; d++) {
      const iso = `${y}-${String(m + 1).padStart(2, '0')}-${String(d).padStart(2, '0')}`;
      poner(grilla, h('button', { type: 'button', text: d, 'aria-pressed': seleccion.has(iso) ? 'true' : 'false', 'aria-label': `${fechaLocal(iso)}${seleccion.has(iso) ? ' (excepción)' : ''}`,
        onclick: () => { if (seleccion.has(iso)) seleccion.delete(iso); else seleccion.add(iso); alCambiar(); pintar(); } }));
    }
    reemplazar(caja, h('div', { class: 'acciones' },
      h('button', { type: 'button', text: '◀', 'aria-label': 'Mes anterior', onclick: () => { mes.setMonth(mes.getMonth() - 1); pintar(); } }),
      h('strong', { text: mes.toLocaleDateString('es-AR', { month: 'long', year: 'numeric' }) }),
      h('button', { type: 'button', text: '▶', 'aria-label': 'Mes siguiente', onclick: () => { mes.setMonth(mes.getMonth() + 1); pintar(); } })), grilla,
    h('p', { class: 'meta', text: seleccion.size ? `Excepciones: ${[...seleccion].sort().map(fechaLocal).join(', ')}` : 'Sin excepciones.' }));
  };
  pintar();
  return caja;
}

async function vistaConfig(vista) {
  const cfg = await api('GET', '/api/config');
  const info = cfg._info;
  const guardarSeccion = async (sec, datos) => {
    const r = await accion(() => api('PUT', `/api/config/${sec}`, datos), 'Configuración guardada. Afecta a las próximas ejecuciones.');
    if (r && r._advertencia_cierre) mensaje(r._advertencia_cierre, 'alerta', 15000);
    return r;
  };

  // Recordatorios
  const rc = cfg.recordatorio;
  const dias = new Set(rc.dias);
  const excepciones = new Set(rc.excepciones);
  const puntuales = [...rc.puntuales];
  const botonesDias = h('div', { class: 'dias', role: 'group', 'aria-label': 'Días con recordatorio' },
    DIAS_LARGO.map((d, i) => h('button', { type: 'button', text: d, 'aria-pressed': dias.has(i) ? 'true' : 'false',
      onclick: (ev) => { if (dias.has(i)) dias.delete(i); else dias.add(i); ev.target.setAttribute('aria-pressed', dias.has(i) ? 'true' : 'false'); } })));
  const hora = h('input', { type: 'time', value: rc.hora });
  const zona = h('input', { type: 'text', value: rc.zona, list: 'zonas' });
  const pausado = h('input', { type: 'checkbox', checked: rc.pausado });
  const pausaHasta = h('input', { type: 'date', value: rc.pausa_hasta || '' });
  const posponer = h('input', { type: 'number', min: 5, max: 120, value: rc.posponer_minutos });
  const listaPunt = h('ul');
  const pFecha = h('input', { type: 'date', value: hoyISO() }); const pHora = h('input', { type: 'time', value: '18:00' });
  const pintarPunt = () => reemplazar(listaPunt, ...puntuales.map((x, i) => h('li', {}, `${fechaLocal(x.fecha)} ${x.hora} `,
    h('button', { type: 'button', text: 'Quitar', onclick: () => { puntuales.splice(i, 1); pintarPunt(); } }))));
  pintarPunt();
  const pRec = h('div', { class: 'panel' }, h('h2', { text: 'Recordatorio diario' }),
    h('datalist', { id: 'zonas' }, ['America/Argentina/Buenos_Aires', 'America/Montevideo', 'America/Santiago', 'America/Bogota', 'America/Mexico_City', 'Europe/Madrid', 'UTC'].map(z => h('option', { value: z }))),
    h('div', { class: 'etiqueta', text: 'Días' }), botonesDias,
    h('div', { class: 'fila2' }, campo('Hora', hora), campo('Zona horaria', zona, 'Formato IANA, p. ej. America/Argentina/Buenos_Aires'), campo('Posponer (minutos)', posponer)),
    h('label', {}, pausado, ' Pausar recordatorios'), campo('Pausa hasta (opcional, inclusive)', pausaHasta),
    h('h3', { text: 'Fechas de excepción (sin recordatorio)' }), calendarioExcepciones(excepciones, () => {}),
    h('h3', { text: 'Recordatorios puntuales' }), listaPunt,
    h('div', { class: 'acciones' }, pFecha, pHora, h('button', { type: 'button', text: 'Agregar puntual', onclick: () => { if (pFecha.value && pHora.value) { puntuales.push({ fecha: pFecha.value, hora: pHora.value }); pintarPunt(); } } })),
    h('div', { class: 'acciones' }, h('button', { type: 'button', class: 'primario', text: 'Guardar recordatorios', onclick: () => guardarSeccion('recordatorio', {
      dias: [...dias], hora: hora.value, zona: zona.value, pausado: pausado.checked, pausa_hasta: pausaHasta.value || null,
      excepciones: [...excepciones], puntuales, posponer_minutos: Number(posponer.value) }) })));

  // Presentación
  const pc = cfg.presentacion;
  const periodo = h('select', {}, [['semana_laboral', 'Semana laboral (lun–vie)'], ['semana_completa', 'Semana completa (lun–dom)'], ['personalizado', 'Personalizado']].map(([v, t]) => h('option', { value: v, text: t })));
  periodo.value = pc.periodo;
  const inicio = h('input', { type: 'date', value: pc.inicio || '' }); const fin = h('input', { type: 'date', value: pc.fin || '' });
  const diaCierre = h('select', {}, DIAS_LARGO.map((d, i) => h('option', { value: i, text: d }))); diaCierre.value = pc.dia_cierre;
  const horaCierre = h('input', { type: 'time', value: pc.hora_cierre });
  const fechaCierre = h('input', { type: 'date', value: pc.fecha_cierre || '' });
  const cierreActivo = h('input', { type: 'checkbox', checked: pc.cierre_activo });
  const proyectos = h('input', { type: 'text', value: pc.proyectos.join(', ') });
  const audiencia = h('input', { type: 'text', maxlength: 200, value: pc.audiencia });
  const maxDiap = h('input', { type: 'number', min: 1, max: 20, value: pc.max_diapositivas });
  const pPres = h('div', { class: 'panel' }, h('h2', { text: 'Período de presentación y cierre' }),
    h('div', { class: 'fila2' }, campo('Período', periodo), campo('Inicio (personalizado)', inicio), campo('Fin (personalizado)', fin),
      campo('Día de cierre (semanal)', diaCierre), campo('Hora de cierre', horaCierre), campo('Fecha de cierre (personalizado)', fechaCierre, 'Si queda vacía, se usa la fecha de fin.'),
      campo('Proyectos incluidos', proyectos, 'Separados por coma. Vacío = todos.'), campo('Audiencia', audiencia), campo('Máximo de diapositivas', maxDiap)),
    h('label', {}, cierreActivo, ' Cierre programado activo (prepara el prompt y avisa; no envía nada a Claude)'),
    info.advertencia_cierre ? h('p', { class: 'mensaje alerta', text: info.advertencia_cierre }) : null,
    h('div', { class: 'acciones' }, h('button', { type: 'button', class: 'primario', text: 'Guardar período', onclick: () => guardarSeccion('presentacion', {
      periodo: periodo.value, inicio: inicio.value || null, fin: fin.value || null, dia_cierre: Number(diaCierre.value), hora_cierre: horaCierre.value,
      fecha_cierre: fechaCierre.value || null, cierre_activo: cierreActivo.checked, proyectos: proyectos.value.split(',').map(s => s.trim()).filter(Boolean),
      audiencia: audiencia.value, max_diapositivas: Number(maxDiap.value) }) })));

  // IA
  const ic = cfg.ia;
  const modo = h('select', {}, [['plantilla', 'Sin IA (plantilla)'], ['gemini', 'Gemini'], ['demo', 'Demostración (simulado)']].map(([v, t]) => h('option', { value: v, text: t })));
  modo.value = ic.modo;
  const num = (v, min, max) => h('input', { type: 'number', min, max, value: v });
  const iaCampos = { pausada: h('input', { type: 'checkbox', checked: ic.pausada }), espera_segundos: num(ic.espera_segundos, 10, 3600),
    max_intentos_diarios: num(ic.max_intentos_diarios, 1, 500), timeout_segundos: num(ic.timeout_segundos, 10, 300),
    max_caracteres_entrada: num(ic.max_caracteres_entrada, 2000, 400000), max_tokens_salida: num(ic.max_tokens_salida, 512, 32768),
    reintentos_transitorios: num(ic.reintentos_transitorios, 0, 5) };
  const pIA = h('div', { class: 'panel' }, h('h2', { text: 'Inteligencia artificial (Gemini)' }),
    h('p', { class: 'meta', text: `Modelo: ${info.modelo} · Clave: ${info.clave_configurada ? 'configurada en .env (no se muestra)' : 'no configurada'}${info.demo ? ' · MODO DEMO: no se usa Gemini' : ''}` }),
    h('details', { open: !ic.consentimiento }, h('summary', { text: 'Qué se envía a Gemini y consentimiento' }),
      h('ul', {}, h('li', { text: 'Se envía solo el texto de los registros válidos del período que marcaste como incluidos (fecha, proyecto, tarea, actividad, avance, problemas, solución, próximos pasos, IDs) y los nombres de las evidencias.' }),
        h('li', { text: 'Nunca se envían adjuntos, imágenes, carpetas completas, la clave ni la configuración.' }),
        h('li', { text: 'En el nivel gratuito, Google puede usar el contenido para mejorar sus productos según sus condiciones. No uses esta opción para información confidencial de la empresa.' }),
        h('li', { text: 'La app no habilita facturación ni cambia de modelo. Si tu cuenta de Google tiene facturación activa, la app no puede garantizar que el uso sea gratuito.' }),
        h('li', { text: 'Borrar datos locales no borra lo que ya se haya enviado al proveedor.' })),
      ic.consentimiento ? h('p', {}, insignia('ok', `Consentimiento otorgado ${momento(ic.consentimiento_utc)}`), ' ',
        h('button', { type: 'button', text: 'Retirar consentimiento', onclick: async () => { if (await accion(() => api('POST', '/api/ia/consentimiento', { acepto: false }), 'Consentimiento retirado: modo sin IA.')) navegar(); } }))
        : h('button', { type: 'button', class: 'primario', disabled: info.demo, text: 'Entiendo y acepto enviar ese texto a Gemini', onclick: async () => { if (await accion(() => api('POST', '/api/ia/consentimiento', { acepto: true }), 'Consentimiento registrado. Ahora podés elegir el modo Gemini.')) navegar(); } })),
    h('div', { class: 'fila2' }, campo('Modo', modo, 'Sin IA: arma el prompt con una plantilla, sin conexión.'),
      campo('Espera para agrupar cambios (s)', iaCampos.espera_segundos), campo('Máx. llamadas diarias a Gemini', iaCampos.max_intentos_diarios),
      campo('Tiempo máximo de respuesta (s)', iaCampos.timeout_segundos), campo('Máx. caracteres de entrada', iaCampos.max_caracteres_entrada),
      campo('Máx. tokens de salida', iaCampos.max_tokens_salida), campo('Reintentos ante errores transitorios', iaCampos.reintentos_transitorios)),
    h('label', {}, iaCampos.pausada, ' Pausar IA (no se llama a Gemini)'),
    h('div', { class: 'acciones' }, h('button', { type: 'button', class: 'primario', text: 'Guardar IA', onclick: async () => {
      const datos = { modo: modo.value, pausada: iaCampos.pausada.checked };
      for (const k of Object.keys(iaCampos)) if (k !== 'pausada') datos[k] = Number(iaCampos[k].value);
      if (await guardarSeccion('ia', datos)) navegar(); } })));

  // Carpeta de entrada y límites
  const en = cfg.entrada;
  const carpeta = h('input', { type: 'text', value: en.carpeta || '', placeholder: info.carpeta_sugerida, class: 'ancho' });
  const activa = h('input', { type: 'checkbox', checked: en.activa });
  const lm = cfg.limites;
  const lim = { texto_mb: num(lm.texto_mb, 0.1, 20), documento_mb: num(lm.documento_mb, 0.1, 50), pdf_paginas: num(lm.pdf_paginas, 1, 500),
    max_caracteres_extraidos: num(lm.max_caracteres_extraidos, 1000, 2000000), docx_descomprimido_mb: num(lm.docx_descomprimido_mb, 1, 200) };
  lim.texto_mb.step = '0.1'; lim.documento_mb.step = '0.1';
  const pEnt = h('div', { class: 'panel' }, h('h2', { text: 'Carpeta de entrada' }),
    h('p', { class: 'ayuda', text: 'Elegí una carpeta exclusiva. Se aceptan .txt, .md, .json, .docx y .pdf con texto seleccionable (sin OCR) e imágenes .png/.jpg como evidencias. Los originales no se modifican. Ver plantillas en la carpeta «ejemplos» del proyecto.' }),
    campo('Ruta completa de la carpeta', carpeta, `Sugerida: ${info.carpeta_sugerida}`), h('label', {}, activa, ' Supervisar esta carpeta'),
    h('div', { class: 'acciones' },
      h('button', { type: 'button', class: 'primario', text: 'Guardar carpeta', onclick: async () => { if (await guardarSeccion('entrada', { carpeta: carpeta.value.trim() || null, activa: activa.checked })) navegar(); } }),
      h('button', { type: 'button', text: 'Crear y usar la carpeta sugerida', onclick: async () => { if (await accion(() => api('POST', '/api/config/carpeta-sugerida'), (x) => `Carpeta activa: ${x.carpeta}`)) navegar(); } })),
    h('h3', { text: 'Límites de archivos' }),
    h('div', { class: 'fila2' }, campo('Texto/JSON (MB)', lim.texto_mb), campo('Documentos y evidencias (MB)', lim.documento_mb), campo('Páginas de PDF', lim.pdf_paginas),
      campo('Caracteres extraídos', lim.max_caracteres_extraidos), campo('DOCX descomprimido (MB)', lim.docx_descomprimido_mb)),
    h('button', { type: 'button', text: 'Guardar límites', onclick: () => guardarSeccion('limites', Object.fromEntries(Object.entries(lim).map(([k, v]) => [k, Number(v.value)]))) }));

  // Notificaciones, copias y sistema
  const resNotif = h('p', { class: 'meta' });
  const listaCopias = h('ul');
  const pintarCopias = async () => { const c = await api('GET', '/api/copias'); reemplazar(listaCopias, ...(c.length ? c.map(x => h('li', { text: `${x.nombre} (${(x.tamano / 1024).toFixed(0)} KB)` })) : [h('li', { text: 'Sin copias todavía.' })])); };
  const pSis = h('div', { class: 'panel' }, h('h2', { text: 'Notificaciones, copias y datos' }),
    h('button', { type: 'button', text: 'Probar notificación de Windows', onclick: async () => {
      const r = await accion(() => api('POST', '/api/notificaciones/probar'));
      if (r) resNotif.textContent = `Resultado: ${ENTREGA[r.entrega] || r.entrega} ${r.detalle || ''} Confirmá vos si la viste en pantalla.`; } }), resNotif,
    h('h3', { text: 'Copia de seguridad' }),
    h('p', { class: 'ayuda', text: `Los datos están en ${info.carpeta_datos} (sin cifrar). La copia incluye base de datos, adjuntos e historial; nunca el archivo .env.` }),
    h('button', { type: 'button', text: 'Crear copia ahora', onclick: async () => { if (await accion(() => api('POST', '/api/copias'), (x) => `Copia creada: ${x.archivo}`)) pintarCopias(); } }), listaCopias,
    h('p', { class: 'ayuda', text: 'Para restaurar: detené la app y ejecutá scripts\\restaurar_copia.ps1 -Archivo "<ruta de la copia>". Los datos actuales se mueven a una carpeta de resguardo.' }),
    h('h3', { text: 'Inicio automático con Windows (opcional)' }),
    h('p', { class: 'ayuda', text: 'Desactivado por defecto. Para activarlo ejecutá scripts\\inicio_automatico.ps1 -Activar (crea un acceso directo en tu carpeta Inicio, sin permisos de administrador). Para quitarlo: scripts\\inicio_automatico.ps1 -Desactivar.' }));
  // Cora, la mascota de escritorio
  const mc = cfg.mascota;
  const gat = { habilitada: h('input', { type: 'checkbox', checked: mc.habilitada }), siempre_visible: h('input', { type: 'checkbox', checked: mc.siempre_visible }),
    sonidos: h('input', { type: 'checkbox', checked: mc.sonidos }), reducir_animaciones: h('input', { type: 'checkbox', checked: mc.reducir_animaciones }),
    notificacion_respaldo: h('input', { type: 'checkbox', checked: mc.notificacion_respaldo }) };
  const tamano = h('select', {}, [['chico', 'Chico'], ['mediano', 'Mediano'], ['grande', 'Grande']].map(([v, t]) => h('option', { value: v, text: t })));
  tamano.value = mc.tamano;
  const pGato = h('div', { class: 'panel' }, h('h2', { text: 'Cora, la mascota de escritorio' }),
    h('p', { class: 'ayuda', text: 'Cora es el recordatorio principal: en los días y horarios configurados arriba, si falta el registro de hoy muestra un plato vacío y pide comida. Registrar una actividad válida de hoy equivale a darle de comer (la animación se ve una vez por día). Con «Hoy no hubo actividad», Cora descansa. Arrastrá a Cora para cambiar su posición; clic derecho para el menú.' }),
    h('label', {}, gat.habilitada, ' Mascota activada'), h('br'),
    h('label', {}, gat.siempre_visible, ' Mantener sobre otras ventanas'), h('br'),
    h('label', {}, gat.reducir_animaciones, ' Reducir animaciones'), h('br'),
    h('label', {}, gat.sonidos, ' Sonidos (desactivados por defecto)'), h('br'),
    h('label', {}, gat.notificacion_respaldo, ' Usar notificación de Windows cuando Cora esté oculta o cerrada'),
    h('div', { class: 'fila2' }, campo('Tamaño', tamano)),
    h('p', { class: 'meta', text: mc.posicion_x !== null ? `Posición guardada: ${mc.posicion_x}, ${mc.posicion_y} (se cambia arrastrándolo)` : 'Posición: esquina inferior derecha (se cambia arrastrándolo).' }),
    h('div', { class: 'acciones' },
      h('button', { type: 'button', class: 'primario', text: 'Guardar opciones de Cora', onclick: async () => {
        const datos = { tamano: tamano.value };
        for (const [k, el] of Object.entries(gat)) datos[k] = el.checked;
        await guardarSeccion('mascota', datos); } }),
      h('button', { type: 'button', text: 'Mostrar a Cora ahora', onclick: () => accion(() => api('POST', '/api/mascota/abrir'), (x) => x.mensaje) }),
      h('button', { type: 'button', text: 'Volver a la esquina', onclick: async () => { if (await guardarSeccion('mascota', { posicion_x: null, posicion_y: null })) mensaje('Se aplicará la próxima vez que se abra Cora.', 'alerta'); } })),
    h('p', { class: 'ayuda', text: '«Cerrar a Cora» (en su menú) solo cierra la mascota: CoraNotes sigue funcionando y, si está activado, avisa con notificaciones de Windows. Para detener todo usá «Detener todo CoraNotes…» o Detener CoraNotes.bat.' }));
  reemplazar(vista, h('h1', { text: 'Configuración' }), pRec, pGato, pPres, pIA, pEnt, pSis);
  pintarCopias().catch(() => {});
}

// ---------- arranque ----------
(async () => {
  try { await iniciarSesion(); } catch { mensaje('No se pudo conectar con el backend local.', 'error', 0); }
  navegar();
})();
