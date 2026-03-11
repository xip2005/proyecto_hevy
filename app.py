import streamlit as st
import requests
import pandas as pd
import os
import re
from dotenv import load_dotenv

# 1. Configuración de página
st.set_page_config(page_title="Hevy Pro Analytics", page_icon="⚡", layout="wide")

load_dotenv()
API_KEY = os.getenv("HEVY_API_KEY")
ZONA_HORARIA = os.getenv("TIMEZONE", "America/Asuncion") 

# --- CSS Personalizado ---
st.markdown("""
    <style>
    .block-container { padding-top: 1.5rem; }
    div[data-testid="metric-container"] {
        background-color: #1E1E1E;
        border: 1px solid #333;
        padding: 5% 5% 5% 10%;
        border-radius: 10px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.3);
    }
    </style>
""", unsafe_allow_html=True)

# 2. Funciones de Datos
def obtener_datos_hevy(paginas_a_extraer=3):
    url = "https://api.hevyapp.com/v1/workouts"
    headers = {"api-key": API_KEY, "Accept": "application/json"}
    
    todos_los_workouts = []
    
    for pagina in range(1, paginas_a_extraer + 1):
        params = {"page": pagina, "pageSize": 10} 
        response = requests.get(url, headers=headers, params=params)
        
        if response.status_code == 200:
            datos_pagina = response.json()
            if "workouts" in datos_pagina:
                todos_los_workouts.extend(datos_pagina["workouts"])
        else:
            st.sidebar.error(f"Error HTTP en página {pagina}: {response.status_code}")
            break
            
    if todos_los_workouts:
        return {"workouts": todos_los_workouts}
    return None

def detectar_semana_actual(datos_json):
    """Busca en las notas del último entrenamiento para autodetectar la semana"""
    if not datos_json or "workouts" not in datos_json or len(datos_json["workouts"]) == 0:
        return 1
        
    ultimo_entreno = datos_json["workouts"][0]
    for ej in ultimo_entreno.get("exercises", []):
        notas = ej.get("notes", "")
        # Busca patrones como "Semana 2" o "semana 4"
        match = re.search(r'[Ss]emana\s*(\d+)', notas)
        if match:
            semana = int(match.group(1))
            return semana if 1 <= semana <= 8 else 1
    return 1

def procesar_datos(datos_json):
    if not datos_json or "workouts" not in datos_json:
        return pd.DataFrame(), pd.DataFrame()
    
    lista_rutinas = []
    lista_ejercicios = []
    
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
                    "Fecha Cruda": fecha_cruda,
                    "Rutina": nombre_rutina,
                    "Ejercicio": nombre_ej,
                    "Serie": serie.get("index", 0) + 1,
                    "Peso (Kg)": peso,
                    "Reps": reps,
                    "1RM Est.": round(rm_estimado, 1)
                })
                
        lista_rutinas.append({
            "Fecha Cruda": fecha_cruda,
            "Rutina": nombre_rutina,
            "Volumen Total (Kg)": volumen_total
        })
        
    df_rutinas = pd.DataFrame(lista_rutinas)
    df_ejercicios = pd.DataFrame(lista_ejercicios)
    
    for df in [df_rutinas, df_ejercicios]:
        if not df.empty:
            fechas_ajustadas = pd.to_datetime(df["Fecha Cruda"], utc=True).dt.tz_convert(ZONA_HORARIA) + pd.Timedelta(hours=1)
            df["Fecha"] = fechas_ajustadas.dt.strftime('%Y-%m-%d %H:%M')
            df["Fecha Solo"] = fechas_ajustadas.dt.strftime('%Y-%m-%d')
            
    return df_rutinas, df_ejercicios

# 3. Estado de la Sesión
if 'datos_cargados' not in st.session_state:
    st.session_state.datos_cargados = False

