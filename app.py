import streamlit as st
import requests
import pandas as pd
import os
import re
import json
import gspread
from google.oauth2.service_account import Credentials
from groq import Groq
import google.generativeai as genai  # NUEVO: Gemini SDK
from PIL import Image               # NUEVO: Para procesar imágenes
from datetime import datetime
import pytz
from dotenv import load_dotenv

# 1. CONFIGURACIÓN DEL SISTEMA
st.set_page_config(page_title="Hevy Coach AI", page_icon="⚡", layout="centered", initial_sidebar_state="collapsed")

load_dotenv()
API_KEY = os.getenv("HEVY_API_KEY")
ZONA_HORARIA = os.getenv("TIMEZONE", "America/Asuncion") 
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

# NUEVO: Configuración de Gemini para Visión
gemini_key = st.secrets.get("GEMINI_API_KEY")
model_gemini = None
if gemini_key:
    genai.configure(api_key=gemini_key)
    # Usamos Gemini 1.5 Flash por velocidad y costos bajos
    model_gemini = genai.GenerativeModel('gemini-3-flash-preview')

# Configuración de Groq para Texto
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
    # Buscamos solo las últimas 2 páginas para que cargue rápido
    for p in range(1, 3): 
        res = requests.get(url, headers=headers, params={"page": p, "pageSize": 10})
        if res.status_code == 200:
            datos = res.json()
            if "workouts" in datos: todos.extend(datos["workouts"])
    return {"workouts": todos} if todos else None

def detectar_semana_actual(datos_json):
    if not datos_json or "workouts" not in datos_json or len(datos_json["workouts"]) == 0: return 1
    for ej in datos_json["workouts"][0].get("exercises", []):
        match = re.search(r'[Ss]emana\s*(\d+)', ej.get("notes", ""))
        if match: return int(match.group(1))
    return 1

