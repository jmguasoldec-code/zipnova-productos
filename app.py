#!/usr/bin/env python3
"""
App web para gestión de productos en Zipnova.
Permite crear productos desde ML, WooCommerce o manualmente.
Deploy: Streamlit Cloud
"""

import os, json, re, base64, time
import streamlit as st
import requests
from tab_envios import render_tab_envios
from tab_vincular import render_tab_vincular

# ─── CONFIG ──────────────────────────────────────────────────────────────────
ML_BASE = "https://api.mercadolibre.com"
ZN_BASE = "https://api.zipnova.com.ar/v2"


def get_cuentas_ml():
    return [
        {"nombre": "GUALASD",   "user_id": st.secrets["ml_gualasd"]["user_id"],   "client_id": st.secrets["ml_gualasd"]["client_id"],   "client_secret": st.secrets["ml_gualasd"]["client_secret"],   "token_key": "ml_gualasd"},
        {"nombre": "DECO-GSD",  "user_id": st.secrets["ml_decogsd"]["user_id"],   "client_id": st.secrets["ml_decogsd"]["client_id"],   "client_secret": st.secrets["ml_decogsd"]["client_secret"],   "token_key": "ml_decogsd"},
        {"nombre": "NAMAH-ARG", "user_id": st.secrets["ml_namah"]["user_id"],     "client_id": st.secrets["ml_namah"]["client_id"],     "client_secret": st.secrets["ml_namah"]["client_secret"],     "token_key": "ml_namah"},
        {"nombre": "TVOXS",     "user_id": st.secrets["ml_tvoxs"]["user_id"],     "client_id": st.secrets["ml_tvoxs"]["client_id"],     "client_secret": st.secrets["ml_tvoxs"]["client_secret"],     "token_key": "ml_tvoxs"},
    ]


# ─── COSTOS ERP ──────────────────────────────────────────────────────────────
@st.cache_data(ttl=3600)
def get_dolar_ccl():
    try:
        r = requests.get("https://dolarapi.com/v1/dolares/contadoconliqui", timeout=10)
        if r.status_code == 200:
            return float(r.json().get("venta", 1400))
    except Exception:
        pass
    return 1400.0


@st.cache_data(ttl=300)
def cargar_costos_erp():
    """Carga costos del ERP desde archivo subido o local."""
    erp_path = os.path.join(os.path.dirname(__file__), "costos_erp.xlsx")
    if not os.path.exists(erp_path):
        return {}
    import openpyxl
    ccl = get_dolar_ccl()
    wb = openpyxl.load_workbook(erp_path, read_only=True)
    ws = wb.active
    costos = {}
    for row in ws.iter_rows(min_row=2, values_only=True):
        sku = str(row[0] or "").strip()
        costo_str = str(row[2] or "").strip()
        if not sku or not costo_str:
            continue
        try:
            num = float(re.sub(r"[^\d.]", "", costo_str.split()[0].replace(",", "")))
        except (ValueError, IndexError):
            continue
        if "USD" in costo_str.upper():
            num = round(num * ccl, 2)
        costos[sku.upper()] = num
    wb.close()
    return costos


def buscar_costo_erp(sku):
    if not sku:
        return None
    return cargar_costos_erp().get(sku.upper())


# ─── ZIPNOVA API ─────────────────────────────────────────────────────────────
def get_zn_auth():
    api_key = st.secrets["zipnova"]["api_key"]
    api_secret = st.secrets["zipnova"]["api_secret"]
    account_id = st.secrets["zipnova"]["account_id"]
    creds = base64.b64encode(f"{api_key}:{api_secret}".encode()).decode()
    return {"Authorization": f"Basic {creds}", "Accept": "application/json", "Content-Type": "application/json"}, account_id


def zn_sku_exists(sku):
    h, acc = get_zn_auth()
    r = requests.get(f"{ZN_BASE}/inventory/search", headers=h,
                     params={"account_id": acc, "sku": sku}, timeout=15)
    if r.status_code == 200:
        return len(r.json().get("data", [])) > 0
    return False


