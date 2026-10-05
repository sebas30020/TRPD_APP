/* Visor de revisión TRPD (generado por TRPD_APP/generar_reporte_html.py).
   Datos: window.TRPD_INDICE / TRPD_CONFIG (data/indice.js) y window.TRPD_DATA[mid]
   (data/<mid>.js, cargado a demanda con <script>, que funciona con file://).
   Filas det: [id, seg, t_osc, t_abs, vmax, vpp, en_otro, manual, env]
   Filas cand: [id, seg, t_osc, t_abs, v, vpp] */
(function () {
  "use strict";
  const CFG = window.TRPD_CONFIG, IDX = window.TRPD_INDICE || [];
  const CANALES = ["ch3", "ch2"], SENALES = ["ch1", "ch2", "ch3", "ch4"];
  const CLAVE_LS = "trpd_revision_v1", CLAVE_PREF = "trpd_visor_pref_v1";
  const st = { mid: null, est: "F", cand: true, seg: 1, sel: null, pendiente: null };
  let marcas = leerLS(CLAVE_LS, {});
  const $ = (id) => document.getElementById(id);
  const PLOT_CFG = { responsive: true, displaylogo: false, modeBarButtonsToRemove: ["lasso2d", "select2d"] };

  // ---------- utilidades ----------
  function leerLS(k, def) { try { const v = localStorage.getItem(k); return v ? JSON.parse(v) : def; } catch (e) { return def; } }
  function escribirLS(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* sin almacenamiento */ } }
  function dec(b64, s) {
    const bin = atob(b64), n = bin.length >> 1, out = new Float32Array(n);
    for (let i = 0; i < n; i++) {
      let v = bin.charCodeAt(2 * i) | (bin.charCodeAt(2 * i + 1) << 8);
      if (v & 0x8000) v -= 0x10000;
      out[i] = v * s;
    }
    return out;
  }
  function trazaMinMax(tr) {   // {t0, w, y, s} -> x, y
    const y = dec(tr.y, tr.s), x = new Float32Array(y.length);
    for (let i = 0; i < y.length; i += 2) { x[i] = tr.t0 + tr.w * (i / 2 + 0.25); x[i + 1] = tr.t0 + tr.w * (i / 2 + 0.75); }
    return { x: Array.from(x), y: Array.from(y) };
  }
  function trazaUniforme(tr) { // {t0, dt, y, s}
    const y = dec(tr.y, tr.s), x = new Array(y.length);
    for (let i = 0; i < y.length; i++) x[i] = tr.t0 + tr.dt * i;
    return { x: x, y: Array.from(y) };
  }
  const f3 = (v) => (v === null || v === undefined || v === "") ? "—" : Number(v).toFixed(3);
  const f1 = (v) => (v === null || v === undefined) ? "—" : Number(v).toFixed(1);
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const D = () => window.TRPD_DATA && window.TRPD_DATA[st.mid];
  const E = () => D().est[st.est];

  // ---------- puntos ----------
  function puntos(ch, conCand) {
    const e = E(), out = [];
    e.det[ch].forEach((r) => out.push({ id: r[0], ch: ch, tipo: "det", seg: r[1], t: r[2], tabs: r[3], v: r[4], vpp: r[5], en: r[6], manual: r[7], env: r[8] }));
    if (conCand) e.cand[ch].forEach((r) => out.push({ id: r[0], ch: ch, tipo: "cand", seg: r[1], t: r[2], tabs: r[3], v: r[4], vpp: r[5], en: 0, manual: 0, env: null }));
    return out;
  }
  function todos() { return CANALES.flatMap((c) => puntos(c, st.cand)).sort((a, b) => a.seg - b.seg || a.t - b.t); }
  function buscar(id) { for (const c of CANALES) { const p = puntos(c, true).find((q) => q.id === id); if (p) return p; } return null; }

  // ---------- marcas ----------
  function marcar(p, accion) {
    const d = D();
    marcas[p.id] = { id: p.id, ruta: d.meta.ruta, titulo: d.meta.titulo, canal: p.ch, estado: st.est,
                     accion: accion, seg: p.seg, t_us: Number(p.t.toFixed(5)) };
    escribirLS(CLAVE_LS, marcas); refrescarTodo();
  }
  function desmarcar(id) { delete marcas[id]; escribirLS(CLAVE_LS, marcas); refrescarTodo(); }
  function marcasMedicion() { const r = D().meta.ruta; return Object.values(marcas).filter((m) => m.ruta === r && m.estado === st.est); }

  // ---------- carga ----------
  function cargar(mid) {
    st.mid = mid; st.sel = null; st.pendiente = null; st.seg = 1;
    escribirLS(CLAVE_PREF, { mid: mid, est: st.est });
    if (window.TRPD_DATA && window.TRPD_DATA[mid]) { iniciarMedicion(); return; }
    Plotly.purge($("senales"));
    $("senales").innerHTML = '<div class="cargando">Cargando datos…</div>';
    const s = document.createElement("script");
    s.src = "data/" + mid + ".js";
    s.onload = iniciarMedicion;
    s.onerror = () => { $("senales").innerHTML = '<div class="cargando">No se pudo cargar data/' + mid + ".js</div>"; };
    document.head.appendChild(s);
  }
  function iniciarMedicion() {
    const d = D();
    $("sel-disparo").innerHTML = "";
    for (let s = 1; s <= d.meta.nsegs; s++) $("sel-disparo").add(new Option("Disparo " + s, s));
    const p = todos()[0];
    if (p) seleccionar(p.id); else { st.seg = 1; refrescarTodo(); }
  }

  // ---------- selección ----------
  function seleccionar(id) {
    const p = buscar(id);
    if (!p) return;
    st.sel = p; st.seg = p.seg; st.pendiente = null;
    refrescarTodo();
  }
  function irDisparo(s) {
    const n = D().meta.nsegs;
    st.seg = Math.min(n, Math.max(1, s));
    if (!st.sel || st.sel.seg !== st.seg) {
      const p = todos().find((q) => q.seg === st.seg);
      st.sel = p || null;
    }
    st.pendiente = null;
    refrescarTodo();
  }
  function irPunto(paso) {
    const L = todos();
    if (!L.length) return;
    let i = st.sel ? L.findIndex((q) => q.id === st.sel.id) : -1;
    i = i < 0 ? 0 : (i + paso + L.length) % L.length;
    seleccionar(L[i].id);
  }

  // ---------- render ----------
  function refrescarTodo() {
    if (!D()) return;
    $("n-marcas").textContent = Object.keys(marcas).length;
    $("sel-disparo").value = st.seg;
    renderCabecera(); renderMapas(); renderSenales(); renderDetalle(); renderTablaDisparo(); renderMarcas();
  }

  function cuentasRevisadas(ch) {
    const base = E().cuentas[ch].slice(), ms = marcasMedicion().filter((m) => m.canal === ch);
    ms.forEach((m) => { const i = m.seg - 1; if (i >= 0 && i < base.length) base[i] += (m.accion === "anadir" ? 1 : -1); });
    const dist = [0, 1, 2, 3, 4].map((k) => base.filter((c) => c === k).length).concat([base.filter((c) => c > 4).length]);
    return { cuentas: base, dist: "[" + dist.join(", ") + "]", n: ms.length };
  }

  function renderCabecera() {
    const d = D(), e = E();
    $("titulo-med").textContent = d.meta.titulo + " · set " + d.meta.set + " · " + d.meta.nsegs + " disparos";
    $("params").textContent = d.meta.ruta + " · " + (st.est === "F" ? "con filtros" : "sin filtros (señal cruda)") +
      " · CH3 " + e.filtro.ch3 + ", umbral " + e.umbral.ch3 + " mV, desde t_abs " + d.meta.t_ini.ch3 + " µs" +
      " · CH2 " + e.filtro.ch2 + ", umbral " + e.umbral.ch2 + " mV + " + CFG.k_env + "·resonancia, desde t_abs " + d.meta.t_ini.ch2 + " µs";
    let h = "<tr><th>Sensor</th><th>N_PD distribution<br>[0,1,2,3,4,&gt;4]</th><th>N_PD = N_cav</th><th>V̄pp (V)</th><th>t̄abs (µs)</th><th>Descargas</th><th>Revisado</th></tr>";
    CANALES.forEach((ch) => {
      const f = e.fila[ch], rv = cuentasRevisadas(ch);
      h += "<tr><td>" + esc(f.sensor) + " (" + ch.toUpperCase() + ")</td><td>" + esc(f.distribucion) + "</td><td>" + esc(f.n_coinc) +
        "</td><td>" + esc(f.vpp_media) + "</td><td>" + esc(f.tabs_media) + "</td><td>" + e.det[ch].length + "</td><td>" +
        (rv.n ? esc(rv.dist) + " <span class='nota'>(" + rv.n + " marcas)</span>" : "—") + "</td></tr>";
    });
    $("tabla1").innerHTML = h;
    const r = IDX.find((m) => m.id === st.mid).res;
    let g = "<tr><th></th><th>Descargas F</th><th>Descargas C</th><th>En el otro F</th><th>En el otro C</th><th>Cand. F</th><th>Cand. C</th></tr>";
    CANALES.forEach((ch) => {
      g += "<tr><td>" + ch.toUpperCase() + "</td><td>" + r.F[ch].n + "</td><td>" + r.C[ch].n + "</td><td>" + r.F[ch].coinc +
        "</td><td>" + r.C[ch].coinc + "</td><td>" + r.F[ch].cand + "</td><td>" + r.C[ch].cand + "</td></tr>";
    });
    $("tabla-fc").innerHTML = g;
  }

  function renderMapas() {
    const d = D();
    CANALES.forEach((ch) => {
      const col = CFG.colores[ch], P = puntos(ch, true), tr = [];
      const grupo = (filtro, nombre, marker) => {
        const L = P.filter(filtro);
        if (!L.length) return;
        tr.push({ type: "scattergl", mode: "markers", name: nombre, x: L.map((p) => p.tabs), y: L.map((p) => p.vpp / 1000),
          customdata: L.map((p) => p.id), marker: marker,
          text: L.map((p) => p.id + "<br>disparo " + p.seg + " · t_osc " + p.t.toFixed(4) + " µs<br>Vpp " + p.vpp.toFixed(1) + " mV" +
            (p.tipo === "det" ? (p.en ? " · también en el otro sensor" : " · solo en " + ch.toUpperCase()) : " · candidato")),
          hovertemplate: "%{text}<br>t_abs %{x:.3f} µs<extra></extra>" });
      };
      if (st.cand) grupo((p) => p.tipo === "cand", "candidato", { color: "#b8c0ca", size: 5 });
      grupo((p) => p.tipo === "det" && p.en && !p.manual, "también en el otro", { color: col, size: 8, line: { color: "#fff", width: 0.5 } });
      grupo((p) => p.tipo === "det" && !p.en && !p.manual, "solo " + ch.toUpperCase(), { color: "#fff", size: 8, line: { color: col, width: 1.5 } });
      grupo((p) => p.manual, "manual", { color: col, size: 10, symbol: "diamond", line: { color: "#000", width: 0.6 } });
      const ms = marcasMedicion().filter((m) => m.canal === ch);
      const q = ms.filter((m) => m.accion === "quitar").map((m) => buscar(m.id)).filter(Boolean);
      if (q.length) tr.push({ type: "scatter", mode: "markers", name: "no es DP", x: q.map((p) => p.tabs), y: q.map((p) => p.vpp / 1000),
        customdata: q.map((p) => p.id), marker: { symbol: "x-thin", size: 14, color: "#c0392b", line: { color: "#c0392b", width: 2.5 } }, hoverinfo: "skip" });
      const a = ms.filter((m) => m.accion === "anadir");
      if (a.length) tr.push({ type: "scatter", mode: "markers", name: "es DP", customdata: a.map((m) => m.id),
        x: a.map((m) => { const p = buscar(m.id); return p ? p.tabs : m.t_us - d.meta.t10[m.seg - 1] - (d.meta.t_lag[ch] || 0); }),
        y: a.map((m) => { const p = buscar(m.id); return p ? p.vpp / 1000 : 0; }),
        marker: { symbol: "circle-open", size: 15, color: "#1e8449", line: { color: "#1e8449", width: 2.5 } }, hoverinfo: "skip" });
      if (st.sel && st.sel.ch === ch) tr.push({ type: "scatter", mode: "markers", name: "seleccionado", x: [st.sel.tabs], y: [st.sel.vpp / 1000],
        marker: { symbol: "circle-open", size: 20, color: "#e6b800", line: { color: "#e6b800", width: 3 } }, hoverinfo: "skip", showlegend: false });
      const lay = {
        title: { text: (ch === "ch3" ? "Antena 1 (CH3)" : "HFCT (CH2)") + " · " + E().det[ch].length + " descargas", font: { size: 13 }, x: 0.01 },
        margin: { l: 55, r: 10, t: 30, b: 38 }, xaxis: { title: "t_abs [µs]", range: CFG.x_lim, zeroline: false },
        yaxis: { title: "Vpp [V]", rangemode: "tozero" }, legend: { orientation: "h", y: 1.12, x: 1, xanchor: "right", font: { size: 10 } },
        shapes: [{ type: "rect", xref: "x", yref: "paper", x0: CFG.x_lim[0], x1: d.meta.t_ini[ch], y0: 0, y1: 1, fillcolor: "#eef1f5", line: { width: 0 }, layer: "below" },
                 { type: "line", xref: "x", yref: "paper", x0: 0, x1: 0, y0: 0, y1: 1, line: { color: "#9aa5b1", width: 1, dash: "dot" } }],
        uirevision: st.mid + ch, plot_bgcolor: "#fff", paper_bgcolor: "#fff", hovermode: "closest",
      };
      const div = $("mapa-" + ch);
      Plotly.react(div, tr, lay, PLOT_CFG);
      if (!div._conClic) { div.on("plotly_click", (ev) => { const p = ev.points && ev.points[0]; if (p && p.customdata) seleccionar(p.customdata); }); div._conClic = true; }
    });
  }

  function lineasPuntos(seg, eje, yref, ch, conCand) {
    return puntos(ch, conCand).filter((p) => p.seg === seg).map((p) => ({
      type: "line", xref: eje, yref: yref, x0: p.t, x1: p.t, y0: 0, y1: 1,
      line: { color: p.tipo === "det" ? CFG.colores[ch] : "#9aa5b1", width: p.tipo === "det" ? 1.5 : 1, dash: p.tipo === "det" ? "solid" : "dot" },
    }));
  }

  function renderSenales() {
    const d = D(), e = E(), sen = e.senal[st.seg] || {}, tr = [], shapes = [], lay = {};
    const n = SENALES.length, gap = 0.025, h = (1 - gap * (n - 1)) / n;
    SENALES.forEach((ch, k) => {
      const ya = k === 0 ? "y" : "y" + (k + 1), clave = k === 0 ? "yaxis" : "yaxis" + (k + 1);
      const top = 1 - k * (h + gap);
      lay[clave] = { domain: [top - h, top], title: { text: CFG.nombres[ch], font: { size: 10 } }, zeroline: false };
      if (sen[ch]) { const t = trazaMinMax(sen[ch]); tr.push({ type: "scattergl", mode: "lines", x: t.x, y: t.y, yaxis: ya, name: ch.toUpperCase(), line: { color: CFG.colores[ch], width: 0.8 }, hoverinfo: "x+y" }); }
      if (ch === "ch2" && sen.ch2r) { const t = trazaMinMax(sen.ch2r); tr.push({ type: "scattergl", mode: "lines", x: t.x, y: t.y, yaxis: ya, name: "CH2 − resonancia", visible: "legendonly", line: { color: "#7f4f24", width: 0.8 } }); }
      const yref = (k === 0 ? "y" : "y" + (k + 1)) + " domain";
      if (ch === "ch3" || ch === "ch2") {
        shapes.push(...lineasPuntos(st.seg, "x", yref, ch, st.cand));
        shapes.push({ type: "line", xref: "paper", yref: ya, x0: 0, x1: 1, y0: e.umbral[ch], y1: e.umbral[ch], line: { color: "#c0392b", width: 1, dash: "dash" } });
      }
    });
    if (st.sel && st.sel.seg === st.seg) {
      const t = st.sel.t - (CFG.retardo[st.sel.ch] || 0);
      shapes.push({ type: "rect", xref: "x", yref: "paper", x0: t - 0.03, x1: t + 0.03, y0: 0, y1: 1, fillcolor: "rgba(241,196,15,0.25)", line: { width: 0 }, layer: "below" });
    }
    Object.assign(lay, {
      margin: { l: 70, r: 10, t: 10, b: 40 }, showlegend: true, legend: { orientation: "h", y: -0.06, font: { size: 10 } },
      xaxis: { anchor: "y" + n, title: "Tiempo del osciloscopio [µs]", range: CFG.t_lim }, shapes: shapes,
      uirevision: st.mid + st.est + st.seg, hovermode: "x", plot_bgcolor: "#fff", paper_bgcolor: "#fff",
    });
    const divS = $("senales");
    if (divS.querySelector(".cargando")) divS.innerHTML = "";
    Plotly.react(divS, tr, lay, PLOT_CFG);
    const nD = CANALES.map((c) => c.toUpperCase() + " " + e.cuentas[c][st.seg - 1]).join(" · ");
    $("titulo-disparo").textContent = "Disparo " + st.seg + " de " + d.meta.nsegs + " (" + nD + ")";
    $("info-sel").textContent = st.sel ? "Seleccionado " + st.sel.id + " · " + st.sel.ch.toUpperCase() + " · t_osc " + st.sel.t.toFixed(4) +
      " µs · t_abs " + st.sel.tabs.toFixed(3) + " µs · Vpp " + st.sel.vpp.toFixed(1) + " mV" : "Sin punto seleccionado";
  }

  function renderDetalle() {
    const div = $("detalle"), e = E();
    if (!st.sel) { Plotly.purge(div); div._conClic = false; div.innerHTML = '<div class="cargando">Selecciona un punto del mapa o de la tabla.</div>'; return; }
    if (div.querySelector(".cargando")) div.innerHTML = "";
    const det = e.detalle[st.sel.id], t0 = st.sel.t, W = CFG.detalle_us;
    const orden = ["ch3", "ch4", "ch2", "ch2r"], tr = [], shapes = [], lay = {};
    const n = orden.length, gap = 0.04, h = (1 - gap * (n - 1)) / n;
    orden.forEach((ch, k) => {
      const ya = k === 0 ? "y" : "y" + (k + 1), clave = k === 0 ? "yaxis" : "yaxis" + (k + 1), top = 1 - k * (h + gap);
      lay[clave] = { domain: [top - h, top], title: { text: CFG.nombres[ch], font: { size: 10 } }, zeroline: false };
      let t = null;
      if (det && det[ch]) t = trazaUniforme(det[ch]);
      else if (e.senal[st.seg] && e.senal[st.seg][ch]) {   // sin ventana de detalle: traza diezmada recortada
        const m = trazaMinMax(e.senal[st.seg][ch]), x = [], y = [];
        m.x.forEach((xi, i) => { if (xi >= t0 - W && xi <= t0 + W) { x.push(xi); y.push(m.y[i]); } });
        t = { x: x, y: y };
      }
      if (t) tr.push({ type: "scatter", mode: "lines", x: t.x, y: t.y, yaxis: ya, name: ch.toUpperCase(), meta: ch,
        line: { color: ch === "ch2r" ? "#7f4f24" : CFG.colores[ch], width: 1 }, hovertemplate: "%{x:.4f} µs · %{y:.1f} mV<extra>" + ch.toUpperCase() + "</extra>" });
      const base = ch === "ch2r" ? "ch2" : ch;
      if (base === "ch3" || base === "ch2") {
        const yref = ya + " domain";
        shapes.push(...lineasPuntos(st.seg, "x", yref, base, st.cand));
        if (ch !== "ch2" || st.est === "F") {
          const u = e.umbral[base];
          shapes.push({ type: "line", xref: "paper", yref: ya, x0: 0, x1: 1, y0: u, y1: u, line: { color: "#c0392b", width: 1, dash: "dash" } });
          shapes.push({ type: "line", xref: "paper", yref: ya, x0: 0, x1: 1, y0: u * CFG.frac_cand, y1: u * CFG.frac_cand, line: { color: "#9aa5b1", width: 1, dash: "dot" } });
          if (ch === "ch2r" && st.sel.ch === "ch2" && st.sel.env) {
            const ud = u + CFG.k_env * st.sel.env;
            shapes.push({ type: "line", xref: "paper", yref: ya, x0: 0, x1: 1, y0: ud, y1: ud, line: { color: "#c0392b", width: 1, dash: "dashdot" } });
          }
        }
      }
    });
    shapes.push({ type: "line", xref: "x", yref: "paper", x0: t0 - (CFG.retardo[st.sel.ch] || 0), x1: t0 - (CFG.retardo[st.sel.ch] || 0), y0: 0, y1: 1, line: { color: "#f1c40f", width: 2 }, layer: "below" });
    if (st.pendiente) shapes.push({ type: "line", xref: "x", yref: "paper", x0: st.pendiente.t, x1: st.pendiente.t, y0: 0, y1: 1, line: { color: "#1e8449", width: 2, dash: "dash" } });
    Object.assign(lay, {
      margin: { l: 70, r: 10, t: 10, b: 40 }, showlegend: false, shapes: shapes,
      xaxis: { anchor: "y" + n, title: "Tiempo del osciloscopio [µs]", range: [t0 - W, t0 + W] },
      uirevision: st.sel.id + st.est, hovermode: "closest", plot_bgcolor: "#fff", paper_bgcolor: "#fff",
      annotations: det ? [] : [{ xref: "paper", yref: "paper", x: 0.5, y: 1, showarrow: false, text: "sin ventana de alta resolución: traza diezmada", font: { color: "#c0392b", size: 11 } }],
    });
    Plotly.react(div, tr, lay, PLOT_CFG);
    if (!div._conClic) {
      div.on("plotly_click", (ev) => {
        const p = ev.points && ev.points[0];
        if (!p || !p.data || !p.data.meta) return;
        const ch = p.data.meta === "ch2r" ? "ch2" : p.data.meta;
        if (ch !== "ch3" && ch !== "ch2") return;
        st.pendiente = { ch: ch, t: p.x, v: p.y };
        renderDetalle(); renderTablaDisparo();
      });
      div._conClic = true;
    }
  }

  function renderTablaDisparo() {
    const L = todos().filter((p) => p.seg === st.seg);
    let h = "<tr><th>ID</th><th>Canal</th><th>Tipo</th><th>t_abs (µs)</th><th>Vpp (mV)</th><th>En el otro</th><th>Revisión</th></tr>";
    if (st.pendiente) {
      const p = st.pendiente;
      h += "<tr class='sel'><td colspan='3'>Nuevo " + p.ch.toUpperCase() + " en t_osc " + p.t.toFixed(4) + " µs</td><td colspan='3'>" + f1(p.v) +
        " mV</td><td><button class='mini contar' data-acc='confirmar'>Es DP</button> <button class='mini' data-acc='cancelar'>✕</button></td></tr>";
    }
    L.forEach((p) => {
      const m = marcas[p.id], cls = [st.sel && st.sel.id === p.id ? "sel" : "", m ? "marcado-" + (m.accion === "quitar" ? "quitar" : "contar") : ""].join(" ");
      const btn = m ? "<button class='mini' data-acc='desmarcar' data-id='" + p.id + "'>Deshacer</button>"
        : (p.tipo === "det" ? "<button class='mini quitar' data-acc='quitar' data-id='" + p.id + "'>No es DP</button>"
          : "<button class='mini contar' data-acc='anadir' data-id='" + p.id + "'>Es DP</button>");
      h += "<tr class='" + cls + "'><td class='id' data-id='" + p.id + "'>" + p.id + "</td><td>" + p.ch.toUpperCase() + "</td><td>" +
        (p.tipo === "det" ? (p.manual ? "manual" : "descarga") : "candidato") + "</td><td>" + f3(p.tabs) + "</td><td>" + f1(p.vpp) + "</td><td>" +
        (p.tipo === "det" ? (p.en ? "sí" : "no") : "—") + "</td><td>" + btn + "</td></tr>";
    });
    const extra = Object.values(marcas).filter((m) => m.ruta === D().meta.ruta && m.estado === st.est && m.seg === st.seg && !buscar(m.id));
    extra.forEach((m) => {
      h += "<tr class='marcado-contar'><td class='id'>" + m.id + "</td><td>" + m.canal.toUpperCase() + "</td><td>añadido</td><td colspan='3'>t_osc " +
        m.t_us.toFixed(4) + " µs</td><td><button class='mini' data-acc='desmarcar' data-id='" + m.id + "'>Deshacer</button></td></tr>";
    });
    if (!L.length && !extra.length && !st.pendiente) h += "<tr><td colspan='7' class='nota'>Sin descargas ni candidatos en este disparo.</td></tr>";
    $("tabla-disparo").innerHTML = h;
  }

  function renderMarcas() {
    const L = Object.values(marcas).sort((a, b) => (a.ruta + a.id).localeCompare(b.ruta + b.id));
    $("lista-marcas").innerHTML = L.length ? L.map((m) =>
      "<li><span class='txt' data-mid-ruta='" + esc(m.ruta) + "' data-id='" + esc(m.id) + "'>" + (m.accion === "quitar" ? "✕ no es DP" : "✓ es DP") + " · " +
      esc(m.titulo || m.ruta) + " · " + m.canal.toUpperCase() + " · " + (m.estado === "F" ? "con filtros" : "sin filtros") + " · disparo " + m.seg +
      " · t " + m.t_us.toFixed(4) + " µs</span><button class='mini' data-acc='desmarcar' data-id='" + esc(m.id) + "'>✕</button></li>").join("")
      : "<li class='nota'>Sin marcas.</li>";
  }

  // ---------- eventos ----------
  function exportar() {
    const L = Object.values(marcas);
    const txt = JSON.stringify(L, null, 1);
    try { navigator.clipboard && navigator.clipboard.writeText(txt); } catch (e) { /* sin portapapeles */ }
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([txt], { type: "application/json" }));
    a.download = "revision_trpd.json";
    document.body.appendChild(a); a.click(); a.remove();
  }
  document.addEventListener("click", (ev) => {
    const b = ev.target.closest("[data-acc]");
    if (b) {
      const acc = b.dataset.acc, id = b.dataset.id;
      if (acc === "quitar" || acc === "anadir") { const p = buscar(id); if (p) marcar(p, acc); }
      else if (acc === "desmarcar") desmarcar(id);
      else if (acc === "cancelar") { st.pendiente = null; renderDetalle(); renderTablaDisparo(); }
      else if (acc === "confirmar" && st.pendiente) {
        const p = st.pendiente, id2 = st.mid + "-" + p.ch + "-" + st.est + "-a" + Date.now();
        st.pendiente = null;
        marcar({ id: id2, ch: p.ch, seg: st.seg, t: p.t }, "anadir");
      }
      return;
    }
    const c = ev.target.closest("td.id[data-id]");
    if (c) { seleccionar(c.dataset.id); return; }
    const li = ev.target.closest(".marcas .txt");
    if (li) {
      const m = marcas[li.dataset.id];
      if (!m) return;
      const med = IDX.find((x) => x.ruta === m.ruta);
      if (m.estado !== st.est) setEstado(m.estado, false);
      if (med && med.id !== st.mid) { $("sel-medicion").value = med.id; cargar(med.id); }
      setTimeout(() => { if (buscar(m.id)) seleccionar(m.id); else irDisparo(m.seg); }, 50);
    }
  });
  function setEstado(e, refrescar) {
    st.est = e;
    document.querySelectorAll(".seg-control button").forEach((b) => b.classList.toggle("activo", b.dataset.estado === e));
    escribirLS(CLAVE_PREF, { mid: st.mid, est: e });
    if (refrescar !== false && D()) { const s = st.seg; st.sel = null; st.pendiente = null; const p = todos().find((q) => q.seg === s); st.sel = p || null; refrescarTodo(); }
  }
  document.querySelectorAll(".seg-control button").forEach((b) => b.addEventListener("click", () => setEstado(b.dataset.estado)));
  $("chk-cand").addEventListener("change", (ev) => { st.cand = ev.target.checked; if (st.sel && st.sel.tipo === "cand" && !st.cand) st.sel = null; refrescarTodo(); });
  $("sel-medicion").addEventListener("change", (ev) => cargar(ev.target.value));
  $("sel-disparo").addEventListener("change", (ev) => irDisparo(Number(ev.target.value)));
  $("btn-seg-ant").addEventListener("click", () => irDisparo(st.seg - 1));
  $("btn-seg-sig").addEventListener("click", () => irDisparo(st.seg + 1));
  $("btn-pd-ant").addEventListener("click", () => irPunto(-1));
  $("btn-pd-sig").addEventListener("click", () => irPunto(1));
  $("btn-exportar").addEventListener("click", exportar);
  $("btn-borrar").addEventListener("click", (ev) => {
    const b = ev.currentTarget;
    if (b.dataset.confirmar) { marcas = {}; escribirLS(CLAVE_LS, marcas); delete b.dataset.confirmar; b.textContent = "Borrar todas las marcas"; refrescarTodo(); }
    else { b.dataset.confirmar = "1"; b.textContent = "Pulsa otra vez para borrar"; setTimeout(() => { delete b.dataset.confirmar; b.textContent = "Borrar todas las marcas"; }, 3000); }
  });
  document.addEventListener("keydown", (ev) => {
    if (ev.target.tagName === "SELECT" || ev.target.tagName === "INPUT") return;
    if (ev.key === "ArrowRight") irPunto(1);
    else if (ev.key === "ArrowLeft") irPunto(-1);
    else if (ev.key === "PageDown") irDisparo(st.seg + 1);
    else if (ev.key === "PageUp") irDisparo(st.seg - 1);
  });

  // ---------- inicio ----------
  $("frac-cand").textContent = Math.round(CFG.frac_cand * 100) + " %";
  $("det-us").textContent = CFG.detalle_us;
  $("pie").textContent = "Generado " + CFG.generado + " · coincidencia ≤ " + (CFG.tol_coinc * 1000) + " ns (CH2 − CH3 = " +
    (CFG.retardo.ch2 * 1000) + " ns) · teclas ← → recorren los puntos, RePág/AvPág los disparos";
  const grupos = {};
  IDX.forEach((m) => { (grupos[m.probeta] = grupos[m.probeta] || []).push(m); });
  Object.keys(grupos).forEach((p) => {
    const og = document.createElement("optgroup"); og.label = p;
    grupos[p].forEach((m) => og.appendChild(new Option(m.titulo + " — CH3 " + m.res.F.ch3.n + " · CH2 " + m.res.F.ch2.n, m.id)));
    $("sel-medicion").appendChild(og);
  });
  const pref = leerLS(CLAVE_PREF, {});
  if (pref.est === "C") setEstado("C", false);
  const inicial = IDX.some((m) => m.id === pref.mid) ? pref.mid : (IDX[0] && IDX[0].id);
  if (inicial) { $("sel-medicion").value = inicial; cargar(inicial); }
})();
