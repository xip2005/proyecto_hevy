import streamlit as st
import requests
import pandas as pd
import os
import re
import google.generativeai as genai
from dotenv import load_dotenv

# 1. CONFIGURACIÓN DEL SISTEMA
st.set_page_config(page_title="Hevy Coach AI", page_icon="⚡", layout="centered", initial_sidebar_state="collapsed")

load_dotenv()
API_KEY = os.getenv("HEVY_API_KEY")
ZONA_HORARIA = os.getenv("TIMEZONE", "America/Asuncion") 
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

# 2. MOTOR DE DATOS (Sincronización Automática con Caché)
@st.cache_data(ttl=300) 
def obtener_datos_hevy_auto():
    url = "https://api.hevyapp.com/v1/workouts"
    headers = {"api-key": API_KEY, "Accept": "application/json"}
    todos_los_workouts = []
    for pagina in range(1, 4): 
        params = {"page": pagina, "pageSize": 10} 
        response = requests.get(url, headers=headers, params=params)
        if response.status_code == 200:
            datos_p = response.json()
            if "workouts" in datos_p: todos_los_workouts.extend(datos_p["workouts"])
    return {"workouts": todos_los_workouts} if todos_los_workouts else None

def detectar_semana_actual(datos_json):
    """Busca 'Semana X' en las notas para automatizar la fase del ciclo."""
    if not datos_json or "workouts" not in datos_json or len(datos_json["workouts"]) == 0: return 1
    for ej in datos_json["workouts"][0].get("exercises", []):
        match = re.search(r'[Ss]emana\s*(\d+)', ej.get("notes", ""))
        if match: return int(match.group(1))
    return 1

