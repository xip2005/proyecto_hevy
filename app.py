import streamlit as st
import requests
import pandas as pd
import os
import re
import json
import gspread
from google.oauth2.service_account import Credentials
from groq import Groq
import google.generativeai as genai
from PIL import Image
from datetime import datetime
import pytz
from dotenv import load_dotenv
import time

# 1. CONFIGURACIÓN DEL SISTEMA
st.set_page_config(page_title="Hevy Coach AI", page_icon="⚡", layout="centered", initial_sidebar_state="collapsed")

load_dotenv()
API_KEY = os.getenv("HEVY_API_KEY")
ZONA_HORARIA = os.getenv("TIMEZONE", "America/Asuncion")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

gemini_key = st.secrets.get("GEMINI_API_KEY")
model_gemini = None
if gemini_key:
    genai.configure(api_key=gemini_key)
    model_gemini = genai.GenerativeModel('gemini-3-flash-preview')

client_groq = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

# --- CONEXIÓN A BASE DE DATOS (Google Sheets) ---
@st.cache_resource
def conectar_db():
    try:
        scope = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
        creds_dict = json.loads(st.secrets["GOOGLE_JSON"])
        creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
        client_gs = gspread.authorize(creds)
        return client_gs.open("Hevy_DB").sheet1
    except:
        return None

sheet = conectar_db()

# 2. MOTOR DE DATOS (Hevy)
@st.cache_data(ttl=300)
def obtener_datos_hevy_auto():
    url = "https://api.hevyapp.com/v1/workouts"
    headers = {"api-key": API_KEY, "Accept": "application/json"}
    todos = []
    for p in range(1, 7):
        res = requests.get(url, headers=headers, params={"page": p, "pageSize": 10})
        if res.status_code == 200:
            datos = res.json()
            if "workouts" in datos:
                todos.extend(datos["workouts"])
    return {"workouts": todos} if todos else None

def detectar_semana_actual(datos_json):
    if not datos_json or "workouts" not in datos_json or len(datos_json["workouts"]) == 0:
        return 1
    for ej in datos_json["workouts"][0].get("exercises", []):
        match = re.search(r'[Ss]emana\s*(\d+)', ej.get("notes", ""))
        if match:
            return int(match.group(1))
    return 1

def procesar_datos(datos_json):
    if not datos_json or "workouts" not in datos_json:
        return pd.DataFrame(), pd.DataFrame()
    lista_r, lista_e = [], []
    for rutina in datos_json["workouts"]:
        f_c = rutina.get("start_time", "")
        n_rutina = rutina.get("title", "Sin Nombre")
        vol_r = 0
        for ej in rutina.get("exercises", []):
            nombre_ej = ej.get("title")
            nota_ej = ej.get("notes", "")
            for s in ej.get("sets", []):
                p, r = s.get("weight_kg") or 0, s.get("reps") or 0
                vol_r += (p * r)
                rm = p * (1 + (r / 30)) if r > 0 else 0
                lista_e.append({
                    "Fecha Cruda": f_c, "Rutina": n_rutina, "Ejercicio": nombre_ej,
                    "Notas": nota_ej,
                    "Peso (Kg)": p, "Reps": r, "1RM Est.": round(rm, 1)
                })
        lista_r.append({"Fecha Cruda": f_c, "Rutina": n_rutina, "Volumen": vol_r})
    df_r, df_e = pd.DataFrame(lista_r), pd.DataFrame(lista_e)
    for df in [df_r, df_e]:
        if not df.empty:
            f_dt = pd.to_datetime(df["Fecha Cruda"], utc=True).dt.tz_convert(ZONA_HORARIA)
            df["Fecha"] = f_dt.dt.strftime('%d/%m/%Y')
            df["Fecha_Sort"] = f_dt
    return df_r, df_e