def crear_en_zipnova(sku, name, weight, length, width, height, price):
    h, acc = get_zn_auth()
    sku_body = {
        "account_id": acc, "sku": sku, "name": name,
        "classification_id": 1, "unit_declared_value": price, "currency": "ARS",
        "weight": max(weight, 1), "length": max(length, 1),
        "width": max(width, 1), "height": max(height, 1),
    }
    r1 = requests.post(f"{ZN_BASE}/inventory", headers=h, json=sku_body, timeout=15)
    prod_body = {"reference_code": sku, "name": name, "skus": [{"sku": sku, "units": 1}]}
    r2 = requests.post(f"{ZN_BASE}/products", headers=h, json=prod_body, timeout=15)
    if r2.status_code in (200, 201):
        return True, r2.json()
    return False, f"SKU: HTTP {r1.status_code} | Producto: HTTP {r2.status_code} — {r2.text[:300]}"


# ─── ML API ──────────────────────────────────────────────────────────────────
def refresh_ml_token(cuenta):
    token_key = cuenta["token_key"]
    refresh_tok = st.secrets[token_key].get("refresh_token", "")
    if not refresh_tok:
        return None
    r = requests.post(f"{ML_BASE}/oauth/token", json={
        "grant_type": "refresh_token",
        "client_id": cuenta["client_id"],
        "client_secret": cuenta["client_secret"],
        "refresh_token": refresh_tok,
    }, timeout=10)
    if r.status_code == 200:
        data = r.json()
        # En cloud no podemos escribir secrets, guardamos en session_state
        st.session_state[f"ml_token_{token_key}"] = data["access_token"]
        return data["access_token"]
    # Intentar con token guardado en session_state
    return st.session_state.get(f"ml_token_{token_key}")


def buscar_item_ml(item_id, cuenta):
    token = refresh_ml_token(cuenta)
    if not token:
        return None, "No se pudo renovar token ML"
    h = {"Authorization": f"Bearer {token}"}
    r = requests.get(f"{ML_BASE}/items/{item_id}", headers=h,
                     params={"include_attributes": "all"}, timeout=15)
    if r.status_code != 200:
        return None, f"HTTP {r.status_code}"
    item = r.json()

    weight, length, width, height = 0, 0, 0, 0
    dims_str = (item.get("shipping") or {}).get("dimensions") or ""
    if dims_str:
        try:
            parts = dims_str.split(",")
            peso_g = int(parts[1]) if len(parts) > 1 else 0
            dim_parts = parts[0].split("x")
            if len(dim_parts) == 3:
                height, length, width = int(dim_parts[0]), int(dim_parts[1]), int(dim_parts[2])
            weight = peso_g
        except (ValueError, IndexError):
            pass

    if weight == 0 and length == 0:
        for a in item.get("attributes", []):
            aid = a.get("id", "")
            name = a.get("value_name", "") or ""
            try:
                num = float(re.sub(r"[^\d.]", "", name)) if name else 0
            except ValueError:
                num = 0
            if aid == "PACKAGE_WEIGHT":
                weight = int(num * 1000) if "kg" in name.lower() else int(num)
            elif aid == "PACKAGE_LENGTH":
                if "mm" in name.lower(): length = max(1, int(num / 10))
                elif "cm" in name.lower(): length = int(num)
                else: length = int(num * 100)
            elif aid == "PACKAGE_WIDTH":
                if "mm" in name.lower(): width = max(1, int(num / 10))
                elif "cm" in name.lower(): width = int(num)
                else: width = int(num * 100)
            elif aid == "PACKAGE_HEIGHT":
                if "mm" in name.lower(): height = max(1, int(num / 10))
                elif "cm" in name.lower(): height = int(num)
                else: height = int(num * 100)

    # SKU: prioridad SELLER_SKU (atributo) > variaciones > seller_custom_field
    sku = ""
    for a in item.get("attributes", []):
        if a.get("id") == "SELLER_SKU":
            sku = a.get("value_name", "") or ""
            break
    if not sku:
        for v in item.get("variations", []):
            sku = v.get("seller_custom_field") or ""
            if sku:
                break
    if not sku:
        sku = item.get("seller_custom_field") or ""

    thumbnail = item.get("thumbnail") or item.get("secure_thumbnail") or ""
    logistic_type = (item.get("shipping") or {}).get("logistic_type", "")
    return {
        "item_id": item.get("id", ""),
        "sku": sku,
        "name": item.get("title", ""),
        "price": float(item.get("price", 0) or 0),
        "weight": weight, "length": length, "width": width, "height": height,
        "thumbnail": thumbnail,
        "logistic_type": logistic_type,
    }, None


