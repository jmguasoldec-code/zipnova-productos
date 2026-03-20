"""
Tab de gestión masiva de promociones ML.
Escanea, muestra preview y activa cofundadas (SMART) priorizando mayor subsidio de ML.
"""


def render_tab_promociones(get_cuentas_ml, refresh_ml_token, ML_BASE):
    import streamlit as st
    import requests
    import time
    import pandas as pd

    # ── session state defaults ─────────────────────────────────────────
    defaults = {
        "promo_scan": None,         # lista de dicts con info por item
        "promo_activados": None,    # resultados de activación
        "promo_confirmar": False,   # flag de confirmación
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

    # ── helpers ────────────────────────────────────────────────────────
    def ml_get(url, token, params=None):
        r = requests.get(url, headers={"Authorization": f"Bearer {token}"},
                         params=params, timeout=15)
        return r.json() if r.status_code == 200 else None

    def ml_post(url, token, body):
        r = requests.post(url, headers={"Authorization": f"Bearer {token}",
                          "Content-Type": "application/json"}, json=body, timeout=15)
        return r.status_code, r.json() if r.status_code in (200, 201) else r.text

    st.markdown("### 🏷️ Gestión Masiva de Promociones")

    cuentas = get_cuentas_ml()
    cuenta_nombre = st.selectbox("Cuenta ML", [c["nombre"] for c in cuentas], key="promo_cuenta")
    cuenta = next(c for c in cuentas if c["nombre"] == cuenta_nombre)

    # ── PASO 1: ESCANEAR ──────────────────────────────────────────────
    if st.button("🔍 Escanear promociones", key="btn_scan_promos"):
        st.session_state["promo_scan"] = None
        st.session_state["promo_activados"] = None
        st.session_state["promo_confirmar"] = False

        token = refresh_ml_token(cuenta)
        if not token:
            st.error("No se pudo renovar token ML")
            return

        # Traer items activos
        with st.spinner("Cargando items activos..."):
            item_ids = []
            off = 0
            while True:
                data = ml_get(f"{ML_BASE}/users/{cuenta['user_id']}/items/search",
                              token, {"status": "active", "offset": off, "limit": 50})
                if not data:
                    break
                item_ids.extend(data.get("results", []))
                if len(item_ids) >= data.get("paging", {}).get("total", 0):
                    break
                off += 50

        st.info(f"🛒 {len(item_ids)} items activos en {cuenta_nombre}")

        # Escanear promos de cada item
        scan = []
        prog = st.progress(0, text="Escaneando promociones...")
        for i, iid in enumerate(item_ids):
            prog.progress((i + 1) / max(len(item_ids), 1), text=f"Escaneando {i+1}/{len(item_ids)}...")

            # Obtener título del item
            item_data = ml_get(f"{ML_BASE}/items/{iid}", token)
            titulo = item_data.get("title", "—")[:50] if item_data else "—"
            precio = item_data.get("price", 0) if item_data else 0

            # Obtener promos
            promos = ml_get(f"{ML_BASE}/seller-promotions/items/{iid}?app_version=v2", token)
            if not promos or not isinstance(promos, list):
                time.sleep(0.2)
                continue

            smarts_candidatas = [p for p in promos if p.get("type") == "SMART" and p.get("status") == "candidate"]
            smarts_activas = [p for p in promos if p.get("type") == "SMART" and p.get("status") == "started"]

            if smarts_candidatas or smarts_activas:
                # Ordenar candidatas por meli_percentage desc
                smarts_candidatas.sort(key=lambda p: float(p.get("meli_percentage", 0) or 0), reverse=True)

                mejor = smarts_candidatas[0] if smarts_candidatas else (smarts_activas[0] if smarts_activas else None)

                scan.append({
                    "item_id": iid,
                    "titulo": titulo,
                    "precio": precio,
                    "candidatas": smarts_candidatas,
                    "activas": smarts_activas,
                    "mejor_nombre": mejor.get("name", "—") if mejor else "—",
                    "mejor_meli_pct": float(mejor.get("meli_percentage", 0) or 0) if mejor else 0,
                    "mejor_seller_pct": float(mejor.get("seller_percentage", 0) or 0) if mejor else 0,
                    "mejor_precio": float(mejor.get("price", 0) or 0) if mejor else 0,
                    "estado": "Activa" if smarts_activas else "Candidata",
                })

            time.sleep(0.2)

        prog.empty()
        st.session_state["promo_scan"] = scan
        st.rerun()

    # ── PASO 2: PREVIEW ───────────────────────────────────────────────
    if st.session_state["promo_scan"] is not None:
        scan = st.session_state["promo_scan"]

        if not scan:
            st.warning("No se encontraron items con promociones cofundadas.")
            return

        # Métricas
        total = len(scan)
        activas = sum(1 for s in scan if s["estado"] == "Activa")
        candidatas = sum(1 for s in scan if s["estado"] == "Candidata")

        c1, c2, c3 = st.columns(3)
        c1.metric("Total con cofundadas", total)
        c2.metric("✅ Ya activas", activas)
        c3.metric("🟡 Candidatas (activables)", candidatas)

        # Filtro
        filtro = st.radio("Filtrar", ["Todas", "Solo candidatas", "Solo activas"], horizontal=True, key="promo_filtro")
        if filtro == "Solo candidatas":
            scan_filtrado = [s for s in scan if s["estado"] == "Candidata"]
        elif filtro == "Solo activas":
            scan_filtrado = [s for s in scan if s["estado"] == "Activa"]
        else:
            scan_filtrado = scan

        # Tabla
        rows = []
        for s in scan_filtrado:
            rows.append({
                "MLA": s["item_id"],
                "Producto": s["titulo"],
                "Precio actual": f"${s['precio']:,.2f}",
                "Mejor cofundada": s["mejor_nombre"],
                "ML paga (%)": f"{s['mejor_meli_pct']}%",
                "Vos pagás (%)": f"{s['mejor_seller_pct']}%",
                "Precio promo": f"${s['mejor_precio']:,.2f}",
                "Estado": s["estado"],
                "N° candidatas": len(s["candidatas"]),
                "N° activas": len(s["activas"]),
            })

        df = pd.DataFrame(rows)
        st.dataframe(df, use_container_width=True, hide_index=True)

        st.download_button("📥 Descargar CSV", df.to_csv(index=False).encode("utf-8"),
                           f"promos_{cuenta_nombre}.csv", "text/csv", key="btn_dl_promos")

        # ── PASO 3: ACTIVAR ───────────────────────────────────────────
        activables = [s for s in scan if s["candidatas"]]
        if activables:
            st.divider()
            st.markdown(f"### Activar cofundadas ({len(activables)} items con candidatas)")
            st.caption("Se activarán TODAS las cofundadas de cada item, priorizando la que ML más subsidia.")

            total_promos = sum(len(s["candidatas"]) for s in activables)

            if not st.session_state["promo_confirmar"]:
                if st.button(f"🏷️ Activar {total_promos} cofundadas en {len(activables)} items", type="primary"):
                    st.session_state["promo_confirmar"] = True
                    st.rerun()
            else:
                st.warning(f"⚠️ Vas a activar **{total_promos} promociones cofundadas** en **{len(activables)} items**. ML se hace cargo de parte del descuento.")

                col_si, col_no = st.columns(2)
                with col_si:
                    confirmar = st.button("✅ Confirmar activación", type="primary", use_container_width=True)
                with col_no:
                    if st.button("❌ Cancelar", use_container_width=True):
                        st.session_state["promo_confirmar"] = False
                        st.rerun()

                if confirmar:
                    token = refresh_ml_token(cuenta)
                    if not token:
                        st.error("Token expirado")
                        return

                    resultados = []
                    prog = st.progress(0, text="Activando...")
                    idx = 0
                    total_ops = total_promos

                    for s in activables:
                        for promo in s["candidatas"]:
                            idx += 1
                            prog.progress(idx / max(total_ops, 1), text=f"Activando {idx}/{total_ops}...")

                            body = {
                                "promotion_id": promo.get("id"),
                                "promotion_type": "SMART",
                                "offer_id": promo.get("ref_id"),
                            }
                            status, resp = ml_post(
                                f"{ML_BASE}/seller-promotions/items/{s['item_id']}?app_version=v2",
                                token, body
                            )

                            if status in (200, 201):
                                resultados.append({
                                    "MLA": s["item_id"],
                                    "Promo": promo.get("name", "—"),
                                    "ML (%)": promo.get("meli_percentage"),
                                    "Resultado": "✅ Activada",
                                    "Precio": resp.get("price", "—") if isinstance(resp, dict) else "—",
                                })
                            else:
                                error_msg = resp if isinstance(resp, str) else str(resp)
                                resultados.append({
                                    "MLA": s["item_id"],
                                    "Promo": promo.get("name", "—"),
                                    "ML (%)": promo.get("meli_percentage"),
                                    "Resultado": "❌ Error",
                                    "Precio": error_msg[:100],
                                })

                            time.sleep(0.2)

                    prog.empty()
                    st.session_state["promo_activados"] = resultados
                    st.session_state["promo_confirmar"] = False
                    st.rerun()

    # ── PASO 4: RESULTADOS ────────────────────────────────────────────
    if st.session_state["promo_activados"]:
        resultados = st.session_state["promo_activados"]
        st.divider()
        st.markdown("### Resultado de activación")

        ok = sum(1 for r in resultados if "Activada" in r["Resultado"])
        err = sum(1 for r in resultados if "Error" in r["Resultado"])

        c1, c2 = st.columns(2)
        c1.metric("✅ Activadas", ok)
        c2.metric("❌ Errores", err)

        df_res = pd.DataFrame(resultados)
        st.dataframe(df_res, use_container_width=True, hide_index=True)

        st.download_button("📥 Descargar resultados", df_res.to_csv(index=False).encode("utf-8"),
                           f"promos_resultado_{cuenta_nombre}.csv", "text/csv", key="btn_dl_res")

        if st.button("🔄 Volver a escanear", key="btn_rescan"):
            st.session_state["promo_scan"] = None
            st.session_state["promo_activados"] = None
            st.rerun()