# 3. AGREGACIÓN MENSUAL
def agrupar_por_mes(df_e, df_r):
    if df_e.empty:
        return {}
    df_e = df_e.copy()
    df_r = df_r.copy()
    try:
        tz = pytz.timezone(ZONA_HORARIA)
    except:
        tz = pytz.UTC
    df_e["Mes"] = pd.to_datetime(df_e["Fecha Cruda"], utc=True).dt.tz_convert(tz).dt.to_period("M").astype(str)
    df_r["Mes"] = pd.to_datetime(df_r["Fecha Cruda"], utc=True).dt.tz_convert(tz).dt.to_period("M").astype(str)
    meses = sorted(df_e["Mes"].unique())
    resultado = {}
    for mes in meses:
        mask_r = df_r["Mes"] == mes
        mask_e = df_e["Mes"] == mes
        ejercicios_mes = {}
        for ej in df_e.loc[mask_e, "Ejercicio"].unique():
            mask_ej = mask_e & (df_e["Ejercicio"] == ej)
            df_ej = df_e.loc[mask_ej]
            ejercicios_mes[ej] = {
                "peso_max": df_ej["Peso (Kg)"].max(),
                "rm_max": df_ej["1RM Est."].max(),
            }
        resultado[mes] = {
            "volumen_total": df_r.loc[mask_r, "Volumen"].sum(),
            "ejercicios": ejercicios_mes,
        }
    return resultado

def comparar_mes(por_mes, ejercicio_sel):
    if not por_mes:
        return None
    meses = sorted(por_mes.keys())
    if len(meses) < 2:
        return None
    actual_mes = meses[-1]
    anterior_mes = meses[-2]
    datos_act = por_mes[actual_mes]["ejercicios"].get(ejercicio_sel)
    datos_ant = por_mes[anterior_mes]["ejercicios"].get(ejercicio_sel)
    if not datos_act or not datos_ant:
        return None
    def _delta(act, ant):
        if ant == 0:
            return None
        return round(((act - ant) / ant) * 100, 1)
    return {
        "mes_actual": actual_mes,
        "mes_anterior": anterior_mes,
        "peso_max_act": datos_act["peso_max"],
        "peso_max_ant": datos_ant["peso_max"],
        "rm_max_act": datos_act["rm_max"],
        "rm_max_ant": datos_ant["rm_max"],
        "delta_peso": _delta(datos_act["peso_max"], datos_ant["peso_max"]),
        "delta_rm": _delta(datos_act["rm_max"], datos_ant["rm_max"]),
    }

# 4. INTERFAZ
if not API_KEY:
    st.error("⚠️ Configura HEVY_API_KEY en el archivo .env")