# ─── WOOCOMMERCE API ─────────────────────────────────────────────────────────
def buscar_producto_woo(ref):
    woo_url = st.secrets["woocommerce"]["url"]
    ck = st.secrets["woocommerce"]["consumer_key"]
    cs = st.secrets["woocommerce"]["consumer_secret"]
    params = {"consumer_key": ck, "consumer_secret": cs}
    base = f"{woo_url}/wp-json/wc/v3"

    try:
        r = requests.get(f"{base}/products/{ref}", params=params, timeout=60)
        if r.status_code != 200:
            r = requests.get(f"{base}/products", params={**params, "sku": ref}, timeout=60)
            if r.status_code == 200 and r.json():
                product = r.json()[0]
            else:
                return None, f"No se encontró producto {ref}"
        else:
            product = r.json()
    except requests.exceptions.Timeout:
        return None, "Timeout al conectar con WooCommerce. Intentá de nuevo."
    except Exception as e:
        return None, f"Error de conexión: {e}"

    dims = product.get("dimensions", {})
    weight_kg = float(product.get("weight", 0) or 0)
    images = product.get("images", [])
    thumbnail = images[0].get("src", "") if images else ""
    return {
        "sku": product.get("sku", ""),
        "name": product.get("name", ""),
        "price": float(product.get("price", 0) or 0),
        "weight": int(weight_kg * 1000),
        "length": int(float(dims.get("length", 0) or 0)),
        "width": int(float(dims.get("width", 0) or 0)),
        "height": int(float(dims.get("height", 0) or 0)),
        "thumbnail": thumbnail,
    }, None


# ─── STREAMLIT APP ───────────────────────────────────────────────────────────
st.set_page_config(page_title="Zipnova — Productos", page_icon="📦", layout="wide")

st.markdown("""
<style>
    .stApp { background-color: #0E1117; }
</style>
""", unsafe_allow_html=True)


# ─── LOGIN ───────────────────────────────────────────────────────────────────
def check_password():
    if "authenticated" not in st.session_state:
        st.session_state["authenticated"] = False
    if st.session_state["authenticated"]:
        return True
    st.title("🔒 Zipnova — Productos")
    st.caption("Guala Soluciones Decorativas")
    pwd = st.text_input("Contraseña", type="password", key="login_pwd")
    if st.button("Ingresar", type="primary"):
        if pwd == st.secrets["passwords"]["password"]:
            st.session_state["authenticated"] = True
            st.rerun()
        else:
            st.error("Contraseña incorrecta")
    return False


if not check_password():
    st.stop()

st.title("📦 Zipnova — Gestión de Productos")
st.caption("Guala Soluciones Decorativas")

tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(["🛒 Desde ML", "🌐 Desde Woo", "✏️ Manual", "🔍 Verificar", "📦 Crear Envío", "🔗 Vincular"])

CUENTAS_ML = get_cuentas_ml()

# ─── TAB 1: DESDE MERCADOLIBRE ──────────────────────────────────────────────
with tab1:
    col1, col2 = st.columns([1, 1])
    with col1:
        mla_id = st.text_input("MLA ID", placeholder="MLA671628760", key="mla_id")
    with col2:
        cuenta_nombre = st.selectbox("Cuenta ML", [c["nombre"] for c in CUENTAS_ML], key="ml_cuenta")

    if st.button("🔍 Buscar en ML", key="btn_buscar_ml"):
        if mla_id:
            cuenta = next(c for c in CUENTAS_ML if c["nombre"] == cuenta_nombre)
            with st.spinner("Buscando en MercadoLibre..."):
                data, error = buscar_item_ml(mla_id.strip(), cuenta)
            if error:
                st.error(f"Error: {error}")
            else:
                st.session_state["ml_preview"] = data

    if "ml_preview" in st.session_state:
        data = st.session_state["ml_preview"]
        st.markdown("### Preview")
        c1, c2 = st.columns([1, 2])
        with c1:
            if data["thumbnail"]:
                st.image(data["thumbnail"], width=200)
        with c2:
            st.markdown(f"**{data['name']}**")
            st.markdown(f"SKU detectado: `{data['sku'] or '⚠️ Sin SKU'}`")
            st.markdown(f"Precio ML: ${data['price']:,.2f} | Peso: {data['weight']}g | {data['length']}×{data['width']}×{data['height']} cm")

        st.markdown("---")
        st.markdown("### Editar antes de crear")
        ec1, ec2, ec3, ec4 = st.columns(4)
        with ec1:
            edit_sku = st.text_input("SKU (editable)", value=data["sku"] or "", placeholder="SKU real", key="edit_sku_ml")
        with ec2:
            edit_weight = st.number_input("Peso (g)", value=data["weight"], min_value=0, key="edit_w_ml")
        with ec3:
            edit_length = st.number_input("Largo (cm)", value=data["length"], min_value=0, key="edit_l_ml")
        with ec4:
            edit_width = st.number_input("Ancho (cm)", value=data["width"], min_value=0, key="edit_wi_ml")

        ec5, ec6 = st.columns(2)
        with ec5:
            edit_height = st.number_input("Alto (cm)", value=data["height"], min_value=0, key="edit_h_ml")
        with ec6:
            costo_erp = buscar_costo_erp(edit_sku) if edit_sku else None
            edit_price = st.number_input("Costo c/IVA ($)", value=costo_erp or data["price"], min_value=0.0, key="edit_p_ml")
            if costo_erp:
                st.caption(f"✅ Costo ERP: ${costo_erp:,.2f}")
            elif edit_sku:
                st.caption("⚠️ No encontrado en ERP")

        edit_name = st.text_input("Nombre", value=data["name"], key="edit_name_ml")
        exists = zn_sku_exists(edit_sku) if edit_sku else False
        if exists:
            st.warning(f"⚠️ SKU `{edit_sku}` ya existe en Zipnova")
        if st.button("✅ Crear en Zipnova", key="btn_crear_ml", disabled=exists or not edit_sku, type="primary"):
            with st.spinner("Creando..."):
                ok, resp = crear_en_zipnova(edit_sku, edit_name, edit_weight, edit_length, edit_width, edit_height, edit_price)
            if ok:
                st.success(f"Creado (ID: {resp.get('id', '?')})")
                del st.session_state["ml_preview"]
            else:
                st.error(f"Error: {resp}")

