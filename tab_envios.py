"""
Tab de creacion de envios para Zipnova.
Interfaz paso a paso pensada para vendedores.
"""


def render_tab_envios(get_zn_auth, ZN_BASE):
    import streamlit as st
    import requests
    import re
    import time

    # ── helpers ──────────────────────────────────────────────────────────
    def _auth():
        h, acc = get_zn_auth()
        return h, acc

    def _get(endpoint, params=None):
        h, acc = _auth()
        p = {"account_id": acc}
        if params:
            p.update(params)
        r = requests.get(f"{ZN_BASE}{endpoint}", headers=h, params=p, timeout=30)
        r.raise_for_status()
        return r.json()

    def _post(endpoint, payload):
        h, acc = _auth()
        if "account_id" not in payload:
            payload["account_id"] = acc
        r = requests.post(f"{ZN_BASE}{endpoint}", headers=h, json=payload, timeout=30)
        r.raise_for_status()
        return r.json()

    # ── session state defaults ───────────────────────────────────────────
    defaults = {
        "env_items": [],           # productos agregados al envio
        "env_cotizaciones": None,  # resultado de cotizacion
        "env_carrier_idx": None,   # indice de carrier elegido
        "env_creado": None,        # respuesta de envio creado
        "env_origenes": None,      # cache de origenes
        "env_zn_found": None,      # SKU encontrado en Zipnova
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

    # ── cargar origenes (una vez) ────────────────────────────────────────
    if st.session_state["env_origenes"] is None:
        try:
            data = _get("/addresses")
            origenes = data if isinstance(data, list) else data.get("data", data.get("results", []))
            st.session_state["env_origenes"] = origenes if origenes else []
        except Exception as e:
            st.error(f"No se pudieron cargar los origenes: {e}")
            st.session_state["env_origenes"] = []

    origenes = st.session_state["env_origenes"]

    # ── titulo ───────────────────────────────────────────────────────────
    st.markdown("### Crear envio")

    # si ya se creo un envio, mostrar resultado y boton para nuevo envio
    if st.session_state["env_creado"] is not None:
        _render_resultado(st, st.session_state["env_creado"])
        if st.button("Crear otro envio", use_container_width=True):
            _reset_state(st)
            st.rerun()
        return

    # ── Paso 1: Origen ───────────────────────────────────────────────────
    st.markdown("#### 1. Origen del envio")
    if origenes:
        origen_labels = [
            f"{o.get('alias') or o.get('name', '')} — {o.get('street', '')} {o.get('street_number', '')}, {o.get('city', '')}"
            for o in origenes
        ]
        origen_idx = st.selectbox("Direccion de origen", range(len(origen_labels)), format_func=lambda i: origen_labels[i])
        origin_id = origenes[origen_idx].get("id")
    else:
        st.warning("No hay direcciones de origen configuradas en Zipnova.")
        return

    st.divider()

    # ── Paso 2: Destinatario ─────────────────────────────────────────────
    st.markdown("#### 2. Datos del destinatario")
    col_a, col_b = st.columns(2)
    with col_a:
        dest_nombre = st.text_input("Nombre completo *", key="env_dest_nombre")
        dest_telefono = st.text_input("Telefono *", key="env_dest_tel")
        dest_email = st.text_input("Email", key="env_dest_email")
        dest_dni = st.text_input("DNI *", key="env_dest_dni")
    with col_b:
        dest_calle = st.text_input("Calle *", key="env_dest_calle")
        dest_numero = st.text_input("Numero *", key="env_dest_num")
        dest_ciudad = st.text_input("Ciudad *", key="env_dest_ciudad")
        dest_provincia = st.text_input("Provincia *", key="env_dest_prov")
        dest_cp = st.text_input("Codigo Postal *", key="env_dest_cp")

    st.divider()

    # ── Paso 3: Productos ────────────────────────────────────────────────
    st.markdown("#### 3. Productos a enviar")

    with st.expander("Agregar producto", expanded=len(st.session_state["env_items"]) == 0):
        p_sku = st.text_input("SKU *", key="env_p_sku")

        # Autocompletar desde Zipnova al ingresar SKU
        if p_sku and len(p_sku.strip()) >= 2:
            if st.button("🔍 Buscar SKU", key="env_buscar_sku"):
                try:
                    h_zn, acc = _auth()
                    r_zn = requests.get(f"{ZN_BASE}/inventory/search", headers=h_zn,
                                        params={"account_id": acc, "sku": p_sku.strip()}, timeout=10)
                    if r_zn.status_code == 200:
                        items_zn = r_zn.json().get("data", [])
                        if items_zn:
                            zn = items_zn[0]
                            attrs = zn.get("attributes", {})
                            st.session_state["env_zn_found"] = {
                                "name": zn.get("name", "Producto"),
                                "weight": int(attrs.get("weight", 0) or 0),
                                "length": int(attrs.get("length", 0) or 0),
                                "width": int(attrs.get("width", 0) or 0),
                                "height": int(attrs.get("height", 0) or 0),
                            }
                            st.rerun()
                        else:
                            st.session_state["env_zn_found"] = None
                            st.warning(f"⚠️ SKU `{p_sku.strip()}` no encontrado en Zipnova. Completá los datos manualmente.")
                except Exception as e:
                    st.error(f"Error buscando SKU: {e}")

        zn_found = st.session_state.get("env_zn_found")
        if zn_found:
            st.success(f"✅ Encontrado: **{zn_found['name']}** | {zn_found['weight']}g | {zn_found['length']}×{zn_found['width']}×{zn_found['height']} cm")

        col1, col2 = st.columns(2)
        with col1:
            p_desc = st.text_input("Descripcion", key="env_p_desc",
                                   value=zn_found["name"] if zn_found else "Producto")
            p_cantidad = st.number_input("Cantidad", min_value=1, value=1, step=1, key="env_p_cant")
        with col2:
            p_peso = st.number_input("Peso (gramos) *", min_value=1, value=zn_found["weight"] if zn_found and zn_found["weight"] > 0 else 500, step=50, key="env_p_peso")
            p_largo = st.number_input("Largo (cm) *", min_value=1, value=zn_found["length"] if zn_found and zn_found["length"] > 0 else 30, step=1, key="env_p_largo")
            p_ancho = st.number_input("Ancho (cm) *", min_value=1, value=zn_found["width"] if zn_found and zn_found["width"] > 0 else 20, step=1, key="env_p_ancho")
            p_alto = st.number_input("Alto (cm) *", min_value=1, value=zn_found["height"] if zn_found and zn_found["height"] > 0 else 10, step=1, key="env_p_alto")

        if st.button("Agregar producto", type="primary"):
            if not p_sku:
                st.warning("Completa el SKU del producto.")
            else:
                for _ in range(int(p_cantidad)):
                    st.session_state["env_items"].append({
                        "sku": p_sku.strip(),
                        "description": p_desc.strip() or "Producto",
                        "weight": int(p_peso),
                        "length": int(p_largo),
                        "width": int(p_ancho),
                        "height": int(p_alto),
                    })
                # limpiar cotizacion anterior si cambian items
                st.session_state["env_cotizaciones"] = None
                st.session_state["env_carrier_idx"] = None
                st.rerun()

    # mostrar items agregados
    if st.session_state["env_items"]:
        st.markdown(f"**Productos en el envio ({len(st.session_state['env_items'])}):**")
        for i, item in enumerate(st.session_state["env_items"]):
            cols = st.columns([4, 1])
            with cols[0]:
                st.text(f"{item['sku']} — {item['description']}  |  {item['weight']}g  |  {item['length']}x{item['width']}x{item['height']} cm")
            with cols[1]:
                if st.button("Quitar", key=f"env_rm_{i}"):
                    st.session_state["env_items"].pop(i)
                    st.session_state["env_cotizaciones"] = None
                    st.session_state["env_carrier_idx"] = None
                    st.rerun()
    else:
        st.info("Agrega al menos un producto para continuar.")
        return

    st.divider()

    # ── valor declarado ──────────────────────────────────────────────────
    valor_declarado = st.number_input("Valor declarado del envio ($) *", min_value=0.0, value=0.0, step=100.0, key="env_valor")

    st.divider()

    # ── Paso 4: Cotizar ─────────────────────────────────────────────────
    st.markdown("#### 4. Cotizar envio")

    # validacion minima
    campos_ok = all([dest_nombre, dest_telefono, dest_dni, dest_calle, dest_numero, dest_ciudad, dest_provincia, dest_cp])

    if not campos_ok:
        st.warning("Completa todos los campos obligatorios (*) del destinatario para cotizar.")

    if st.button("Cotizar envio", type="primary", disabled=not campos_ok, use_container_width=True):
        payload = {
            "account_id": _auth()[1],
            "origin_id": origin_id,
            "declared_value": float(valor_declarado),
            "destination": {
                "city": dest_ciudad.strip(),
                "state": dest_provincia.strip(),
                "zipcode": dest_cp.strip(),
            },
            "items": [
                {
                    "sku": it["sku"],
                    "weight": it["weight"],
                    "length": it["length"],
                    "width": it["width"],
                    "height": it["height"],
                    "description": it["description"],
                }
                for it in st.session_state["env_items"]
            ],
        }
        with st.spinner("Cotizando..."):
            try:
                resp = _post("/shipments/quote", payload)
                # Zipnova devuelve results como dict {service_type: {carrier, amounts, ...}}
                # y all_results como dict {service_type: [{carrier, amounts, ...}, ...]}
                opciones_flat = []
                all_res = resp.get("all_results", {})
                if isinstance(all_res, dict):
                    for stype, carriers in all_res.items():
                        if isinstance(carriers, list):
                            for c in carriers:
                                c["_service_key"] = stype
                                opciones_flat.append(c)
                        elif isinstance(carriers, dict):
                            carriers["_service_key"] = stype
                            opciones_flat.append(carriers)
                # Fallback a results si all_results vacío
                if not opciones_flat:
                    results = resp.get("results", {})
                    if isinstance(results, dict):
                        for stype, data in results.items():
                            if isinstance(data, dict):
                                data["_service_key"] = stype
                                opciones_flat.append(data)

                if not opciones_flat:
                    st.error("No se encontraron opciones de envio para ese destino.")
                    st.session_state["env_cotizaciones"] = None
                else:
                    st.session_state["env_cotizaciones"] = opciones_flat
                    st.session_state["env_carrier_idx"] = None
                    st.rerun()
            except requests.exceptions.HTTPError as e:
                body = ""
                try:
                    body = e.response.text
                except Exception:
                    pass
                st.error(f"Error al cotizar: {e}\n{body}")
            except Exception as e:
                st.error(f"Error al cotizar: {e}")

    # ── mostrar opciones de cotizacion ───────────────────────────────────
    if st.session_state["env_cotizaciones"]:
        st.markdown("##### Opciones disponibles")
        opciones = st.session_state["env_cotizaciones"]
        for idx, op in enumerate(opciones):
            carrier = op.get("carrier", {})
            carrier_name = carrier.get("name", f"Carrier {idx+1}") if isinstance(carrier, dict) else str(carrier)
            amounts = op.get("amounts", {})
            precio = amounts.get("price_incl_tax", amounts.get("price", 0))
            dt = op.get("delivery_time", {})
            dias_max = dt.get("max", "?") if isinstance(dt, dict) else str(dt)
            servicio = op.get("_service_key", "")

            label = f"**{carrier_name}** — ${precio:,.2f} — {dias_max} días — {servicio}"
            if st.button(label, key=f"env_opt_{idx}", use_container_width=True):
                st.session_state["env_carrier_idx"] = idx
                st.rerun()

    # ── Paso 5: Confirmar y crear ────────────────────────────────────────
    if st.session_state["env_carrier_idx"] is not None and st.session_state["env_cotizaciones"]:
        elegido = st.session_state["env_cotizaciones"][st.session_state["env_carrier_idx"]]
        carrier = elegido.get("carrier", {})
        carrier_name = carrier.get("name", "—") if isinstance(carrier, dict) else str(carrier)
        amounts = elegido.get("amounts", {})
        precio = amounts.get("price_incl_tax", amounts.get("price", "—"))
        carrier_id = carrier.get("id") if isinstance(carrier, dict) else elegido.get("carrier_id")
        # _service_key es el string que guardamos al parsear la cotización (ej: "standard_delivery")
        service_type = str(elegido.get("_service_key", "standard_delivery"))
        logistic_type = str(elegido.get("logistic_type", "carrier_dropoff"))

        st.divider()
        st.markdown("#### 5. Confirmar envio")
        st.success(f"Opcion seleccionada: **{carrier_name}** — ${precio}")

        with st.container(border=True):
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("**Destinatario**")
                st.text(f"{dest_nombre}")
                st.text(f"{dest_calle} {dest_numero}")
                st.text(f"{dest_ciudad}, {dest_provincia} ({dest_cp})")
                st.text(f"Tel: {dest_telefono} | DNI: {dest_dni}")
            with c2:
                st.markdown("**Productos**")
                for it in st.session_state["env_items"]:
                    st.text(f"{it['sku']} — {it['weight']}g")

        ref_externa = st.text_input("Referencia externa (opcional)", key="env_ref", placeholder="Ej: W12345",
                                    help="Solo letras, números, guiones y guiones bajos. Sin espacios.")

        if st.button("Crear envio", type="primary", use_container_width=True):
            payload = {
                "account_id": _auth()[1],
                "origin_id": origin_id,
                "declared_value": float(valor_declarado),
                "external_id": re.sub(r"[^a-zA-Z0-9_\-]", "_", ref_externa.strip())[:30] if ref_externa.strip() else f"ZN{int(time.time())}",
                "destination": {
                    "name": dest_nombre.strip(),
                    "street": dest_calle.strip(),
                    "street_number": dest_numero.strip(),
                    "document": dest_dni.strip(),
                    "email": dest_email.strip() if dest_email else "",
                    "phone": dest_telefono.strip(),
                    "city": dest_ciudad.strip(),
                    "state": dest_provincia.strip(),
                    "zipcode": dest_cp.strip(),
                },
                "items": [
                    {
                        "sku": it["sku"],
                        "weight": it["weight"],
                        "length": it["length"],
                        "width": it["width"],
                        "height": it["height"],
                    }
                    for it in st.session_state["env_items"]
                ],
                "logistic_type": logistic_type,
                "service_type": service_type,
                "carrier_id": carrier_id,
            }
            with st.spinner("Creando envio..."):
                try:
                    resp = _post("/shipments", payload)
                    st.session_state["env_creado"] = resp
                    st.rerun()
                except requests.exceptions.HTTPError as e:
                    body = ""
                    try:
                        body = e.response.text
                    except Exception:
                        pass
                    st.error(f"Error al crear el envio: {e}\n{body}")
                except Exception as e:
                    st.error(f"Error al crear el envio: {e}")


def _render_resultado(st, resp):
    """Muestra el resultado de un envio creado exitosamente."""
    st.success("Envio creado exitosamente!")

    tracking = resp.get("tracking_number") or resp.get("tracking_id") or resp.get("id", "—")
    status = resp.get("status") or resp.get("state", "—")
    label_url = resp.get("label_url") or resp.get("label", {}).get("url") if isinstance(resp.get("label"), dict) else resp.get("label_url")

    with st.container(border=True):
        st.markdown(f"**Numero de tracking:** `{tracking}`")
        st.markdown(f"**Estado:** {status}")
        if label_url:
            st.markdown(f"[Descargar etiqueta]({label_url})")

    st.json(resp, expanded=False)


def _reset_state(st):
    """Limpia el estado para un nuevo envio."""
    st.session_state["env_items"] = []
    st.session_state["env_cotizaciones"] = None
    st.session_state["env_carrier_idx"] = None
    st.session_state["env_creado"] = None
