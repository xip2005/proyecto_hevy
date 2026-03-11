import streamlit as st
import requests
import pandas as pd
import os
import re
import google.generativeai as genai
from dotenv import load_dotenv

# 1. CONFIGURACIÓN MOBILE-FIRST
st.set_page_config(page_title="Hevy Coach AI", page_icon="⚡", layout="centered", initial_sidebar_state="collapsed")

load_dotenv()
API_KEY = os.getenv("HEVY_API_KEY")
ZONA_HORARIA = os.getenv("TIMEZONE", "America/Asuncion") 
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Configurar el Cerebro de IA
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

# 2. FUNCIONES DE DATOS (Auto-Sincronización)
@st.cache_data(ttl=300) 
def obtener_datos_hevy_auto():
    url = "https://api.hevyapp.com/v1/workouts"
    headers = {"api-key": API_KEY, "Accept": "application/json"}
    todos_los_workouts = []
    
    for pagina in range(1, 4): 
        params = {"page": pagina, "pageSize": 10} 
        response = requests.get(url, headers=headers, params=params)
        if response.status_code == 200:
            datos_pagina = response.json()
            if "workouts" in datos_pagina:
                todos_los_workouts.extend(datos_pagina["workouts"])
        else:
            return None 
    if todos_los_workouts:
        return {"workouts": todos_los_workouts}
    return None

def detectar_semana_actual(datos_json):
    if not datos_json or "workouts" not in datos_json or len(datos_json["workouts"]) == 0:
        return 1
    ultimo_entreno = datos_json["workouts"][0]
    for ej in ultimo_entreno.get("exercises", []):
        notas = ej.get("notes", "")
        match = re.search(r'[Ss]emana\s*(\d+)', notas)
        if match:
            semana = int(match.group(1))
            return semana if 1 <= semana <= 8 else 1
    return 1

def procesar_datos(datos_json):
    if not datos_json or "workouts" not in datos_json:
        return pd.DataFrame(), pd.DataFrame()
    lista_rutinas, lista_ejercicios = [], []
    for rutina in datos_json["workouts"]:
        nombre_rutina = rutina.get("title", "Sin nombre")
        fecha_cruda = rutina.get("start_time", "")
        volumen_total = 0
        for ejercicio in rutina.get("exercises", []):
            nombre_ej = ejercicio.get("title", "Desconocido")
            for serie in ejercicio.get("sets", []):
                peso = serie.get("weight_kg") or 0
                reps = serie.get("reps") or 0
                volumen_total += (peso * reps)
                rm_estimado = peso * (1 + (reps / 30)) if reps > 0 else 0
                lista_ejercicios.append({
                    "Fecha Cruda": fecha_cruda, "Rutina": nombre_rutina, "Ejercicio": nombre_ej,
                    "Serie": serie.get("index", 0) + 1, "Peso (Kg)": peso, "Reps": reps, "1RM Est.": round(rm_estimado, 1)
                })
        lista_rutinas.append({"Fecha Cruda": fecha_cruda, "Rutina": nombre_rutina, "Volumen Total (Kg)": volumen_total})
    df_rutinas, df_ejercicios = pd.DataFrame(lista_rutinas), pd.DataFrame(lista_ejercicios)
    for df in [df_rutinas, df_ejercicios]:
        if not df.empty:
            fechas_ajustadas = pd.to_datetime(df["Fecha Cruda"], utc=True).dt.tz_convert(ZONA_HORARIA) + pd.Timedelta(hours=1)
            df["Fecha"] = fechas_ajustadas.dt.strftime('%m-%d %H:%M') 
            df["Fecha Solo"] = fechas_ajustadas.dt.strftime('%Y-%m-%d')
    return df_rutinas, df_ejercicios

# 3. INTERFAZ PRINCIPAL
if not API_KEY:
    st.error("⚠️ Falta API Key de Hevy.")
