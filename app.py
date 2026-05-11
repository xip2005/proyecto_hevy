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

# --- AGREGACIÓN MENSUAL ---
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

# 3. INTERFAZ Y LÓGICA
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

        st.title("⚡ Hevy Coach AI")

        col_1, col_2 = st.columns(2)
        with col_1:
            # Agrupar por día (1er elemento antes del guión) y mostrar solo el último
            df_rutinas = df_e[["Rutina", "Fecha_Sort"]].drop_duplicates()
            df_rutinas["Grupo"] = df_rutinas["Rutina"].str.split("-").str[0]
            rutinas_por_dia = {}
            for grupo, sub in df_rutinas.groupby("Grupo"):
                ultima = sub.sort_values("Fecha_Sort", ascending=False).iloc[0]
                rutinas_por_dia[grupo] = ultima["Rutina"]
            opciones_dia = list(rutinas_por_dia.keys())
            dia_sel = st.selectbox("Día de Entrenamiento:", opciones_dia)
            rutina_sel = rutinas_por_dia[dia_sel]
        with col_2:
            ejercicios_del_dia = sorted(df_e[df_e["Rutina"] == rutina_sel]["Ejercicio"].dropna().unique())
            ejercicio_sel = st.selectbox("Ejercicio:", ejercicios_del_dia)

        semana_sel = st.slider("Fase del Ciclo:", 1, 8, value=sem_auto)
        fase, desc = reglas[semana_sel]
        st.caption(f"Semana {semana_sel} · {fase} · {desc}")

        # --- COACH IA ---
        p_max = df_e[df_e["Ejercicio"] == ejercicio_sel]["Peso (Kg)"].max()
        if client_groq:
            @st.cache_data(ttl=60)
            def analizar_con_ia(sem, fas, reg, ej, maximo):
                try:
                    prompt = f"Coach, Pablo (21 años) está en Semana {sem} ({fas}). Regla: {reg}. Ejercicio: {ej}. Récord: {maximo}kg. Da un consejo corto, táctico y motivador en español."
                    chat = client_groq.chat.completions.create(
                        messages=[{"role": "user", "content": prompt}],
                        model="llama-3.3-70b-versatile",
                        temperature=0.7
                    )
                    return chat.choices[0].message.content
                except:
                    return "Coach analizando..."
            st.info(analizar_con_ia(semana_sel, fase, desc, ejercicio_sel, p_max))

        st.divider()

        # --- COMENTARIOS DEL DÍA ---
        notas_dia = df_e[(df_e["Rutina"] == rutina_sel) & (df_e["Notas"].str.strip() != "")][["Ejercicio", "Notas"]].drop_duplicates()
        if not notas_dia.empty:
            st.subheader("📝 Comentarios del día")
            for _, row in notas_dia.iterrows():
                st.info(f"**{row['Ejercicio']}**: {row['Notas']}")
            st.divider()

        # --- COMPARACIÓN MES A MES ---
        cmp = comparar_mes(por_mes, ejercicio_sel)
        if cmp:
            st.subheader(f"📊 {cmp['mes_actual']} vs {cmp['mes_anterior']}")
            c1, c2 = st.columns(2)
            c1.metric("1RM Máx", f"{cmp['rm_max_act']:.1f} kg",
                      delta=f"{cmp['delta_rm']}%" if cmp.get('delta_rm') is not None else None)
            c2.metric("Peso Máx", f"{cmp['peso_max_act']:.1f} kg",
                      delta=f"{cmp['delta_peso']}%" if cmp.get('delta_peso') is not None else None)

        st.divider()

        # --- GRÁFICO 1RM MENSUAL ---
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

        st.divider()

        # --- 6 TABS ---
        t1, t2, t3, t4, t5, t6 = st.tabs(["📈 Fuerza", "🥗 Nutrición", "💪 Físico", "📹 Técnica", "💧 Agua DB", "📊 Rendimiento"])

        with t1:
            st.subheader(f"Historial: {ejercicio_sel}")
            df_hist = df_e[df_e["Ejercicio"] == ejercicio_sel].sort_values("Fecha_Sort", ascending=False)
            st.dataframe(df_hist[["Fecha", "Peso (Kg)", "Reps", "1RM Est."]], use_container_width=True, hide_index=True)

        with t2:
            st.subheader("📸 Análisis de Plato (Fotos Múltiples)")
            if model_gemini:
                opcion_nutri = st.radio("Método de carga:", ["📸 Usar Cámara", "📁 Subir de Galería"], horizontal=True, key="radio_nutri")
                fotos_nutri_lista = []
                if opcion_nutri == "📸 Usar Cámara":
                    foto_cam_nutri = st.camera_input("Sacale una foto a tu comida 🥗", key="cam_nutri")
                    if foto_cam_nutri:
                        fotos_nutri_lista.append(foto_cam_nutri)
                else:
                    fotos_gal_nutri = st.file_uploader("Subí tus fotos (JPG/PNG)", type=["jpg", "jpeg", "png"], key="file_nutri", accept_multiple_files=True)
                    if fotos_gal_nutri:
                        fotos_nutri_lista.extend(fotos_gal_nutri)
                if fotos_nutri_lista:
                    imagenes_pil = []
                    cols = st.columns(len(fotos_nutri_lista))
                    for idx, f in enumerate(fotos_nutri_lista):
                        img_pil = Image.open(f)
                        imagenes_pil.append(img_pil)
                        cols[idx].image(img_pil, use_container_width=True)
                    if st.button("🔮 Analizar Plato(s)", type="primary", key="btn_nutri"):
                        with st.spinner("Gemini analizando..."):
                            try:
                                prompt = "Sos un nutricionista profesional paraguayo. Mirá estas fotos e identificá la comida. Estimá las calorías totales conjuntas y los macros (Proteína, Carbohidratos, Grasas en gramos). Sé breve."
                                contenido = [prompt] + imagenes_pil
                                respuesta = model_gemini.generate_content(contenido)
                                st.write("---")
                                st.markdown("### ✍️ Análisis Nutricional")
                                st.write(respuesta.text)
                            except Exception as e:
                                st.error(f"Error al analizar con Gemini: {e}")
            else:
                st.error("⚠️ Configura GEMINI_API_KEY en los Secrets.")

        with t3:
            st.subheader("💪 Análisis de Postura (Fotos Múltiples)")
            if model_gemini:
                opcion_fisico = st.radio("Método de carga:", ["📸 Usar Cámara", "📁 Subir de Galería"], horizontal=True, key="radio_fisico")
                fotos_fisico_lista = []
                if opcion_fisico == "📸 Usar Cámara":
                    foto_cam_fisico = st.camera_input("Mostrá tu físico 📸", key="cam_fisico")
                    if foto_cam_fisico:
                        fotos_fisico_lista.append(foto_cam_fisico)
                else:
                    fotos_gal_fisico = st.file_uploader("Subí tus fotos (Frente/Espalda)", type=["jpg", "jpeg", "png"], key="file_fisico", accept_multiple_files=True)
                    if fotos_gal_fisico:
                        fotos_fisico_lista.extend(fotos_gal_fisico)
                if fotos_fisico_lista:
                    imagenes_pil_f = []
                    cols_f = st.columns(len(fotos_fisico_lista))
                    for idx, f in enumerate(fotos_fisico_lista):
                        img_pil = Image.open(f)
                        imagenes_pil_f.append(img_pil)
                        cols_f[idx].image(img_pil, use_container_width=True)
                    if st.button("🔍 Evaluar Físico", type="primary", key="btn_fisico"):
                        with st.spinner("El Coach IA está evaluando..."):
                            try:
                                prompt_fisico = "Sos un entrenador experto en biomecánica. Analizá estas fotos. Evaluá brevemente la simetría, postura, y definición general. Usá un tono motivador en español, directo y sin vueltas."
                                contenido_f = [prompt_fisico] + imagenes_pil_f
                                respuesta_fisico = model_gemini.generate_content(contenido_f)
                                st.write("---")
                                st.markdown("### 📋 Devolución de tu Coach")
                                st.write(respuesta_fisico.text)
                            except Exception as e:
                                st.error(f"Error en el análisis de Gemini: {e}")
            else:
                st.error("⚠️ Configura GEMINI_API_KEY en los Secrets.")

        with t4:
            st.subheader(f"📹 Evaluar Técnica: {ejercicio_sel}")
            st.info("Subí un video corto (máximo 15-20 segundos) para que la IA evalúe tu postura y rango de movimiento.")
            if model_gemini:
                video_file = st.file_uploader("Subí tu video de entrenamiento (MP4)", type=["mp4", "mov"], key="vid_tec")
                if video_file is not None:
                    st.video(video_file)
                    if st.button("🚀 Analizar Técnica en Video", type="primary", use_container_width=True):
                        with st.spinner("Subiendo video a la nube de Google..."):
                            try:
                                temp_path = "temp_video.mp4"
                                with open(temp_path, "wb") as f:
                                    f.write(video_file.getbuffer())
                                video_gemini = genai.upload_file(path=temp_path)
                                st.info("Video subido. Esperando que Google procese los fotogramas...")
                                while video_gemini.state.name == "PROCESSING":
                                    time.sleep(3)
                                    video_gemini = genai.get_file(video_gemini.name)
                                if video_gemini.state.name == "FAILED":
                                    st.error("Error al procesar el video en los servidores de Google.")
                                else:
                                    prompt_tec = f"Sos un entrenador de Powerlifting/Culturismo. Analizá mi técnica en el ejercicio: {ejercicio_sel}. Decime si el rango de movimiento es correcto, si ves fallos en la postura (ej: espalda encorvada, rodillas colapsadas) y cómo puedo mejorarlo. Sé conciso y directo."
                                    respuesta_tec = model_gemini.generate_content([prompt_tec, video_gemini])
                                    st.write("---")
                                    st.markdown("### 🎯 Corrección Técnica")
                                    st.write(respuesta_tec.text)
                                    genai.delete_file(video_gemini.name)
                                    os.remove(temp_path)
                            except Exception as e:
                                st.error(f"Error al analizar el video: {e}")
            else:
                st.error("⚠️ Configura GEMINI_API_KEY en los Secrets.")

        with t5:
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

        with t6:
            st.subheader("Volumen por Sesión")
            df_plot = df_r.sort_values("Fecha_Sort").tail(10)
            st.line_chart(df_plot.set_index("Fecha")["Volumen"])