# ─── TAB 2: DESDE WOOCOMMERCE ───────────────────────────────────────────────
with tab2:
    woo_ref = st.text_input("ID o SKU", placeholder="22345 o SKU-123", key="woo_ref")
    if st.button("🔍 Buscar en WooCommerce", key="btn_buscar_woo"):
        if woo_ref:
            with st.spinner("Buscando..."):
                data, error = buscar_producto_woo(woo_ref.strip())
            if error:
                st.error(f"Error: {error}")
            else:
                st.session_state["woo_preview"] = data

    if "woo_preview" in st.session_state:
        data = st.session_state["woo_preview"]
        st.markdown("### Preview")
        c1, c2 = st.columns([1, 2])
        with c1:
            if data.get("thumbnail"):
                st.image(data["thumbnail"], width=200)
        with c2:
            st.markdown(f"**{data['name']}**")
            st.markdown(f"SKU: `{data['sku'] or '⚠️ Sin SKU'}` | ${data['price']:,.2f} | {data['weight']}g | {data['length']}×{data['width']}×{data['height']} cm")

        st.markdown("---")
        ec1, ec2, ec3, ec4 = st.columns(4)
        with ec1:
            edit_sku_w = st.text_input("SKU", value=data["sku"], key="edit_sku_woo")
        with ec2:
            edit_weight_w = st.number_input("Peso (g)", value=data["weight"], min_value=0, key="edit_w_woo")
        with ec3:
            edit_length_w = st.number_input("Largo (cm)", value=data["length"], min_value=0, key="edit_l_woo")
        with ec4:
            edit_width_w = st.number_input("Ancho (cm)", value=data["width"], min_value=0, key="edit_wi_woo")
        ec5, ec6 = st.columns(2)
        with ec5:
            edit_height_w = st.number_input("Alto (cm)", value=data["height"], min_value=0, key="edit_h_woo")
        with ec6:
            costo_w = buscar_costo_erp(edit_sku_w) if edit_sku_w else None
            edit_price_w = st.number_input("Costo c/IVA ($)", value=costo_w or data["price"], min_value=0.0, key="edit_p_woo")
            if costo_w:
                st.caption(f"✅ ERP: ${costo_w:,.2f}")
        edit_name_w = st.text_input("Nombre", value=data["name"], key="edit_name_woo")
        exists_w = zn_sku_exists(edit_sku_w) if edit_sku_w else False
        if exists_w:
            st.warning(f"⚠️ SKU `{edit_sku_w}` ya existe")
        if st.button("✅ Crear en Zipnova", key="btn_crear_woo", disabled=exists_w or not edit_sku_w, type="primary"):
            with st.spinner("Creando..."):
                ok, resp = crear_en_zipnova(edit_sku_w, edit_name_w, edit_weight_w, edit_length_w, edit_width_w, edit_height_w, edit_price_w)
            if ok:
                st.success(f"Creado (ID: {resp.get('id', '?')})")
                del st.session_state["woo_preview"]
            else:
                st.error(f"Error: {resp}")