else:
    datos_crudos = obtener_datos_hevy_auto()
    if datos_crudos:
        df_rutinas, df_ejercicios = procesar_datos(datos_crudos)
        semana_auto = detectar_semana_actual(datos_crudos)
        
        if not df_rutinas.empty:
            st.title("⚡ Panel Deportivo AI")
            col1, col2 = st.columns(2)
            with col1:
                rutina_max = df_rutinas.loc[df_rutinas['Volumen Total (Kg)'].idxmax()]
                st.metric("Récord Tonelaje", f"{rutina_max['Volumen Total (Kg)']:,.0f} kg", f"Día {rutina_max['Rutina']}")
            with col2:
                st.metric("Foco Actual", "Definición", "Retención Muscular")
            st.write("---")

            tab1, tab2, tab3, tab4 = st.tabs(["📊 Rendimiento", "📈 Fuerza", "🧠 AI Coach", "💧 Agua"])
            
            with tab1:
                st.subheader("Análisis Crítico")
                rutinas_recientes = df_rutinas.head(10) 
                for tipo_rutina in ["Push", "Pull", "Torso", "Leg"]:
                    datos_tipo = rutinas_recientes[rutinas_recientes["Rutina"].str.contains(tipo_rutina, case=False, na=False)]
                    if len(datos_tipo) >= 2:
                        vol_actual = datos_tipo.iloc[0]["Volumen Total (Kg)"]
                        vol_anterior = datos_tipo.iloc[1]["Volumen Total (Kg)"]
                        if vol_actual < vol_anterior:
                            st.error(f"🚨 **ALERTA {tipo_rutina.upper()}:** Volumen bajó a {vol_actual}kg. Forzar intensidad.")
                        else:
                            st.success(f"✅ **ÓPTIMO {tipo_rutina.upper()}:** Volumen en {vol_actual}kg.")
                st.line_chart(df_rutinas.iloc[::-1].set_index("Fecha")["Volumen Total (Kg)"], use_container_width=True)

            with tab2:
                st.subheader("Calculadora 1RM")
                ej_elegido = st.selectbox("Ejercicio:", df_ejercicios["Ejercicio"].unique(), key="ejercicio_rm")
                df_con_peso = df_ejercicios[(df_ejercicios["Ejercicio"] == ej_elegido) & (df_ejercicios["Peso (Kg)"] > 0)]
                if df_con_peso.empty:
                    st.info("💡 Este ejercicio no tiene registros de peso (Ej: peso corporal o bandas).")
                else:
                    df_max_rm = df_con_peso.groupby("Fecha Solo")["1RM Est."].max().reset_index()
                    df_max_rm["Fecha Solo"] = pd.to_datetime(df_max_rm["Fecha Solo"])
                    st.line_chart(df_max_rm.set_index("Fecha Solo"), y="1RM Est.", use_container_width=True)

            with tab3:
                st.subheader("Motor de Hipertrofia Inteligente")
                if "slider_semanas" not in st.session_state:
                    st.session_state.slider_semanas = semana_auto
                semana = st.slider("Fase del ciclo:", 1, 8, key="slider_semanas")
                
                reglas_ciclo = {
                    1: {"fase": "Calibración", "tempo": "3-1", "rir": "2", "desc": "NO llegues al fallo."},
                    2: {"fase": "Sobrecarga Inicial", "tempo": "3-1", "rir": "1-2", "desc": "Sube peso o haz 2 reps extra."},
                    3: {"fase": "Fuerza Pura", "tempo": "Normal", "rir": "1", "desc": "Sube peso obligatorio (10-12 reps)."},
                    4: {"fase": "Tortura Mecánica", "tempo": "4-2", "rir": "Fallo", "desc": "MISMO PESO Sem 3. Pausa 2 seg."},
                    5: {"fase": "Reinicio Interno", "tempo": "3-1", "rir": "2", "desc": "Pesos de Semana 2. Técnica limpia."},
                    6: {"fase": "Nuevo Pico", "tempo": "Normal", "rir": "0", "desc": "Rompe récord de la Semana 3."},
                    7: {"fase": "Prueba Final", "tempo": "4-2", "rir": "Fallo", "desc": "Pesos récord con bajada de 4 seg."},
                    8: {"fase": "Descarga (Eco)", "tempo": "Normal", "rir": "Fácil", "desc": "Pesos al 50%. 1 serie menos."}
                }
                st.info(f"🎯 **{reglas_ciclo[semana]['fase']}**\n\n⏱️ Tempo: {reglas_ciclo[semana]['tempo']} | 🔋 RIR: {reglas_ciclo[semana]['rir']}\n\n📖 {reglas_ciclo[semana]['desc']}")
                
                ej_hipertrofia = st.selectbox("Proyectar peso para:", df_ejercicios["Ejercicio"].unique(), key="select_hiper")
                df_hist_ej = df_ejercicios[(df_ejercicios["Ejercicio"] == ej_hipertrofia) & (df_ejercicios["Peso (Kg)"] > 0)]
                
                peso_maximo = df_hist_ej["Peso (Kg)"].max() if not df_hist_ej.empty else 0
                peso_reciente = df_hist_ej.iloc[0]["Peso (Kg)"] if not df_hist_ej.empty else 0
                
                if not df_hist_ej.empty:
                    if semana == 8:
                        st.success(f"⚖️ **Peso hoy:** {peso_maximo * 0.5:.1f} kg")
                    elif semana in [4, 7]:
                        st.warning(f"⚖️ **Peso hoy:** {peso_reciente} kg (Con Tempo {reglas_ciclo[semana]['tempo']})")
                    else:
                        st.info(f"📊 Récord histórico: **{peso_maximo} kg**.")
                
                st.write("---")
                # --- BOTÓN DE INTELIGENCIA ARTIFICIAL ---
                if st.button(f"🧠 Consultar al Coach IA sobre: {ej_hipertrofia}", use_container_width=True):
                    if not GEMINI_API_KEY:
                        st.error("No se detectó la clave de Gemini en los Secrets.")
                    elif peso_maximo == 0:
                        st.warning("El Coach necesita que este ejercicio tenga un peso registrado mayor a 0 kg para calcular.")
                    else:
                        with st.spinner("Analizando tu sistema nervioso y muscular..."):
                            try:
                                modelo = genai.GenerativeModel('gemini-1.5-flash')
                                prompt = f"""
                                Actúa como un entrenador personal analítico, directo y experto en hipertrofia.
                                Tu cliente está en una fase de definición estricta (cutting) hasta mayo, y su meta principal es llegar magro reteniendo el 100% de la masa muscular mediante estímulos calculados.
                                Hoy está en la Semana {semana} de su ciclo de 8 semanas.
                                Fase del día: {reglas_ciclo[semana]['fase']}.
                                Regla obligatoria hoy: {reglas_ciclo[semana]['desc']}. Tempo a respetar: {reglas_ciclo[semana]['tempo']}, RIR: {reglas_ciclo[semana]['rir']}.
                                
                                Ejercicio que está por hacer: {ej_hipertrofia}.
                                Récord histórico en este ejercicio: {peso_maximo} kg.
                                Peso levantado la última vez: {peso_reciente} kg.
                                
                                Escribe un consejo de 2 párrafos, estratégico y motivador. Dile exactamente cómo aplicar la regla de esta semana a esos kilos específicos para que el déficit calórico queme grasa y no músculo. Háblale directamente a él, sin saludos genéricos ni despedidas.
                                """
                                respuesta = modelo.generate_content(prompt)
                                st.success(respuesta.text)
                            except Exception as e:
                                st.error(f"Error en el servidor de IA: {e}")

            with tab4:
                st.subheader("💧 Check de Hidratación")
                st.checkbox("04:30 AM - Escudo Sal + Café", key="h1")
                st.checkbox("05:00 AM - Botella 500ml Gym", key="h2")
                st.checkbox("08:00 AM a 12PM - 500ml Oficina", key="h3")
                st.checkbox("12:00 PM - Almuerzo (250ml) + Caminata", key="h4")
                st.checkbox("13:30 PM - Tereré (Límite 1L)", key="h5")
                st.checkbox("17:00 PM - Cardio Intenso (500ml)", key="h6")
                st.checkbox("19:00 PM - Universidad (500ml)", key="h7")
                st.checkbox("22:00 PM - Shutdown", key="h8")
        else:
            st.warning("Tu historial está vacío.")