# 4. BARRA LATERAL (Panel de Control e Hidratación)
with st.sidebar:
    st.title("⚡ Hevy Analytics")
    st.write("---")
    
    if st.button("🔄 Sincronizar Servidor", use_container_width=True):
        if not API_KEY:
            st.error("Falta API Key en .env")
        else:
            with st.spinner("Extrayendo historial y autodetectando semana..."):
                datos = obtener_datos_hevy()
                if datos:
                    df_r, df_e = procesar_datos(datos)
                    semana_auto = detectar_semana_actual(datos)
                    
                    if not df_r.empty:
                        st.session_state.df_rutinas = df_r
                        st.session_state.df_ejercicios = df_e
                        st.session_state.datos_cargados = True
                        st.session_state.slider_semanas = semana_auto # Fija el slider automáticamente
                        st.rerun() 
                    else:
                        st.warning("La API conectó, pero no hay rutinas guardadas.")
                else:
                    st.error("No se pudo obtener el JSON de Hevy.")
    
    st.caption("Estado: " + ("🟢 API Lista" if API_KEY else "🔴 Falta Key"))
    
    # --- CHECKLIST DE HIDRATACIÓN 2.0 (CON MEMORIA KEY) --- [cite: 75]
    st.write("---")
    st.subheader("💧 Protocolo de Hidratación")
    st.checkbox("04:30 AM - Escudo Sal + Café", key="hidrato_1") # [cite: 76, 77]
    st.checkbox("05:00 AM - Botella 500ml Gym", key="hidrato_2") # [cite: 79, 80]
    st.checkbox("08:00 AM a 12PM - 500ml Oficina", key="hidrato_3") # [cite: 83, 84]
    st.checkbox("12:00 PM - Almuerzo (250ml) + Caminata", key="hidrato_4") # [cite: 87, 88, 90]
    st.checkbox("13:30 PM - Tereré (Límite 1L)", key="hidrato_5") # [cite: 91, 93]
    st.checkbox("17:00 PM - Cardio Intenso (500ml)", key="hidrato_6") # [cite: 97, 98]
    st.checkbox("19:00 PM - Universidad (500ml)", key="hidrato_7") # [cite: 100, 101]
    st.checkbox("22:00 PM - Shutdown (Cero líquidos)", key="hidrato_8") # [cite: 104, 105]

