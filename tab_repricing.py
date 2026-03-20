"""
Tab de repricing automatico basado en competencia.
Monitorea precios de competidores, calcula margenes y activa cofundadas.
"""


def render_tab_repricing(get_cuentas_ml, refresh_ml_token, ML_BASE, buscar_costo_erp):
    import streamlit as st
    import requests
    import time
    import json
    import pandas as pd
    from datetime import datetime

    # -- session state defaults ------------------------------------------------
    defaults = {
        "repricing_pares": [],
        "repricing_scan": None,
        "repricing_confirmar_paso1": False,
        "repricing_confirmar_paso2": False,
        "repricing_log": [],
        "repricing_preview_propio": None,
        "repricing_preview_comp": None,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

    # -- helpers ---------------------------------------------------------------
    def ml_get(url, token, params=None):
        try:
            r = requests.get(url, headers={"Authorization": f"Bearer {token}"},
                             params=params, timeout=15)
            if r.status_code == 200:
                return r.json(), None
            return None, f"HTTP {r.status_code}"
        except Exception as e:
            return None, str(e)

    def ml_post(url, token, body):
        try:
            r = requests.post(url, headers={"Authorization": f"Bearer {token}",
                              "Content-Type": "application/json"}, json=body, timeout=15)
            return r.status_code, r.json() if r.status_code in (200, 201) else r.text
        except Exception as e:
            return 0, str(e)

    def extraer_sku(item):
        """Extrae SKU de un item ML siguiendo la prioridad definida."""
        # 1. Atributo SELLER_SKU
        for a in item.get("attributes", []):
            if a.get("id") == "SELLER_SKU":
                val = a.get("value_name", "") or ""
                if val:
                    return val
        # 2. Variaciones: attribute_combinations con " - "
        for v in item.get("variations", []):
            for ac in v.get("attribute_combinations", []):
                vname = ac.get("value_name", "") or ""
                if " - " in vname:
                    return vname.split(" - ", 1)[1].strip()
        # 3. Fallback: seller_custom_field
        return item.get("seller_custom_field") or ""

    def obtener_info_item(item_id, token):
        """Obtiene precio, titulo, SKU de un item ML (autenticado, para items propios)."""
        data, err = ml_get(f"{ML_BASE}/items/{item_id}",
                           token, {"include_attributes": "all"})
        if err:
            return None, err
        return {
            "item_id": data.get("id", item_id),
            "title": data.get("title", ""),
            "price": float(data.get("price", 0) or 0),
            "sku": extraer_sku(data),
            "category_id": data.get("category_id", ""),
            "thumbnail": data.get("thumbnail") or data.get("secure_thumbnail") or "",
        }, None

    def obtener_info_competidor(item_id):
        """Obtiene precio y titulo de un item competidor (endpoint público, sin token)."""
        try:
            r = requests.get(f"{ML_BASE}/items/{item_id}", timeout=15)
            if r.status_code != 200:
                return None, f"HTTP {r.status_code}"
            data = r.json()
            return {
                "item_id": data.get("id", item_id),
                "title": data.get("title", ""),
                "price": float(data.get("price", 0) or 0),
                "sku": "",
                "category_id": data.get("category_id", ""),
                "thumbnail": data.get("thumbnail") or data.get("secure_thumbnail") or "",
            }, None
        except Exception as e:
            return None, str(e)

    def obtener_promos(item_id, token):
        """Obtiene promociones disponibles para un item."""
        data, err = ml_get(
            f"{ML_BASE}/seller-promotions/items/{item_id}?app_version=v2", token)
        if err:
            return []
        if not isinstance(data, list):
            return []
        return data

    def mejor_cofundada(promos):
        """Retorna la mejor promo cofundada (mayor meli_percentage) o None."""
        candidatas = []
        for p in promos:
            if (p.get("type") == "SMART"
                    and p.get("status") in ("candidate", "CANDIDATE", "started", "STARTED")
                    and p.get("meli_percentage", 0) > 0):
                candidatas.append(p)
        if not candidatas:
            return None
        return max(candidatas, key=lambda x: x.get("meli_percentage", 0))

    def calcular_margen(precio, costo_erp):
        """Calcula margen neto despues de comision ML."""
        if not costo_erp or costo_erp <= 0 or not precio or precio <= 0:
            return None
        comision_ml = precio * 0.143
        margen = (precio - costo_erp - comision_ml) / precio * 100
        return round(margen, 1)

    def precio_con_cofundada(precio_original, promo):
        """Calcula el precio con cofundada aplicada."""
        if not promo:
            return precio_original
        # Si la promo tiene precio directo
        if promo.get("price") and promo["price"] > 0:
            return float(promo["price"])
        # Calcular desde porcentajes
        meli_pct = promo.get("meli_percentage", 0) or 0
        seller_pct = promo.get("seller_percentage", 0) or 0
        total_pct = meli_pct + seller_pct
        if total_pct > 0:
            return round(precio_original * (1 - total_pct / 100), 2)
        return precio_original

    # ==========================================================================
    st.markdown("### Repricing Automatico por Competencia")

    cuentas = get_cuentas_ml()

    # ======================================================================
    # SECCION 1: CONFIGURAR PARES DE MONITOREO
    # ======================================================================
    st.markdown("---")
    st.markdown("#### 1. Configurar pares de monitoreo")

    # Mostrar pares configurados
    pares = st.session_state["repricing_pares"]
    if pares:
        df_pares = pd.DataFrame([{
            "#": i + 1,
            "Mi MLA": p["mi_mla"],
            "Cuenta": p["cuenta_nombre"],
            "Mi titulo": p.get("mi_titulo", "")[:40],
            "Mi precio": f"${p.get('mi_precio', 0):,.0f}",
            "SKU": p.get("mi_sku", ""),
            "Comp. MLA": p["comp_mla"],
            "Comp. titulo": p.get("comp_titulo", "")[:40],
            "Comp. precio": f"${p.get('comp_precio', 0):,.0f}",
            "Costo ERP": f"${p.get('costo_erp', 0):,.0f}" if p.get("costo_erp") else "N/A",
            "Margen min %": p.get("margen_min", 20),
        } for i, p in enumerate(pares)])
        st.dataframe(df_pares, use_container_width=True, hide_index=True)

        # Botones eliminar por fila
        cols_del = st.columns(min(len(pares), 6))
        indices_a_eliminar = []
        for i, p in enumerate(pares):
            col_idx = i % min(len(pares), 6)
            with cols_del[col_idx]:
                if st.button(f"Eliminar #{i+1}", key=f"del_par_{i}"):
                    indices_a_eliminar.append(i)
        if indices_a_eliminar:
            for idx in sorted(indices_a_eliminar, reverse=True):
                st.session_state["repricing_pares"].pop(idx)
            st.rerun()
    else:
        st.info("No hay pares configurados. Agrega uno abajo.")

    # Persistencia JSON
    col_json1, col_json2 = st.columns(2)
    with col_json1:
        if pares:
            json_str = json.dumps(pares, ensure_ascii=False, indent=2)
            st.download_button(
                "Descargar config JSON",
                json_str.encode("utf-8"),
                "repricing_config.json",
                "application/json",
                key="btn_download_repricing_json",
            )
    with col_json2:
        uploaded = st.file_uploader("Subir config JSON", type=["json"],
                                    key="repricing_upload_json")
        if uploaded is not None:
            try:
                loaded = json.loads(uploaded.read().decode("utf-8"))
                if isinstance(loaded, list):
                    st.session_state["repricing_pares"] = loaded
                    st.success(f"Cargados {len(loaded)} pares desde JSON")
                    st.rerun()
                else:
                    st.error("El JSON debe ser una lista de pares")
            except Exception as e:
                st.error(f"Error al leer JSON: {e}")

    # Formulario agregar par
    st.markdown("##### Agregar par")
    with st.form("form_agregar_par", clear_on_submit=False):
        fc1, fc2 = st.columns(2)
        with fc1:
            mi_mla = st.text_input("Mi MLA", placeholder="MLA1234567890",
                                   key="repr_mi_mla")
            cuenta_nombre = st.selectbox("Cuenta ML",
                                         [c["nombre"] for c in cuentas],
                                         key="repr_cuenta")
        with fc2:
            comp_mla = st.text_input("MLA competidor",
                                     placeholder="MLA9876543210",
                                     key="repr_comp_mla")
            margen_min = st.number_input("Margen minimo (%)", value=20.0,
                                         min_value=0.0, max_value=100.0,
                                         step=1.0, key="repr_margen_min")
        buscar_btn = st.form_submit_button("Buscar")

    if buscar_btn and mi_mla and comp_mla:
        cuenta = next(c for c in cuentas if c["nombre"] == cuenta_nombre)
        token = refresh_ml_token(cuenta)
        if not token:
            st.error("No se pudo renovar token ML")
        else:
            with st.spinner("Buscando ambos productos..."):
                info_propio, err1 = obtener_info_item(mi_mla.strip(), token)
                time.sleep(0.3)
                info_comp, err2 = obtener_info_competidor(comp_mla.strip())

            if err1:
                st.error(f"Error al buscar mi MLA: {err1}")
            elif err2:
                st.error(f"Error al buscar competidor: {err2}")
            else:
                st.session_state["repricing_preview_propio"] = info_propio
                st.session_state["repricing_preview_comp"] = info_comp
                st.session_state["repricing_preview_cuenta"] = cuenta_nombre
                st.session_state["repricing_preview_margen"] = margen_min

    # Mostrar preview si existe
    prev_propio = st.session_state.get("repricing_preview_propio")
    prev_comp = st.session_state.get("repricing_preview_comp")
    if prev_propio and prev_comp:
        st.markdown("##### Preview")
        pc1, pc2 = st.columns(2)
        costo = buscar_costo_erp(prev_propio["sku"]) if prev_propio["sku"] else None
        with pc1:
            st.markdown("**Mi producto**")
            if prev_propio.get("thumbnail"):
                st.image(prev_propio["thumbnail"], width=120)
            st.markdown(f"**{prev_propio['title']}**")
            st.markdown(f"MLA: `{prev_propio['item_id']}` | Precio: **${prev_propio['price']:,.0f}**")
            st.markdown(f"SKU: `{prev_propio['sku'] or 'Sin SKU'}`")
            if costo:
                st.markdown(f"Costo ERP: **${costo:,.0f}**")
            else:
                st.markdown("Costo ERP: N/A")
        with pc2:
            st.markdown("**Competidor**")
            if prev_comp.get("thumbnail"):
                st.image(prev_comp["thumbnail"], width=120)
            st.markdown(f"**{prev_comp['title']}**")
            st.markdown(f"MLA: `{prev_comp['item_id']}` | Precio: **${prev_comp['price']:,.0f}**")

        if st.button("Agregar par", key="btn_agregar_par", type="primary"):
            nuevo_par = {
                "mi_mla": prev_propio["item_id"],
                "cuenta_nombre": st.session_state.get("repricing_preview_cuenta", ""),
                "mi_titulo": prev_propio["title"],
                "mi_precio": prev_propio["price"],
                "mi_sku": prev_propio["sku"],
                "comp_mla": prev_comp["item_id"],
                "comp_titulo": prev_comp["title"],
                "comp_precio": prev_comp["price"],
                "costo_erp": costo,
                "margen_min": st.session_state.get("repricing_preview_margen", 20),
            }
            st.session_state["repricing_pares"].append(nuevo_par)
            st.session_state["repricing_preview_propio"] = None
            st.session_state["repricing_preview_comp"] = None
            st.success("Par agregado")
            st.rerun()

    # ======================================================================
    # SECCION 2: DASHBOARD DE MONITOREO
    # ======================================================================
    st.markdown("---")
    st.markdown("#### 2. Dashboard de monitoreo")

    if not pares:
        st.info("Configura pares de monitoreo arriba para poder escanear.")
    else:
        if st.button("Escanear precios", key="btn_escanear_repricing"):
            st.session_state["repricing_scan"] = None
            st.session_state["repricing_confirmar_paso1"] = False
            st.session_state["repricing_confirmar_paso2"] = False

            resultados = []
            prog = st.progress(0, text="Escaneando precios...")
            tokens_cache = {}

            for i, par in enumerate(pares):
                prog.progress((i + 1) / len(pares),
                              text=f"Escaneando par {i+1}/{len(pares)}...")
                cuenta_n = par["cuenta_nombre"]

                # Obtener token (cachear por cuenta)
                if cuenta_n not in tokens_cache:
                    cuenta = next((c for c in cuentas if c["nombre"] == cuenta_n), None)
                    if cuenta:
                        tokens_cache[cuenta_n] = refresh_ml_token(cuenta)
                token = tokens_cache.get(cuenta_n)

                if not token:
                    resultados.append({
                        "par_idx": i,
                        "error": "Token no disponible",
                        **par,
                    })
                    continue

                # Obtener precio propio
                info_propio, err1 = obtener_info_item(par["mi_mla"], token)
                time.sleep(0.3)

                # Obtener precio competidor
                info_comp, err2 = obtener_info_competidor(par["comp_mla"])
                time.sleep(0.3)

                if err1 or err2:
                    resultados.append({
                        "par_idx": i,
                        "error": f"Propio: {err1 or 'OK'} | Comp: {err2 or 'OK'}",
                        **par,
                    })
                    continue

                # Obtener promos del item propio
                promos = obtener_promos(par["mi_mla"], token)
                time.sleep(0.3)

                mejor = mejor_cofundada(promos)
                precio_propio = info_propio["price"]
                precio_comp = info_comp["price"]
                costo = buscar_costo_erp(info_propio["sku"]) if info_propio["sku"] else None

                # Actualizar costo en el par
                st.session_state["repricing_pares"][i]["costo_erp"] = costo
                st.session_state["repricing_pares"][i]["mi_precio"] = precio_propio
                st.session_state["repricing_pares"][i]["comp_precio"] = precio_comp

                precio_cofundada = precio_con_cofundada(precio_propio, mejor) if mejor else None
                comision_est = round(precio_propio * 0.143, 0)
                margen_actual = calcular_margen(precio_propio, costo)
                margen_cofundada = calcular_margen(precio_cofundada, costo) if precio_cofundada else None

                diff_abs = round(precio_propio - precio_comp, 0)
                diff_pct = round((precio_propio - precio_comp) / precio_comp * 100, 1) if precio_comp > 0 else 0

                # Determinar accion sugerida
                margen_min = par.get("margen_min", 20)
                if precio_propio <= precio_comp:
                    accion = "Ya mas barato"
                elif not mejor:
                    accion = "Sin cofundada"
                elif margen_cofundada is not None and margen_cofundada < margen_min:
                    accion = "Margen insuficiente"
                else:
                    accion = "Activar cofundada"

                resultados.append({
                    "par_idx": i,
                    "mi_mla": par["mi_mla"],
                    "mi_precio": precio_propio,
                    "comp_mla": par["comp_mla"],
                    "comp_precio": precio_comp,
                    "diff_abs": diff_abs,
                    "diff_pct": diff_pct,
                    "tiene_cofundada": "Si" if mejor else "No",
                    "precio_cofundada": precio_cofundada,
                    "costo_erp": costo,
                    "comision_ml_est": comision_est,
                    "margen_actual": margen_actual,
                    "margen_cofundada": margen_cofundada,
                    "accion": accion,
                    "promo_data": mejor,
                    "cuenta_nombre": cuenta_n,
                    "mi_sku": info_propio["sku"],
                    "error": None,
                })

            prog.empty()
            st.session_state["repricing_scan"] = resultados

        # Mostrar resultados del scan
        scan = st.session_state.get("repricing_scan")
        if scan:
            # Construir tabla
            rows = []
            for r in scan:
                if r.get("error"):
                    rows.append({
                        "Mi MLA": r.get("mi_mla", ""),
                        "Mi precio": "",
                        "Comp. MLA": r.get("comp_mla", ""),
                        "Precio comp.": "",
                        "Dif ($)": "",
                        "Dif (%)": "",
                        "Cofundada": "",
                        "Precio c/cofundada": "",
                        "Costo ERP": "",
                        "Comision ML est.": "",
                        "Margen actual (%)": "",
                        "Margen c/cofundada (%)": "",
                        "Accion": f"ERROR: {r['error']}",
                    })
                else:
                    rows.append({
                        "Mi MLA": r["mi_mla"],
                        "Mi precio": f"${r['mi_precio']:,.0f}",
                        "Comp. MLA": r["comp_mla"],
                        "Precio comp.": f"${r['comp_precio']:,.0f}",
                        "Dif ($)": f"${r['diff_abs']:,.0f}",
                        "Dif (%)": f"{r['diff_pct']}%",
                        "Cofundada": r["tiene_cofundada"],
                        "Precio c/cofundada": f"${r['precio_cofundada']:,.0f}" if r["precio_cofundada"] else "N/A",
                        "Costo ERP": f"${r['costo_erp']:,.0f}" if r["costo_erp"] else "N/A",
                        "Comision ML est.": f"${r['comision_ml_est']:,.0f}" if r.get("comision_ml_est") else "N/A",
                        "Margen actual (%)": f"{r['margen_actual']}%" if r["margen_actual"] is not None else "N/A",
                        "Margen c/cofundada (%)": f"{r['margen_cofundada']}%" if r["margen_cofundada"] is not None else "N/A",
                        "Accion": r["accion"],
                    })

            df_scan = pd.DataFrame(rows)

            # Colorear filas
            def colorear_fila(row):
                accion = row.get("Accion", "")
                if "ERROR" in accion:
                    return ["background-color: #2a2a2a"] * len(row)
                if accion == "Ya mas barato":
                    return ["background-color: #0d3320"] * len(row)
                if accion == "Activar cofundada":
                    return ["background-color: #3d1f1f"] * len(row)
                if accion == "Margen insuficiente":
                    return ["background-color: #3d3d1f"] * len(row)
                return [""] * len(row)

            styled = df_scan.style.apply(colorear_fila, axis=1)
            st.dataframe(styled, use_container_width=True, hide_index=True)

            # Resumen
            n_activar = sum(1 for r in scan if r.get("accion") == "Activar cofundada")
            n_barato = sum(1 for r in scan if r.get("accion") == "Ya mas barato")
            n_sin = sum(1 for r in scan if r.get("accion") == "Sin cofundada")
            n_margen = sum(1 for r in scan if r.get("accion") == "Margen insuficiente")
            n_err = sum(1 for r in scan if r.get("error"))

            mc1, mc2, mc3, mc4, mc5 = st.columns(5)
            mc1.metric("Activar cofundada", n_activar)
            mc2.metric("Ya mas barato", n_barato)
            mc3.metric("Sin cofundada", n_sin)
            mc4.metric("Margen insuficiente", n_margen)
            mc5.metric("Errores", n_err)

            # ==================================================================
            # SECCION 3: EJECUTAR REPRICING
            # ==================================================================
            if n_activar > 0:
                st.markdown("---")
                st.markdown("#### 3. Ejecutar repricing")

                items_activar = [r for r in scan if r.get("accion") == "Activar cofundada"]

                st.warning(f"Se activaran cofundadas en **{n_activar}** items. "
                           "Esta accion modifica los precios en MercadoLibre.")

                # Paso 1 de confirmacion
                if not st.session_state["repricing_confirmar_paso1"]:
                    if st.button(f"Aplicar repricing ({n_activar} items)",
                                 key="btn_repricing_paso1"):
                        st.session_state["repricing_confirmar_paso1"] = True
                        st.rerun()
                elif not st.session_state["repricing_confirmar_paso2"]:
                    st.error("CONFIRMAR: Esto activara cofundadas y cambiara precios en ML.")
                    col_conf1, col_conf2 = st.columns(2)
                    with col_conf1:
                        if st.button("SI, CONFIRMAR REPRICING",
                                     key="btn_repricing_paso2", type="primary"):
                            st.session_state["repricing_confirmar_paso2"] = True
                            st.rerun()
                    with col_conf2:
                        if st.button("Cancelar", key="btn_repricing_cancelar"):
                            st.session_state["repricing_confirmar_paso1"] = False
                            st.session_state["repricing_confirmar_paso2"] = False
                            st.rerun()
                else:
                    # Ejecutar repricing
                    st.session_state["repricing_confirmar_paso1"] = False
                    st.session_state["repricing_confirmar_paso2"] = False

                    prog_r = st.progress(0, text="Aplicando repricing...")
                    resultados_repr = []
                    tokens_cache = {}

                    for j, item in enumerate(items_activar):
                        prog_r.progress((j + 1) / len(items_activar),
                                        text=f"Activando {j+1}/{len(items_activar)}...")

                        cuenta_n = item["cuenta_nombre"]
                        if cuenta_n not in tokens_cache:
                            cuenta = next((c for c in cuentas if c["nombre"] == cuenta_n), None)
                            if cuenta:
                                tokens_cache[cuenta_n] = refresh_ml_token(cuenta)
                        token = tokens_cache.get(cuenta_n)

                        if not token:
                            resultados_repr.append({
                                "mla": item["mi_mla"],
                                "ok": False,
                                "msg": "Token no disponible",
                            })
                            continue

                        promo = item.get("promo_data")
                        if not promo:
                            resultados_repr.append({
                                "mla": item["mi_mla"],
                                "ok": False,
                                "msg": "Sin datos de promo",
                            })
                            continue

                        # Construir body para activar cofundada
                        body = {
                            "promotion_id": promo.get("id", ""),
                            "promotion_type": "SMART",
                        }
                        # Agregar offer_id si existe (ref_id como candidata)
                        if promo.get("ref_id"):
                            body["offer_id"] = promo["ref_id"]

                        status_code, resp = ml_post(
                            f"{ML_BASE}/seller-promotions/items/{item['mi_mla']}?app_version=v2",
                            token, body)

                        ok = status_code == 201
                        resultados_repr.append({
                            "mla": item["mi_mla"],
                            "ok": ok,
                            "msg": "Activada" if ok else f"HTTP {status_code}: {str(resp)[:200]}",
                        })

                        # Guardar en log
                        st.session_state["repricing_log"].append({
                            "fecha": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            "mla": item["mi_mla"],
                            "accion": "Activar cofundada" if ok else f"Error: {str(resp)[:100]}",
                            "precio_antes": item.get("mi_precio", 0),
                            "precio_despues": item.get("precio_cofundada", 0) if ok else item.get("mi_precio", 0),
                            "margen": item.get("margen_cofundada", "N/A") if ok else item.get("margen_actual", "N/A"),
                        })

                        time.sleep(0.3)

                    prog_r.empty()

                    # Mostrar resultados
                    n_ok = sum(1 for r in resultados_repr if r["ok"])
                    n_fail = sum(1 for r in resultados_repr if not r["ok"])

                    if n_ok > 0:
                        st.success(f"Cofundadas activadas: {n_ok}/{len(resultados_repr)}")
                    if n_fail > 0:
                        st.error(f"Errores: {n_fail}/{len(resultados_repr)}")

                    for r in resultados_repr:
                        icon = "OK" if r["ok"] else "ERROR"
                        st.text(f"[{icon}] {r['mla']}: {r['msg']}")

    # ======================================================================
    # SECCION 4: HISTORIAL
    # ======================================================================
    st.markdown("---")
    st.markdown("#### 4. Historial de repricing")

    log = st.session_state.get("repricing_log", [])
    if log:
        df_log = pd.DataFrame(log)
        df_log.columns = ["Fecha/hora", "MLA", "Accion", "Precio antes",
                          "Precio despues", "Margen (%)"]
        st.dataframe(df_log, use_container_width=True, hide_index=True)

        csv_log = df_log.to_csv(index=False).encode("utf-8")
        st.download_button(
            "Descargar historial CSV",
            csv_log,
            f"repricing_log_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
            "text/csv",
            key="btn_download_repricing_log",
        )
    else:
        st.info("Sin acciones registradas todavia.")
