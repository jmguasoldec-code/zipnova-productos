"""
Tab de creacion de envios para Zipnova.
Interfaz paso a paso pensada para vendedores.
"""


def render_tab_envios(get_zn_auth, ZN_BASE):
    import streamlit as st
    import requests

    ACCOUNT_ID = 3901

    # ── helpers ──────────────────────────────────────────────────────────
    def _headers():
        return get_zn_auth()

    def _get(endpoint, params=None):
        r = requests.get(f"{ZN_BASE}{endpoint}", headers=_headers(), params=params, timeout=30)
        r.raise_for_status()
        return r.json()

    def _post(endpoint, payload):
        r = requests.post(f"{ZN_BASE}{endpoint}", headers=_headers(), json=payload, timeout=30)
        r.raise_for_status()
        return r.json()

    # ── session state defaults ───────────────────────────────────────────
    defaults = {
        "env_items": [],           # productos agregados al envio
        "env_cotizaciones": None,  # resultado de cotizacion
        "env_carrier_idx": None,   # indice de carrier elegido
        "env_creado": None,        # respuesta de envio creado
        "env_origenes": None,      # cache de origenes
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

    # ── cargar origenes (una vez) ────────────────────────────────────────
    if st.session_state["env_origenes"] is None:
        try:
            data = _get("/v2/addresses", params={"account_id": ACCOUNT_ID})
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
        col1, col2 = st.columns(2)
        with col1:
            p_sku = st.text_input("SKU *", key="env_p_sku")
            p_desc = st.text_input("Descripcion", key="env_p_desc", value="Producto")
            p_cantidad = st.number_input("Cantidad", min_value=1, value=1, step=1, key="env_p_cant")
        with col2:
            p_peso = st.number_input("Peso (gramos) *", min_value=1, value=500, step=50, key="env_p_peso")
            p_largo = st.number_input("Largo (cm) *", min_value=1, value=30, step=1, key="env_p_largo")
            p_ancho = st.number_input("Ancho (cm) *", min_value=1, value=20, step=1, key="env_p_ancho")
            p_alto = st.number_input("Alto (cm) *", min_value=1, value=10, step=1, key="env_p_alto")

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
            "account_id": ACCOUNT_ID,
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
                resp = _post("/v2/shipments/quote", payload)
                opciones = resp if isinstance(resp, list) else resp.get("data", resp.get("results", resp.get("options", [])))
                if not opciones:
                    st.error("No se encontraron opciones de envio para ese destino.")
                    st.session_state["env_cotizaciones"] = None
                else:
                    st.session_state["env_cotizaciones"] = opciones
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
            carrier_name = op.get("carrier_name") or op.get("carrier", {}).get("name", f"Carrier {idx+1}")
            service = op.get("service_type") or op.get("service", "")
            precio = op.get("price") or op.get("total_price") or op.get("amount", "—")
            tiempo = op.get("estimated_delivery") or op.get("delivery_time") or op.get("transit_days", "—")

            label = f"**{carrier_name}**  —  ${precio}  —  {tiempo} dias"
            if st.button(label, key=f"env_opt_{idx}", use_container_width=True):
                st.session_state["env_carrier_idx"] = idx
                st.rerun()

    # ── Paso 5: Confirmar y crear ────────────────────────────────────────
    if st.session_state["env_carrier_idx"] is not None and st.session_state["env_cotizaciones"]:
        elegido = st.session_state["env_cotizaciones"][st.session_state["env_carrier_idx"]]
        carrier_name = elegido.get("carrier_name") or elegido.get("carrier", {}).get("name", "—")
        precio = elegido.get("price") or elegido.get("total_price") or elegido.get("amount", "—")
        carrier_id = elegido.get("carrier_id") or elegido.get("carrier", {}).get("id")
        service_type = elegido.get("service_type") or "standard_delivery"
        logistic_type = elegido.get("logistic_type") or "carrier_dropoff"

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

        ref_externa = st.text_input("Referencia externa (opcional)", key="env_ref", placeholder="Ej: W12345")

        if st.button("Crear envio", type="primary", use_container_width=True):
            payload = {
                "account_id": ACCOUNT_ID,
                "origin_id": origin_id,
                "declared_value": float(valor_declarado),
                "external_id": ref_externa.strip() if ref_externa else None,
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
            # quitar external_id si esta vacio
            if not payload["external_id"]:
                del payload["external_id"]

            with st.spinner("Creando envio..."):
                try:
                    resp = _post("/v2/shipments", payload)
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