def procesar_datos(datos_json):
    if not datos_json or "workouts" not in datos_json: return pd.DataFrame(), pd.DataFrame()
    lista_r, lista_e = [], []
    for rutina in datos_json["workouts"]:
        f_c = rutina.get("start_time", "")
        n_rutina = rutina.get("title", "Sin Nombre")
        vol_r = 0
        for ej in rutina.get("exercises", []):
            nombre_ej = ej.get("title")
            for s in ej.get("sets", []):
                p, r = s.get("weight_kg") or 0, s.get("reps") or 0
                vol_r += (p * r)
                rm = p * (1 + (r / 30)) if r > 0 else 0
                lista_e.append({
                    "Fecha Cruda": f_c, "Rutina": n_rutina, "Ejercicio": nombre_ej, 
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

# 3. INTERFAZ Y LÓGICA
if not API_KEY:
    st.error("⚠️ Configura HEVY_API_KEY.")
else:
    datos_crudos = obtener_datos_hevy_auto()
    if datos_crudos:
        df_r, df_e = procesar_datos(datos_crudos)
        sem_auto = detectar_semana_actual(datos_crudos)
        
        st.title("⚡ Hevy Coach AI")

        # --- FILTRO EN CASCADA ---
        col_1, col_2 = st.columns([1, 1])
        with col_1:
            rutinas_unicas = df_e["Rutina"].unique()
            rutina_sel = st.selectbox("1. Día de Entrenamiento:", rutinas_unicas)
        with col_2:
            ejercicios_del_dia = df_e[df_e["Rutina"] == rutina_sel]["Ejercicio"].unique()
            ejercicio_sel = st.selectbox("2. Ejercicio Actual:", ejercicios_del_dia)

        semana_sel = st.slider("Fase del Ciclo:", 1, 8, value=sem_auto)

        # --- REGLAS LÓGICAS ---
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
        fase, desc = reglas[semana_sel]
        p_max = df_e[df_e["Ejercicio"] == ejercicio_sel]["Peso (Kg)"].max()

        # --- COACH IA AUTOMÁTICO (Groq) ---
        st.markdown(f"### 🧠 Coach: {ejercicio_sel}")
        if client_groq:
            @st.cache_data(ttl=60) 
            def analizar_con_ia(sem, fas, reg, ej, maximo):
                try:
                    prompt = f"Coach, Pablo (21 años) está en Semana {sem} ({fas}). Regla: {reg}. Ejercicio: {ej}. Récord: {maximo}kg. Da un consejo corto, táctico y motivador en español paraguayo."
                    chat = client_groq.chat.completions.create(
                        messages=[{"role": "user", "content": prompt}],
                        model="llama-3.3-70b-versatile",
                        temperature=0.7
                    )
                    return chat.choices[0].message.content
                except: return "Coach analizando..."
            
            st.info(analizar_con_ia(semana_sel, fase, desc, ejercicio_sel, p_max))
        
        st.write("---")

        # --- TABS DE DATOS ---
        # NUEVO: Orden lógico de Tabs (Fuerza -> Nutrición -> Agua -> Rendimiento)
        # Actualizá esta línea para tener 5 pestañas
        t1, t2, t3, t4, t5 = st.tabs(["📈 Fuerza", "🥗 Nutrición", "💪 Físico", "💧 Agua DB", "📊 Rendimiento"])
        
        with t1:
            st.subheader(f"Historial: {ejercicio_sel}")
            df_hist = df_e[df_e["Ejercicio"] == ejercicio_sel].sort_values("Fecha_Sort", ascending=False)
            st.dataframe(df_hist[["Fecha", "Peso (Kg)", "Reps", "1RM Est."]], use_container_width=True, hide_index=True)

        # NUEVO: Pestaña de Nutrición con Gemini
        # --- Pestaña de Nutrición con Cámara en Vivo ---
        with t2:
            st.subheader("📸 Análisis de Plato en Vivo")
            
            if model_gemini:
                # EL CAMBIO CLAVE: Activamos la cámara del celular/PC
                foto = st.camera_input("Sacale una foto a tu comida 🥗")
                
                if foto is not None:
                    # Abrimos la imagen de la cámara
                    imagen_pil = Image.open(foto)
                    
                    if st.button("🔮 Analizar Plato", type="primary"):
                        with st.spinner("Gemini analizando la foto..."):
                            try:
                                prompt = "Sos un nutricionista profesional paraguayo. Mirá esta foto e identificá la comida. Estimá las calorías totales y los macros (Proteína, Carbohidratos, Grasas en gramos). Sé breve."
                                respuesta = model_gemini.generate_content([prompt, imagen_pil])
                                st.write("---")
                                st.markdown("### ✍️ Análisis Nutricional")
                                st.write(respuesta.text)
                            except Exception as e:
                                st.error(f"Error al analizar con Gemini: {e}")
            else:
                st.error("⚠️ Configura GEMINI_API_KEY en los Secrets para usar esta función.")
       with t3:
            st.subheader("💪 Análisis de Postura y Simetría")
            
            if model_gemini:
                # PRO-TIP: Usamos key="cam_fisico" para que no choque con la cámara de comida
                foto_fisico = st.camera_input("Mostrá tu físico actual (Frontal o Espalda) 📸", key="cam_fisico")
                
                if foto_fisico is not None:
                    imagen_pil_fisico = Image.open(foto_fisico)
                    
                    if st.button("🔍 Evaluar Físico", type="primary"):
                        with st.spinner("El Coach IA está evaluando tu musculatura..."):
                            try:
                                # Prompt diseñado para biomecánica y estética
                                prompt_fisico = "Sos un entrenador experto en biomecánica y fisicoculturismo. Analizá esta foto del físico de tu cliente. Evaluá brevemente la simetría, postura corporal, nivel de definición general y áreas musculares que destacan. Usá un tono motivador en español paraguayo, directo y sin vueltas. (Nota: No des diagnósticos médicos, solo evaluación deportiva)."
                                respuesta_fisico = model_gemini.generate_content([prompt_fisico, imagen_pil_fisico])
                                st.write("---")
                                st.markdown("### 📋 Devolución de tu Coach")
                                st.write(respuesta_fisico.text)
                            except Exception as e:
                                st.error(f"Error en el análisis de Gemini: {e}")
            else:
                st.error("⚠️ Configura GEMINI_API_KEY en los Secrets.")
                
        with t4:
            st.subheader("💧 Registro de Hidratación")
            if sheet:
                tz = pytz.timezone(ZONA_HORARIA)
                hoy_str = datetime.now(tz).strftime('%Y-%m-%d')
                
                # Buscar celda hoy
                celda_hoy = sheet.find(hoy_str, in_column=1)
                
                # Si es un día nuevo, crear la fila automáticamente
                if celda_hoy is None:
                    sheet.append_row([hoy_str] + ["FALSE"] * 8)
                    celda_hoy = sheet.find(hoy_str, in_column=1)
                
                valores_db = sheet.row_values(celda_hoy.row)
                while len(valores_db) < 9: valores_db.append("FALSE")
                
                etiquetas = [
                    "04:30 AM - Sal + Café", "05:00 AM - 500ml Gym", 
                    "08:00 AM - 500ml Oficina", "12:00 PM - Almuerzo + Caminata", 
                    "13:30 PM - Tereré (Máximo 1L)", "17:00 PM - Cardio (500ml)", 
                    "19:00 PM - Universidad (500ml)", "22:00 PM - Shutdown"
                ]
                
                nuevos_valores = [hoy_str]
                hubo_cambios = False
                
                for i in range(8):
                    val_original = str(valores_db[i+1]).upper() == 'TRUE'
                    check = st.checkbox(etiquetas[i], value=val_original, key=f"h_{i}")
                    nuevos_valores.append(str(check).upper())
                    if check != val_original: hubo_cambios = True
                
                if hubo_cambios:
                    if st.button("💾 Guardar Cambios", type="primary", use_container_width=True):
                        rango = f"A{celda_hoy.row}:I{celda_hoy.row}"
                        sheet.update(range_name=rango, values=[nuevos_valores])
                        st.success("¡Base de Datos actualizada!")
                        st.rerun()
            else:
                st.info("Conectando con Google Sheets...")

        with t4:
            st.subheader("Volumen por Sesión")
            df_plot = df_r.sort_values("Fecha_Sort").tail(10)
            st.line_chart(df_plot.set_index("Fecha")["Volumen"])