def procesar_datos(datos_json):
    if not datos_json or "workouts" not in datos_json: return pd.DataFrame(), pd.DataFrame()
    lista_r, lista_e = [], []
    meses_es = {1: "Ene", 2: "Feb", 3: "Mar", 4: "Abr", 5: "May", 6: "Jun", 7: "Jul", 8: "Ago", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dic"}
    
    for rutina in datos_json["workouts"]:
        vol_rutina = 0
        f_c = rutina.get("start_time", "")
        for ej in rutina.get("exercises", []):
            for s in ej.get("sets", []):
                p, r = s.get("weight_kg") or 0, s.get("reps") or 0
                vol_rutina += (p * r)
                # Fórmula de Epley para 1RM Estimado
                rm = p * (1 + (r / 30)) if r > 0 else 0
                lista_e.append({
                    "Fecha Cruda": f_c, "Ejercicio": ej.get("title"), "Peso": p, "Reps": r, "1RM": round(rm, 1)
                })
        lista_r.append({"Fecha Cruda": f_c, "Rutina": rutina.get("title"), "Volumen": vol_rutina})
    
    df_r, df_e = pd.DataFrame(lista_r), pd.DataFrame(lista_e)
    if not df_r.empty:
        f_ajustada = pd.to_datetime(df_r["Fecha Cruda"], utc=True).dt.tz_convert(ZONA_HORARIA)
        df_r["Fecha Visual"] = f_ajustada.apply(lambda x: f"{x.day} {meses_es[x.month]}")
        df_r["Fecha Orden"] = f_ajustada
    return df_r, df_e

# 3. INTERFAZ PROFESIONAL
if not API_KEY:
    st.error("⚠️ Configura la HEVY_API_KEY en Secrets.")
else:
    with st.spinner("Sincronizando con Hevy..."):
        crudo = obtener_datos_hevy_auto()
    
    if crudo:
        df_r, df_e = procesar_datos(crudo)
        sem_auto = detectar_semana_actual(crudo)
        
        st.title("⚡ Hevy Coach AI")
        
        # Pestañas Principales
        t1, t2, t3, t4 = st.tabs(["📊 Rendimiento", "📈 Fuerza", "🧠 Coach AI", "💧 Agua"])
        
        with t1:
            st.subheader("Tonelaje por Sesión")
            df_plot_r = df_r.sort_values("Fecha Orden").tail(10)
            st.line_chart(df_plot_r.set_index("Fecha Visual")["Volumen"])
            
            st.subheader("Análisis de Masa Muscular")
            # Motor de Alertas Críticas
            rutinas_recientes = df_r.head(8)
            for tipo in ["Push", "Pull", "Torso", "Leg"]:
                filtro = rutinas_recientes[rutinas_recientes["Rutina"].str.contains(tipo, case=False, na=False)]
                if len(filtro) >= 2:
                    v_act, v_ant = filtro.iloc[0]["Volumen"], filtro.iloc[1]["Volumen"]
                    if v_act < v_ant:
                        st.error(f"🚨 **{tipo.upper()}**: Bajaste {v_ant - v_act:.0f}kg. ¡Ojo con el músculo!")
                    else:
                        st.success(f"✅ **{tipo.upper()}**: Estímulo mantenido ({v_act:.0f}kg).")

        with t2:
            st.subheader("Progreso de Fuerza (1RM)")
            ej_sel = st.selectbox("Seleccionar Ejercicio:", df_e["Ejercicio"].unique(), key="fuerza_sel")
            df_f = df_e[(df_e["Ejercicio"] == ej_sel) & (df_e["Peso"] > 0)].sort_values("Fecha Cruda")
            if not df_f.empty:
                df_f_g = df_f.groupby("Fecha Cruda")["1RM"].max()
                st.line_chart(df_f_g)
            else:
                st.info("No hay datos de peso para graficar este ejercicio.")

        with t3:
            st.subheader("Sistema de Hipertrofia 8 Semanas")
            sem = st.slider("Fase del Ciclo:", 1, 8, value=sem_auto, key="sem_slider")
            
            # Reglas lógicas del manual de usuario 
            reglas = {
                1: {"f": "Calibración", "t": "3-1", "r": "RIR 2", "d": "Encontrar peso base. NO fallar."},
                2: {"f": "Sobrecarga", "t": "3-1", "r": "RIR 1-2", "d": "Subir peso o +1 repetición."},
                3: {"f": "Fuerza Pura", "t": "Normal", "r": "RIR 1", "d": "Peso máximo para 10-12 reps."},
                4: {"f": "Tortura Mecánica", "t": "4-2", "r": "Fallo", "d": "MISMO PESO Sem 3. Pausa 2s abajo."},
                5: {"f": "Reinicio", "t": "3-1", "r": "RIR 2", "d": "Usa pesos de la Semana 2."},
                6: {"f": "Nuevo Pico", "t": "Normal", "r": "RIR 0", "d": "Superar récord de Semana 3."},
                7: {"f": "Prueba Final", "t": "4-2", "r": "Fallo", "d": "Pesos récord con bajada de 4s."},
                8: {"f": "Descarga", "t": "Normal", "r": "Fácil", "d": "PESOS AL 50%. -1 serie por ejercicio."}
            }
            
            st.info(f"🎯 **Fase:** {reglas[sem]['f']} | ⏱️ **Tempo:** {reglas[sem]['t']}\n\n📖 **Instrucción:** {reglas[sem]['d']}")
            
            ej_ai = st.selectbox("Ejercicio para el Coach:", df_e["Ejercicio"].unique(), key="ai_sel")
            df_ai = df_e[df_e["Ejercicio"] == ej_ai]
            p_max = df_ai["Peso"].max() if not df_ai.empty else 0
            p_ult = df_ai.iloc[0]["Peso"] if not df_ai.empty else 0
            
            if st.button("🧠 Consultar Coach IA", use_container_width=True):
                if not GEMINI_API_KEY: st.error("Falta GEMINI_API_KEY")
                else:
                    with st.spinner("Analizando biomecánica..."):
                        try:
                            model = genai.GenerativeModel('gemini-1.5-flash-latest')
                            prompt = f"""Instrucción: Hablá en español. Sos un coach experto. 
                            Cliente: Pablo. Objetivo: Definición extrema reteniendo músculo.
                            Semana actual: {sem} ({reglas[sem]['f']}). 
                            Regla: {reglas[sem]['d']}. Tempo: {reglas[sem]['t']}.
                            Ejercicio: {ej_ai}. Récord: {p_max}kg. Último peso: {p_ult}kg.
                            Dale un consejo táctico y motivador de 2 párrafos sobre cómo encarar este ejercicio hoy."""
                            res = model.generate_content(prompt)
                            st.write(res.text)
                        except Exception as e: st.error(f"Error IA: {e}")

        with t4:
            st.subheader("💧 Protocolo de Hidratación") # 
            st.checkbox("04:30 AM - Escudo Sal + Café", key="h1") # [cite: 76, 77]
            st.checkbox("05:00 AM - 500ml Gym (Sorbos)", key="h2") # [cite: 79, 81]
            st.checkbox("08:00 AM - 12PM - 500ml Oficina", key="h3") # [cite: 83, 84]
            st.checkbox("12:00 PM - Almuerzo (250ml) + Caminata", key="h4") # [cite: 87, 88, 90]
            st.checkbox("13:30 PM - Tereré (Máximo 1 Litro)", key="h5") # [cite: 91, 93, 95]
            st.checkbox("17:00 PM - Cardio Intenso (500ml)", key="h6") # [cite: 97, 98]
            st.checkbox("19:00 PM - Universidad (500ml)", key="h7") # [cite: 100, 101]
            st.checkbox("22:00 PM - Shutdown (Cero líquidos)", key="h8") # [cite: 104, 105]

    else:
        st.error("No se pudo conectar con Hevy. Revisá tu API Key.")