else:
    with st.spinner("Cargando datos de Hevy..."):
        try:
            datos_crudos = obtener_datos_hevy_auto()
        except Exception as e:
            st.error(f"❌ Error al conectar con Hevy: {e}")
            datos_crudos = None

    if not datos_crudos:
        st.warning("⚠️ No se pudieron cargar los entrenamientos. Verificá tu conexión a internet.")
    else:
        df_r, df_e = procesar_datos(datos_crudos)
        sem_auto = detectar_semana_actual(datos_crudos)
        por_mes = agrupar_por_mes(df_e, df_r)

        reglas = {
            1: ("Calibración", "NO llegues al fallo. Peso base."),
            2: ("Sobrecarga", "Sube peso o haz +1 repetición."),
            3: ("Fuerza Pura", "Peso máximo para 10-12 reps."),
            4: ("Tortura Mecánica", "MISMO PESO Sem 3. Pausa 2 seg abajo."),
            5: ("Reinicio", "Pesos de Semana 2. Técnica limpia."),
            6: ("Nuevo Pico", "Superar récord de Semana 3."),
            7: ("Prueba Final", "Pesos récord con bajada de 4s."),
            8: ("Descarga", "Baja todo al 50%. 1 serie menos.")
        }

        # ── HEADER ──
        st.title("⚡ Hevy Coach AI")
        semana_sel = st.slider("Fase del Ciclo:", 1, 8, value=sem_auto)
        fase, desc = reglas[semana_sel]
        st.caption(f"Semana {semana_sel} · {fase} · {desc}")

        st.divider()

        # ── SELECTORES: DÍA → EJERCICIO ──
        c1, c2 = st.columns(2)
        with c1:
            df_rutinas = df_e[["Rutina", "Fecha_Sort"]].drop_duplicates()
            df_rutinas["Grupo"] = df_rutinas["Rutina"].str.split("-").str[0]
            rutinas_por_dia = {}
            for grupo, sub in df_rutinas.groupby("Grupo"):
                ultima = sub.sort_values("Fecha_Sort", ascending=False).iloc[0]
                rutinas_por_dia[grupo] = ultima["Rutina"]
            dia_sel = st.selectbox("Día:", list(rutinas_por_dia.keys()))
            rutina_sel = rutinas_por_dia[dia_sel]
        with c2:
            ejercicios_del_dia = sorted(df_e[df_e["Rutina"] == rutina_sel]["Ejercicio"].dropna().unique())
            ejercicio_sel = st.selectbox("Ejercicio:", ejercicios_del_dia)

        # ── COMPARACIÓN MES A MES ──
        cmp = comparar_mes(por_mes, ejercicio_sel)

        # ── COACH IA ──
        st.subheader("🧠 Coach")
        p_max = df_e[df_e["Ejercicio"] == ejercicio_sel]["Peso (Kg)"].max()
        if client_groq:
            @st.cache_data(ttl=60)
            def analizar_con_ia(sem, fas, reg, ej, maximo, comparacion):
                base = f"Coach, Pablo (21 años) | Semana {sem} ({fas}) | Ejercicio: {ej} | Récord: {maximo}kg | Regla: {reg}."
                if comparacion:
                    base += f" | vs mes anterior: 1RM {comparacion['rm_max_ant']:.1f}→{comparacion['rm_max_act']:.1f}kg ({comparacion['delta_rm']}%), Peso {comparacion['peso_max_ant']:.1f}→{comparacion['peso_max_act']:.1f}kg ({comparacion['delta_peso']}%)."
                base += " Da un consejo corto, táctico y motivador en español. Máximo 3 frases."
                try:
                    chat = client_groq.chat.completions.create(
                        messages=[{"role": "user", "content": base}],
                        model="llama-3.3-70b-versatile",
                        temperature=0.7
                    )
                    return chat.choices[0].message.content
                except:
                    return "Coach analizando..."
            st.info(analizar_con_ia(semana_sel, fase, desc, ejercicio_sel, p_max, cmp))
        else:
            st.info("⚙️ Configurá GROQ_API_KEY en .env para activar el coach IA.")

        # ── KPIs MES A MES ──
        if cmp:
            st.divider()
            st.subheader(f"📊 {cmp['mes_actual']} vs {cmp['mes_anterior']}")
            k1, k2 = st.columns(2)
            k1.metric("1RM Máx", f"{cmp['rm_max_act']:.1f} kg",
                       delta=f"{cmp['delta_rm']}%" if cmp.get('delta_rm') is not None else None)
            k2.metric("Peso Máx", f"{cmp['peso_max_act']:.1f} kg",
                       delta=f"{cmp['delta_peso']}%" if cmp.get('delta_peso') is not None else None)

        # ── GRÁFICO 1RM MENSUAL ──
        st.divider()
        st.subheader(f"📈 1RM Mensual: {ejercicio_sel}")
        meses_ordenados = sorted(por_mes.keys())
        rm_data = []
        for m in meses_ordenados:
            ej_data = por_mes[m]["ejercicios"].get(ejercicio_sel)
            if ej_data:
                rm_data.append({"Mes": m, "1RM Est.": ej_data["rm_max"]})
        if rm_data:
            df_grafico = pd.DataFrame(rm_data).set_index("Mes")
            st.area_chart(df_grafico, use_container_width=True)

        # ── COMENTARIOS DEL DÍA ──
        notas_dia = df_e[(df_e["Rutina"] == rutina_sel) & (df_e["Notas"].str.strip() != "")][["Ejercicio", "Notas"]].drop_duplicates()
        if not notas_dia.empty:
            st.divider()
            st.subheader("📝 Comentarios del día")
            for _, row in notas_dia.iterrows():
                st.info(f"**{row['Ejercicio']}**: {row['Notas']}")

        st.divider()

        # ── 6 SECCIONES (2×3) ──
        if "tab" not in st.session_state:
            st.session_state.tab = "Fuerza"

        secciones = ["Fuerza", "Nutrición", "Físico", "Técnica", "Agua", "Rendimiento"]
        iconos = ["📈", "🥗", "💪", "📹", "💧", "📊"]

        r1c1, r1c2, r1c3 = st.columns(3)
        r2c1, r2c2, r2c3 = st.columns(3)
        fila1 = [r1c1, r1c2, r1c3]
        fila2 = [r2c1, r2c2, r2c3]

        for i, (sec, ico) in enumerate(zip(secciones, iconos)):
            col = fila1[i] if i < 3 else fila2[i - 3]
            tipo = "primary" if st.session_state.tab == sec else "secondary"
            if col.button(f"{ico} {sec}", key=f"tab_{sec}", use_container_width=True, type=tipo):
                st.session_state.tab = sec
                st.rerun()

        st.divider()

        tab = st.session_state.tab

        # ── CONTENIDO DE CADA SECCIÓN ──
        if tab == "Fuerza":
            st.subheader(f"Historial: {ejercicio_sel}")
            df_hist = df_e[df_e["Ejercicio"] == ejercicio_sel].sort_values("Fecha_Sort", ascending=False)
            st.dataframe(df_hist[["Fecha", "Peso (Kg)", "Reps", "1RM Est."]], use_container_width=True, hide_index=True)

        elif tab == "Nutrición":
            st.subheader("📸 Análisis de Plato")
            if model_gemini:
                opcion = st.radio("Método:", ["📸 Cámara", "📁 Galería"], horizontal=True, key="nutri_radio")
                fotos = []
                if opcion == "📸 Cámara":
                    f = st.camera_input("Foto de tu comida", key="cam_nutri")
                    if f: fotos.append(f)
                else:
                    f = st.file_uploader("Subí fotos", type=["jpg", "jpeg", "png"], key="file_nutri", accept_multiple_files=True)
                    if f: fotos.extend(f)
                if fotos:
                    imgs = []
                    cols = st.columns(len(fotos))
                    for idx, fi in enumerate(fotos):
                        img = Image.open(fi)
                        imgs.append(img)
                        cols[idx].image(img, use_container_width=True)
                    if st.button("🔮 Analizar", type="primary", key="btn_nutri"):
                        with st.spinner("Analizando..."):
                            try:
                                prompt = "Sos un nutricionista paraguayo. Identificá la comida, estimá calorías totales y macros (Proteína, Carbs, Grasas en g). Sé breve."
                                resp = model_gemini.generate_content([prompt] + imgs)
                                st.markdown("### ✍️ Análisis")
                                st.write(resp.text)
                            except Exception as e:
                                st.error(f"Error: {e}")
            else:
                st.error("⚠️ Configura GEMINI_API_KEY en Secrets.")

        elif tab == "Físico":
            st.subheader("💪 Análisis de Postura")
            if model_gemini:
                opcion = st.radio("Método:", ["📸 Cámara", "📁 Galería"], horizontal=True, key="fisico_radio")
                fotos = []
                if opcion == "📸 Cámara":
                    f = st.camera_input("Foto de tu físico", key="cam_fisico")
                    if f: fotos.append(f)
                else:
                    f = st.file_uploader("Subí fotos", type=["jpg", "jpeg", "png"], key="file_fisico", accept_multiple_files=True)
                    if f: fotos.extend(f)
                if fotos:
                    imgs = []
                    cols = st.columns(len(fotos))
                    for idx, fi in enumerate(fotos):
                        img = Image.open(fi)
                        imgs.append(img)
                        cols[idx].image(img, use_container_width=True)
                    if st.button("🔍 Evaluar", type="primary", key="btn_fisico"):
                        with st.spinner("Evaluando..."):
                            try:
                                prompt = "Sos un entrenador experto en biomecánica. Analizá estas fotos. Evaluá brevemente simetría, postura y definición. Tono motivador, directo."
                                resp = model_gemini.generate_content([prompt] + imgs)
                                st.markdown("### 📋 Devolución")
                                st.write(resp.text)
                            except Exception as e:
                                st.error(f"Error: {e}")
            else:
                st.error("⚠️ Configura GEMINI_API_KEY en Secrets.")

        elif tab == "Técnica":
            st.subheader(f"📹 Evaluar Técnica: {ejercicio_sel}")
            st.info("Subí un video corto (15-20s) para evaluar postura y rango de movimiento.")
            if model_gemini:
                video_file = st.file_uploader("Subí tu video (MP4)", type=["mp4", "mov"], key="vid_tec")
                if video_file:
                    st.video(video_file)
                    if st.button("🚀 Analizar Técnica", type="primary", use_container_width=True):
                        with st.spinner("Procesando video..."):
                            try:
                                temp_path = "temp_video.mp4"
                                with open(temp_path, "wb") as f:
                                    f.write(video_file.getbuffer())
                                video_gemini = genai.upload_file(path=temp_path)
                                while video_gemini.state.name == "PROCESSING":
                                    time.sleep(3)
                                    video_gemini = genai.get_file(video_gemini.name)
                                if video_gemini.state.name == "FAILED":
                                    st.error("Error al procesar el video.")
                                else:
                                    prompt = f"Entrenador de Powerlifting/Culturismo. Analizá mi técnica en {ejercicio_sel}. Evaluá rango de movimiento, postura, y cómo mejorar. Conciso y directo."
                                    resp = model_gemini.generate_content([prompt, video_gemini])
                                    st.markdown("### 🎯 Corrección Técnica")
                                    st.write(resp.text)
                                    genai.delete_file(video_gemini.name)
                                    os.remove(temp_path)
                            except Exception as e:
                                st.error(f"Error: {e}")
            else:
                st.error("⚠️ Configura GEMINI_API_KEY en Secrets.")

        elif tab == "Agua":
            st.subheader("💧 Registro de Hidratación")
            if sheet:
                tz = pytz.timezone(ZONA_HORARIA)
                hoy_str = datetime.now(tz).strftime('%Y-%m-%d')
                celda_hoy = sheet.find(hoy_str, in_column=1)
                if celda_hoy is None:
                    sheet.append_row([hoy_str] + ["FALSE"] * 8)
                    celda_hoy = sheet.find(hoy_str, in_column=1)
                valores_db = sheet.row_values(celda_hoy.row)
                while len(valores_db) < 9:
                    valores_db.append("FALSE")
                etiquetas = [
                    "04:30 AM - Sal + Café:500ML", "05:00 AM - 500ml Gym",
                    "08:00 AM - 500ml Oficina", "12:00 PM - Almuerzo + 250ML",
                    "13:30 PM - Tereré (Máximo 1L)", "17:00 PM - Cardio (500ml)",
                    "19:00 PM - Universidad (500ml)", "22:00 PM - No más agua"
                ]
                nuevos_valores = [hoy_str]
                hubo_cambios = False
                for i in range(8):
                    val_original = str(valores_db[i+1]).upper() == 'TRUE'
                    check = st.checkbox(etiquetas[i], value=val_original, key=f"h_{i}")
                    nuevos_valores.append(str(check).upper())
                    if check != val_original:
                        hubo_cambios = True
                if hubo_cambios:
                    if st.button("💾 Guardar Cambios", type="primary", use_container_width=True):
                        rango = f"A{celda_hoy.row}:I{celda_hoy.row}"
                        sheet.update(range_name=rango, values=[nuevos_valores])
                        st.success("¡Base de Datos actualizada!")
                        st.rerun()
            else:
                st.info("Conectando con Google Sheets...")

        elif tab == "Rendimiento":
            st.subheader("Volumen por Sesión")
            df_plot = df_r.sort_values("Fecha_Sort").tail(10)
            st.line_chart(df_plot.set_index("Fecha")["Volumen"])
