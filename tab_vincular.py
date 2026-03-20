"""
Tab Vincular — Vincula productos/SKUs de Zipnova con publicaciones de MercadoLibre.
La vinculacion funciona por coincidencia de SKU: si el seller_sku del item ML
coincide con el SKU del inventario de Zipnova, estan vinculados automaticamente.
"""


def render_tab_vincular(get_zn_auth, ZN_BASE, buscar_item_ml, get_cuentas_ml, refresh_ml_token):
    import streamlit as st
    import requests

    ML_BASE = "https://api.mercadolibre.com"
    CUENTAS_ML = get_cuentas_ml()

    # ─── HELPERS ────────────────────────────────────────────────────────────
    def buscar_sku_zipnova(sku):
        """Busca un SKU en el inventario de Zipnova. Devuelve (data, error)."""
        if not sku:
            return None, "SKU vacio"
        h, acc = get_zn_auth()
        r = requests.get(f"{ZN_BASE}/inventory/search", headers=h,
                         params={"account_id": acc, "sku": sku}, timeout=15)
        if r.status_code != 200:
            return None, f"HTTP {r.status_code}"
        items = r.json().get("data", [])
        if not items:
            return None, "SKU no encontrado en Zipnova"
        return items[0], None

    def buscar_producto_zipnova(sku):
        """Busca un producto en Zipnova por reference_code (SKU)."""
        h, acc = get_zn_auth()
        r = requests.get(f"{ZN_BASE}/products/search", headers=h,
                         params={"account_id": acc, "reference_code": sku}, timeout=15)
        if r.status_code != 200:
            return None, f"HTTP {r.status_code}"
        items = r.json().get("data", [])
        if not items:
            return None, "Producto no encontrado"
        return items[0], None

    def actualizar_sku_ml(item_id, nuevo_sku, cuenta):
        """Actualiza el seller_custom_field (SKU) de un item en ML."""
        token = refresh_ml_token(cuenta)
        if not token:
            return False, "No se pudo renovar token ML"
        h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        body = {"seller_custom_field": nuevo_sku}
        r = requests.put(f"{ML_BASE}/items/{item_id}", headers=h, json=body, timeout=15)
        if r.status_code == 200:
            return True, None
        return False, f"HTTP {r.status_code} — {r.text[:200]}"

    def actualizar_sku_variacion_ml(item_id, variation_id, nuevo_sku, cuenta):
        """Actualiza el SKU de una variacion especifica."""
        token = refresh_ml_token(cuenta)
        if not token:
            return False, "No se pudo renovar token ML"
        h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        body = {"variations": [{"id": variation_id, "seller_custom_field": nuevo_sku}]}
        r = requests.put(f"{ML_BASE}/items/{item_id}", headers=h, json=body, timeout=15)
        if r.status_code == 200:
            return True, None
        return False, f"HTTP {r.status_code} — {r.text[:200]}"

    # ─── UI ─────────────────────────────────────────────────────────────────
    st.markdown("### Vincular productos ML con Zipnova")
    st.caption("La vinculacion funciona por SKU: si el SKU del item en ML coincide con un SKU en Zipnova, quedan vinculados automaticamente.")

    st.markdown("---")

    # ── Seccion 1: Buscar SKU en Zipnova ──────────────────────────────────
    st.markdown("#### 1. Buscar SKU en Zipnova")
    zn_sku_input = st.text_input("SKU a buscar en Zipnova", placeholder="Ej: KF-VIN-001", key="vinc_zn_sku")

    if st.button("Buscar en Zipnova", key="btn_vinc_zn"):
        if not zn_sku_input:
            st.warning("Ingresa un SKU")
        else:
            with st.spinner("Buscando en Zipnova..."):
                inv_data, inv_err = buscar_sku_zipnova(zn_sku_input.strip())
                prod_data, _ = buscar_producto_zipnova(zn_sku_input.strip())
            if inv_err:
                st.error(f"No encontrado: {inv_err}")
                st.session_state.pop("vinc_zn_data", None)
            else:
                st.session_state["vinc_zn_data"] = inv_data
                st.session_state["vinc_zn_prod"] = prod_data

    if "vinc_zn_data" in st.session_state:
        zn = st.session_state["vinc_zn_data"]
        attrs = zn.get("attributes", {})
        col1, col2, col3 = st.columns(3)
        with col1:
            st.markdown(f"**SKU:** `{zn.get('sku', '')}`")
            st.markdown(f"**Nombre:** {zn.get('name', '—')}")
        with col2:
            st.markdown(f"**Peso:** {attrs.get('weight', 0)} g")
            st.markdown(f"**Dimensiones:** {attrs.get('length', 0)} x {attrs.get('width', 0)} x {attrs.get('height', 0)} cm")
        with col3:
            st.markdown(f"**Valor declarado:** ${zn.get('unit_declared_value', 0)}")
            st.markdown(f"**Clasificacion:** {zn.get('classification_id', '—')}")

        prod = st.session_state.get("vinc_zn_prod")
        if prod:
            skus_prod = prod.get("skus", [])
            if skus_prod:
                st.markdown(f"**Producto Zipnova:** {prod.get('name', '')} | SKUs asociados: {', '.join(s.get('sku', '') for s in skus_prod)}")

    st.markdown("---")

    # ── Seccion 2: Buscar publicacion en ML ───────────────────────────────
    st.markdown("#### 2. Buscar publicacion en MercadoLibre")
    c1, c2 = st.columns([1, 1])
    with c1:
        ml_item_id = st.text_input("MLA ID", placeholder="MLA671628760", key="vinc_mla_id")
    with c2:
        cuenta_nombre = st.selectbox("Cuenta ML", [c["nombre"] for c in CUENTAS_ML], key="vinc_ml_cuenta")

    if st.button("Buscar en ML", key="btn_vinc_ml"):
        if not ml_item_id:
            st.warning("Ingresa un MLA ID")
        else:
            cuenta = next(c for c in CUENTAS_ML if c["nombre"] == cuenta_nombre)
            with st.spinner("Buscando en MercadoLibre..."):
                data, error = buscar_item_ml(ml_item_id.strip(), cuenta)
            if error:
                st.error(f"Error: {error}")
                st.session_state.pop("vinc_ml_data", None)
            else:
                st.session_state["vinc_ml_data"] = data
                st.session_state["vinc_ml_cuenta"] = cuenta

    if "vinc_ml_data" in st.session_state:
        ml = st.session_state["vinc_ml_data"]
        col1, col2 = st.columns([1, 2])
        with col1:
            if ml.get("thumbnail"):
                st.image(ml["thumbnail"], width=150)
        with col2:
            st.markdown(f"**{ml['name']}**")
            st.markdown(f"**MLA:** `{ml['item_id']}`")
            st.markdown(f"**SKU en ML:** `{ml['sku'] or '-- Sin SKU --'}`")
            st.markdown(f"**Precio:** ${ml['price']:,.2f} | **Peso:** {ml['weight']}g | **Dims:** {ml['length']}x{ml['width']}x{ml['height']} cm")

    st.markdown("---")

    # ── Seccion 3: Estado de vinculacion ──────────────────────────────────
    st.markdown("#### 3. Estado de vinculacion")

    if "vinc_ml_data" not in st.session_state:
        st.info("Busca primero una publicacion de ML arriba.")
    else:
        ml = st.session_state["vinc_ml_data"]
        ml_sku = (ml.get("sku") or "").strip()
        cuenta = st.session_state.get("vinc_ml_cuenta")

        if not ml_sku:
            st.warning("La publicacion de ML no tiene SKU asignado. No puede vincularse automaticamente con Zipnova.")
        else:
            # Verificar si el SKU de ML existe en Zipnova
            with st.spinner("Verificando vinculacion..."):
                zn_inv, zn_err = buscar_sku_zipnova(ml_sku)

            if zn_inv:
                st.success(f"VINCULADO: El SKU `{ml_sku}` del item ML coincide con un SKU en Zipnova.")
                attrs = zn_inv.get("attributes", {})
                st.markdown(f"**Producto Zipnova:** {zn_inv.get('name', '')} | Peso: {attrs.get('weight', 0)}g | Dims: {attrs.get('length', 0)}x{attrs.get('width', 0)}x{attrs.get('height', 0)} cm")
            else:
                st.error(f"NO VINCULADO: El SKU `{ml_sku}` del item ML no existe en Zipnova.")

        # ── Opcion A: Actualizar SKU en ML ──────────────────────────────
        st.markdown("---")
        st.markdown("#### Vincular manualmente")
        st.markdown("**Opcion A — Actualizar SKU en MercadoLibre** para que coincida con un SKU de Zipnova:")

        nuevo_sku = st.text_input(
            "SKU de Zipnova a asignar en ML",
            value=st.session_state.get("vinc_zn_data", {}).get("sku", ""),
            placeholder="Ingresa el SKU exacto de Zipnova",
            key="vinc_nuevo_sku",
        )

        if nuevo_sku:
            # Verificar que el SKU exista en Zipnova antes de asignar
            zn_check, zn_check_err = buscar_sku_zipnova(nuevo_sku.strip())
            if zn_check:
                st.caption(f"SKU `{nuevo_sku}` encontrado en Zipnova: {zn_check.get('name', '')}")
            else:
                st.caption(f"SKU `{nuevo_sku}` NO existe en Zipnova. Crealo primero.")

        if st.button("Actualizar SKU en ML", key="btn_vinc_update_ml", type="primary",
                     disabled=not nuevo_sku or not cuenta):
            zn_exists, _ = buscar_sku_zipnova(nuevo_sku.strip())
            if not zn_exists:
                st.error(f"El SKU `{nuevo_sku}` no existe en Zipnova. Crealo primero en el tab 'Manual' o 'Desde ML'.")
            else:
                with st.spinner("Actualizando SKU en ML..."):
                    ok, err = actualizar_sku_ml(ml["item_id"], nuevo_sku.strip(), cuenta)
                if ok:
                    st.success(f"SKU actualizado en ML: `{ml['item_id']}` ahora tiene SKU `{nuevo_sku}`")
                    # Actualizar datos en session
                    st.session_state["vinc_ml_data"]["sku"] = nuevo_sku.strip()
                else:
                    st.error(f"Error al actualizar: {err}")

        # ── Opcion B: Guia manual desde panel Zipnova ───────────────────
        st.markdown("---")
        st.markdown("**Opcion B — Vincular desde el panel web de Zipnova**")
        st.markdown("""
Si necesitas una vinculacion mas avanzada (multiples SKUs por producto, reglas de empaque, etc.)
que no se puede hacer solo con el match de SKU, segui estos pasos en el panel de Zipnova:

1. Ingresa a [panel.zipnova.com.ar](https://panel.zipnova.com.ar)
2. Ir a **Inventario** > buscar el SKU del producto
3. Editar el producto y en la seccion **Integraciones** / **Marketplace**:
   - Asociar el MLA ID de MercadoLibre
   - Configurar reglas de empaque si el producto tiene multiples SKUs
4. Guardar cambios

**Nota:** La API de Zipnova v2 no expone un endpoint directo para vincular un MLA ID
a un producto. La vinculacion automatica se basa exclusivamente en la coincidencia de SKU:
cuando llega una orden con un `sku` que coincide con el inventario de Zipnova, se asocia
automaticamente. Por eso, lo mas importante es que el `seller_custom_field` (SKU) en ML
sea identico al SKU registrado en Zipnova.
""")

    # ── Seccion 4: Vinculacion masiva (vista rapida) ────────────────────
    st.markdown("---")
    st.markdown("#### Verificacion rapida de vinculacion por cuenta")
    st.caption("Compara los SKUs de items activos en ML contra el inventario de Zipnova.")

    cuenta_masiva = st.selectbox("Cuenta ML", [c["nombre"] for c in CUENTAS_ML], key="vinc_masiva_cuenta")
    limite = st.slider("Items a verificar", min_value=10, max_value=200, value=50, step=10, key="vinc_masiva_limite")

    if st.button("Verificar vinculacion", key="btn_vinc_masiva"):
        cuenta = next(c for c in CUENTAS_ML if c["nombre"] == cuenta_masiva)
        token = refresh_ml_token(cuenta)
        if not token:
            st.error("No se pudo renovar token ML")
        else:
            # Cargar SKUs de Zipnova
            with st.spinner("Cargando inventario Zipnova..."):
                h_zn, acc = get_zn_auth()
                zn_skus = set()
                page = 1
                while True:
                    r = requests.get(f"{ZN_BASE}/inventory/search", headers=h_zn,
                                     params={"account_id": acc, "per_page": 100, "page": page}, timeout=15)
                    if r.status_code != 200:
                        break
                    data_zn = r.json()
                    for it in data_zn.get("data", []):
                        zn_skus.add(it["sku"].upper())
                    if page >= data_zn.get("meta", {}).get("last_page", 1):
                        break
                    page += 1

            # Cargar items de ML
            with st.spinner("Cargando items de ML..."):
                ids = []
                off = 0
                while len(ids) < limite:
                    r = requests.get(f"{ML_BASE}/users/{cuenta['user_id']}/items/search",
                                     headers={"Authorization": f"Bearer {token}"},
                                     params={"status": "active", "offset": off, "limit": 50}, timeout=15)
                    if r.status_code != 200:
                        break
                    resp_ml = r.json()
                    ids.extend(resp_ml.get("results", []))
                    if len(ids) >= resp_ml.get("paging", {}).get("total", 0):
                        break
                    off += 50
                ids = ids[:limite]

            # Comparar
            vinculados = []
            no_vinculados = []
            sin_sku = []
            prog = st.progress(0)
            import time
            for i, iid in enumerate(ids):
                prog.progress((i + 1) / len(ids))
                ml_data, err = buscar_item_ml(iid, cuenta)
                if not ml_data:
                    continue
                ml_sku = (ml_data.get("sku") or "").strip()
                if not ml_sku:
                    sin_sku.append({"MLA": iid, "Producto": ml_data["name"][:50], "SKU ML": "—", "Estado": "Sin SKU"})
                elif ml_sku.upper() in zn_skus:
                    vinculados.append({"MLA": iid, "Producto": ml_data["name"][:50], "SKU ML": ml_sku, "Estado": "Vinculado"})
                else:
                    no_vinculados.append({"MLA": iid, "Producto": ml_data["name"][:50], "SKU ML": ml_sku, "Estado": "No en Zipnova"})
                time.sleep(0.05)
            prog.empty()

            # Metricas
            m1, m2, m3 = st.columns(3)
            m1.metric("Vinculados", len(vinculados))
            m2.metric("No en Zipnova", len(no_vinculados))
            m3.metric("Sin SKU en ML", len(sin_sku))

            # Tabla de problemas
            problemas = no_vinculados + sin_sku
            if problemas:
                import pandas as pd
                df = pd.DataFrame(problemas)
                st.dataframe(df, use_container_width=True, hide_index=True)
                st.download_button(
                    "Descargar CSV",
                    df.to_csv(index=False).encode("utf-8"),
                    f"vinculacion_{cuenta_masiva}.csv",
                    "text/csv",
                    key="btn_vinc_download",
                )
            else:
                st.success("Todos los items verificados estan vinculados con Zipnova.")