# 5. PANTALLA PRINCIPAL
if st.session_state.datos_cargados:
    df_rutinas = st.session_state.df_rutinas
    df_ejercicios = st.session_state.df_ejercicios

    st.title("Panel de Rendimiento Deportivo")
    
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Sesiones Analizadas", f"{len(df_rutinas)} rutinas")
    with col2:
        rutina_max = df_rutinas.loc[df_rutinas['Volumen Total (Kg)'].idxmax()]
        st.metric("Récord de Volumen", f"{rutina_max['Volumen Total (Kg)']:,.0f} kg", f"Día de {rutina_max['Rutina']}")
    with col3:
        st.metric("Foco Actual", "Retención Muscular", "Alerta de Intensidad ON")

    st.write("---")

    tab1, tab2, tab3, tab4 = st.tabs([
        "📊 Historial de Volumen", 
        "📈 Progresión de Fuerza", 
        "🧠 Motor de Alertas", 
        "⚙️ Sistema de Hipertrofia"
    ])
    
    with tab1:
        st.subheader("Evolución del Tonelaje")
        st.line_chart(df_rutinas.iloc[::-1].set_index("Fecha Solo")["Volumen Total (Kg)"], use_container_width=True)
        st.dataframe(df_rutinas[["Fecha", "Rutina", "Volumen Total (Kg)"]], use_container_width=True)

    with tab2:
        st.subheader("Calculadora de Repetición Máxima (Epley)")
        ejercicios_unicos = df_ejercicios["Ejercicio"].unique()
        # Lista con memoria
        ejercicio_elegido = st.selectbox("Selecciona un ejercicio para analizar:", ejercicios_unicos, key="ejercicio_rm")
        
        df_filtro = df_ejercicios[df_ejercicios["Ejercicio"] == ejercicio_elegido]
        df_max_rm = df_filtro.groupby("Fecha Solo")["1RM Est."].max().reset_index()
        
        df_max_rm["Fecha Solo"] = pd.to_datetime(df_max_rm["Fecha Solo"])
        
        st.write(f"Tendencia de fuerza en **{ejercicio_elegido}**")
        st.line_chart(df_max_rm.set_index("Fecha Solo"), y="1RM Est.", use_container_width=True)
        
        with st.expander("Ver Datos Crudos del 1RM"):
            st.dataframe(df_max_rm, use_container_width=True)

    with tab3:
        st.subheader("Análisis Crítico de Rendimiento")
        st.write("Mantener el volumen y la intensidad es vital en esta fase de definición.")
        rutinas_recientes = df_rutinas.head(15) 
        
        for tipo_rutina in ["Push", "Pull", "Torso", "Leg"]:
            datos_tipo = rutinas_recientes[rutinas_recientes["Rutina"].str.contains(tipo_rutina, case=False, na=False)]
            if len(datos_tipo) >= 2:
                vol_actual = datos_tipo.iloc[0]["Volumen Total (Kg)"]
                vol_anterior = datos_tipo.iloc[1]["Volumen Total (Kg)"]
                if vol_actual < vol_anterior:
                    st.error(f"🚨 **ALERTA EN {tipo_rutina.upper()}:** El volumen cayó de {vol_anterior}kg a {vol_actual}kg. Forzar intensidad.")
                else:
                    st.success(f"✅ **ÓPTIMO EN {tipo_rutina.upper()}:** Volumen mantenido o en aumento ({vol_actual}kg).")

    with tab4:
        st.subheader("⚙️ Sistema de Hipertrofia (Controlador de Ciclos)") # [cite: 1]
        
        # Slider con memoria. Si se detectó la semana, se ajusta solo.
        if "slider_semanas" not in st.session_state:
            st.session_state.slider_semanas = 1
            
        semana = st.slider("¿En qué semana de tu ciclo te encuentras hoy?", 1, 8, key="slider_semanas")
        
        # Diccionario lógico del manual
        reglas_ciclo = {
            1: {"fase": "Calibración", "tempo": "3-1", "rir": "2", "desc": "Encontrar peso base. NO llegues al fallo."} , # [cite: 16, 17, 18, 19, 20]
            2: {"fase": "Sobrecarga Inicial", "tempo": "3-1", "rir": "1-2", "desc": "Opción A: Sube 2.5kg. Opción B: Mismo peso, 2 reps extra."} , # [cite: 21, 22, 23, 24, 25]
            3: {"fase": "Fuerza Pura", "tempo": "Normal", "rir": "1", "desc": "Ritmo fluido. Aumenta peso obligatorio para 10-12 reps."} , # [cite: 26, 27, 28, 29, 30]
            4: {"fase": "Tortura Mecánica", "tempo": "4-2", "rir": "Fallo", "desc": "Usa EL MISMO PESO de la Semana 3. Pausa de 2 seg abajo."} , # [cite: 31, 32, 33, 34]
            5: {"fase": "Reinicio Interno", "tempo": "3-1", "rir": "2", "desc": "Usa los pesos que manejaste en la Semana 2. Técnica impecable."} , # [cite: 37, 38, 39, 40]
            6: {"fase": "Nuevo Pico de Fuerza", "tempo": "Normal", "rir": "0", "desc": "Rompe tu récord. Supera el peso de la Semana 3."} , # [cite: 41, 42, 43, 44]
            7: {"fase": "La Prueba Final", "tempo": "4-2", "rir": "Fallo", "desc": "Usa los pesos récord de la Sem 6 con bajada de 4 segundos."} , # [cite: 45, 46, 47, 48]
            8: {"fase": "Descarga (Eco)", "tempo": "Normal", "rir": "Fácil", "desc": "Baja TODOS los pesos a la mitad (50%) y haz una serie menos."} # [cite: 50, 51, 52, 53, 54]
        }
        
        st.info(f"🎯 **Objetivo:** {reglas_ciclo[semana]['fase']}\n\n⏱️ **Tempo:** {reglas_ciclo[semana]['tempo']} | 🔋 **RIR:** {reglas_ciclo[semana]['rir']}\n\n📖 **Regla del día:** {reglas_ciclo[semana]['desc']}")
        
        st.write("---")
        st.subheader("🧮 Calculadora de Peso por Ejercicio")
        # Selector de ejercicio con memoria
        ej_hipertrofia = st.selectbox("Elige el ejercicio a realizar:", df_ejercicios["Ejercicio"].unique(), key="select_hiper")
        
        df_hist_ej = df_ejercicios[df_ejercicios["Ejercicio"] == ej_hipertrofia]
        
        if not df_hist_ej.empty:
            peso_maximo = df_hist_ej["Peso (Kg)"].max()
            peso_reciente = df_hist_ej.iloc[0]["Peso (Kg)"]
            
            if semana == 8:
                peso_descarga = peso_maximo * 0.5 # [cite: 53]
                st.success(f"⚖️ **Tu peso para hoy:** {peso_descarga:.1f} kg *(El 50% de tu máximo histórico de {peso_maximo} kg. Haz 1 serie menos).*") # [cite: 53, 54]
            elif semana == 4 or semana == 7:
                st.warning(f"⚖️ **Tu peso para hoy:** Mantén tu peso pesado ({peso_reciente} kg) pero aplícale el Tempo {reglas_ciclo[semana]['tempo']}. Te van a salir menos reps, es lo esperado.") # [cite: 34, 48]
            elif semana == 1 or semana == 5:
                # Proyección lógica del ciclo anterior (Semana 2) [cite: 59]
                st.info(f"⚖️ **Proyección de Arranque:** Según la regla de reinicio, debes arrancar con el peso de la Semana 2 del ciclo anterior. Tu máximo histórico aquí fue **{peso_maximo} kg**.") # [cite: 59]
            else:
                st.info(f"📊 Tu peso máximo histórico es **{peso_maximo} kg**. Aplica la regla de arriba para decidir los discos de hoy.")
        
else:
    st.title("Bienvenido al Motor Analítico")
    st.info("👈 Por favor, utiliza el panel lateral para sincronizar tus datos con los servidores de Hevy.")