# ─── TAB 3: MANUAL ──────────────────────────────────────────────────────────
with tab3:
    st.markdown("### Crear producto manualmente")
    mc1, mc2 = st.columns(2)
    with mc1:
        man_sku = st.text_input("SKU *", key="man_sku")
        man_name = st.text_input("Nombre *", key="man_name")
        costo_m = buscar_costo_erp(man_sku) if man_sku else None
        man_price = st.number_input("Costo c/IVA ($)", value=costo_m or 0.0, min_value=0.0, key="man_price")
        if costo_m:
            st.caption(f"✅ ERP: ${costo_m:,.2f}")
        elif man_sku:
            st.caption("⚠️ No en ERP")
    with mc2:
        man_weight = st.number_input("Peso (g) *", value=0, min_value=0, key="man_weight")
        man_length = st.number_input("Largo (cm) *", value=0, min_value=0, key="man_length")
        m3, m4 = st.columns(2)
        with m3:
            man_width = st.number_input("Ancho (cm) *", value=0, min_value=0, key="man_width")
        with m4:
            man_height = st.number_input("Alto (cm) *", value=0, min_value=0, key="man_height")

    if man_sku and man_weight > 0 and man_length > 0:
        pv = (man_length * man_width * man_height) / 4000
        st.info(f"Peso vol: {pv:.1f} kg | Real: {man_weight/1000:.1f} kg | **Zipnova usará: {max(pv, man_weight/1000):.1f} kg**")

    can = man_sku and man_name and man_weight > 0 and man_length > 0 and man_width > 0 and man_height > 0
    if man_sku:
        ex = zn_sku_exists(man_sku)
        if ex:
            st.warning(f"⚠️ SKU `{man_sku}` ya existe")
            can = False
    if st.button("✅ Crear en Zipnova", key="btn_crear_man", disabled=not can, type="primary"):
        with st.spinner("Creando..."):
            ok, resp = crear_en_zipnova(man_sku, man_name, man_weight, man_length, man_width, man_height, man_price)
        if ok:
            st.success(f"Creado (ID: {resp.get('id', '?')})")
        else:
            st.error(f"Error: {resp}")

# ─── TAB 4: VERIFICAR ───────────────────────────────────────────────────────
with tab4:
    st.markdown("### Verificar productos Zipnova vs ML")
    cuenta_v = st.selectbox("Cuenta", [c["nombre"] for c in CUENTAS_ML], key="v_cuenta")
    if st.button("🔍 Verificar", key="btn_verif"):
        cuenta = next(c for c in CUENTAS_ML if c["nombre"] == cuenta_v)
        token = refresh_ml_token(cuenta)
        if not token:
            st.error("Token ML no disponible")
        else:
            # --- Paso 1: Cargar todos los SKUs de Zipnova con paginación ---
            with st.spinner("Cargando inventario Zipnova..."):
                h_zn, acc = get_zn_auth()
                zn_skus = {}
                page = 1
                while True:
                    r = requests.get(f"{ZN_BASE}/inventory/search", headers=h_zn,
                                     params={"account_id": acc, "per_page": 100, "page": page}, timeout=15)
                    if r.status_code != 200:
                        break
                    data_zn = r.json()
                    for it in data_zn.get("data", []):
                        at = it.get("attributes", {})
                        zn_skus[it["sku"].upper()] = {
                            "w": int(at.get("weight", 0) or 0),
                            "l": int(at.get("length", 0) or 0),
                            "wi": int(at.get("width", 0) or 0),
                            "h": int(at.get("height", 0) or 0),
                        }
                    if page >= data_zn.get("meta", {}).get("last_page", 1):
                        break
                    page += 1
            st.info(f"📦 {len(zn_skus)} SKUs cargados de Zipnova")

            # --- Paso 2: Cargar todos los item IDs activos de ML ---
            with st.spinner("Cargando items activos de ML..."):
                ids = []
                off = 0
                while True:
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
            st.info(f"🛒 {len(ids)} items activos en ML ({cuenta_v}) — se filtrarán solo ME1/Zipnova")

            # --- Paso 3: Comparar cada item ML contra Zipnova ---
            rows = []
            ok_n, diff_n, no_zn, no_sku, filtered_n = 0, 0, 0, 0, 0
            prog = st.progress(0, text="Comparando items...")
            for i, iid in enumerate(ids):
                prog.progress((i + 1) / max(len(ids), 1), text=f"Procesando {i+1}/{len(ids)}...")
                ml, err = buscar_item_ml(iid, cuenta)
                if not ml:
                    no_sku += 1
                    continue
                # Filtrar solo items ME1 (Zipnova) — logistic_type == "default"
                if ml.get("logistic_type") != "default":
                    filtered_n += 1
                    continue
                if not ml["sku"]:
                    no_sku += 1
                    rows.append({
                        "MLA": iid, "SKU": "", "Producto": ml["name"][:50],
                        "Problema": "Sin SKU en ML",
                        "ML Peso(g)": ml["weight"], "ML Largo": ml["length"],
                        "ML Ancho": ml["width"], "ML Alto": ml["height"],
                        "ZN Peso(g)": "", "ZN Largo": "", "ZN Ancho": "", "ZN Alto": "",
                    })
                    continue
                su = ml["sku"].upper()
                if su not in zn_skus:
                    no_zn += 1
                    rows.append({
                        "MLA": iid, "SKU": ml["sku"], "Producto": ml["name"][:50],
                        "Problema": "No existe en Zipnova",
                        "ML Peso(g)": ml["weight"], "ML Largo": ml["length"],
                        "ML Ancho": ml["width"], "ML Alto": ml["height"],
                        "ZN Peso(g)": "", "ZN Largo": "", "ZN Ancho": "", "ZN Alto": "",
                    })
                    continue
                z = zn_skus[su]
                diffs = []
                if abs(ml["weight"] - z["w"]) > 50:
                    diffs.append("Peso")
                if abs(ml["length"] - z["l"]) > 2:
                    diffs.append("Largo")
                if abs(ml["width"] - z["wi"]) > 2:
                    diffs.append("Ancho")
                if abs(ml["height"] - z["h"]) > 2:
                    diffs.append("Alto")
                if diffs:
                    diff_n += 1
                    rows.append({
                        "MLA": iid, "SKU": ml["sku"], "Producto": ml["name"][:50],
                        "Problema": ", ".join(diffs),
                        "ML Peso(g)": ml["weight"], "ML Largo": ml["length"],
                        "ML Ancho": ml["width"], "ML Alto": ml["height"],
                        "ZN Peso(g)": z["w"], "ZN Largo": z["l"],
                        "ZN Ancho": z["wi"], "ZN Alto": z["h"],
                    })
                else:
                    ok_n += 1
                time.sleep(0.05)
            prog.empty()

            # --- Paso 4: Metricas resumen ---
            me1_total = ok_n + diff_n + no_zn + no_sku
            st.info(f"📦 {me1_total} items ME1 (Zipnova) de {len(ids)} activos en ML — {filtered_n} items no-ME1 filtrados")
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("✅ OK", ok_n)
            c2.metric("⚠️ Con diferencias", diff_n)
            c3.metric("❌ No en Zipnova", no_zn)
            c4.metric("🔹 Sin SKU en ML", no_sku)

            # --- Paso 5: Tabla detallada ---
            if rows:
                import pandas as pd
                df = pd.DataFrame(rows)
                st.dataframe(df, use_container_width=True, hide_index=True)
                st.download_button(
                    "📥 Descargar CSV",
                    df.to_csv(index=False).encode("utf-8"),
                    f"verificacion_{cuenta_v}.csv",
                    "text/csv",
                    key="btn_download_verif",
                )
            else:
                st.success("Todos los productos coinciden entre ML y Zipnova.")

# ─── TAB 5: CREAR ENVÍO ──────────────────────────────────────────────────────
with tab5:
    render_tab_envios(get_zn_auth, ZN_BASE)

# ─── TAB 6: VINCULAR ────────────────────────────────────────────────────────
with tab6:
    render_tab_vincular(get_zn_auth, ZN_BASE, buscar_item_ml, get_cuentas_ml, refresh_ml_token)

# ─── SIDEBAR ─────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### Zipnova Productos")
    st.caption("Guala Soluciones Decorativas")
    st.markdown("---")
    st.markdown(f"**Dólar CCL:** ${get_dolar_ccl():,.2f}")
    st.markdown("---")
    st.markdown("**Cuentas ML:**")
    for c in CUENTAS_ML:
        st.markdown(f"- {c['nombre']}")
    st.markdown("**WooCommerce:** gualasd.com.ar")
