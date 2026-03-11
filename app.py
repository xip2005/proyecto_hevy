import streamlit as st
import requests
import pandas as pd
import os
import re
from dotenv import load_dotenv

# 1. Configuración de página (DEBE ser la primera línea)
st.set_page_config(page_title="Hevy Pro Analytics", page_icon="⚡", layout="wide")

load_dotenv()
API_KEY = os.getenv("HEVY_API_KEY")
ZONA_HORARIA = os.getenv("TIMEZONE", "America/Asuncion") 

# 2. MOTOR DE TEMAS (CLARO / OSCURO)
if "modo_oscuro" not in st.session_state:
    st.session_state.modo_oscuro = False

modo_oscuro = st.sidebar.toggle("🌙 Activar Modo Oscuro", value=st.session_state.modo_oscuro)
st.session_state.modo_oscuro = modo_oscuro

# Definición de colores según el tema
if not modo_oscuro:
    bg_app = "#f4f7f6"        # Fondo gris clarito muy moderno
    bg_card = "#ffffff"       # Tarjetas blancas
    color_texto = "#1e1e1e"   # Letras oscuras
    borde = "#e0e0e0"
    sombra = "0 4px 12px rgba(0,0,0,0.05)"
else:
    bg_app = "#0e1117"
    bg_card = "#1e1e1e"
    color_texto = "#fafafa"
    borde = "#333333"
    sombra = "0 4px 12px rgba(255,255,255,0.02)"

# Inyección del CSS Dinámico
st.markdown(f"""
    <style>
    /* Fondo general */
    .stApp {{
        background-color: {bg_app};
    }}
    /* Tarjetas de Métricas (KPIs) */
    div[data-testid="metric-container"] {{
        background-color: {bg_card};
        border: 1px solid {borde};
        padding: 5% 5% 5% 10%;
        border-radius: 12px;
        box-shadow: {sombra};
        color: {color_texto};
    }}
    /* Títulos generales */
    h1, h2, h3, h4, p, span {{
        color: {color_texto} !important;
    }}
    /* Estilizar Pestañas para que parezcan tarjetas */
    .stTabs [data-baseweb="tab-list"] {{
        gap: 10px;
    }}
    .stTabs [data-baseweb="tab"] {{
        background-color: {bg_card};
        border-radius: 8px 8px 0 0;
        border: 1px solid {borde};
        border-bottom: none;
        box-shadow: {sombra};
    }}
    </style>
""", unsafe_allow_html=True)

# 3. FUNCIONES DE DATOS (Con Caché Automático de 5 Minutos)
@st.cache_data(ttl=300) # ttl=300 significa Time To Live de 300 segundos (5 min)
def obtener_datos_hevy_auto():
    url = "https://api.hevyapp.com/v1/workouts"
    headers = {"api-key": API_KEY, "Accept": "application/json"}
    
    todos_los_workouts = []
    
    for pagina in range(1, 4): # Extrae las últimas 3 páginas (30 rutinas)
        params = {"page": pagina, "pageSize": 10} 
        response = requests.get(url, headers=headers, params=params)
        
        if response.status_code == 200:
            datos_pagina = response.json()
            if "workouts" in datos_pagina:
                todos_los_workouts.extend(datos_pagina["workouts"])
        else:
            return None # Si hay error, devuelve nulo para no romper la app
            
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

# 4. BARRA LATERAL (Hidratación)
with st.sidebar:
    st.title("⚡ Hevy Analytics")
    st.caption("Estado: " + ("🟢 API Sincronizada" if API_KEY else "🔴 Falta Key"))
    
    st.write("---")
    st.subheader("💧 Protocolo de Hidratación")
    st.checkbox("04:30 AM - Escudo Sal + Café", key="hidrato_1")
    st.checkbox("05:00 AM - Botella 500ml Gym", key="hidrato_2")
    st.checkbox("08:00 AM a 12PM - 500ml Oficina", key="hidrato_3")
    st.checkbox("12:00 PM - Almuerzo (250ml) + Caminata", key="hidrato_4")
    st.checkbox("13:30 PM - Tereré (Límite 1L)", key="hidrato_5")
    st.checkbox("17:00 PM - Cardio Intenso (500ml)", key="hidrato_6")
    st.checkbox("19:00 PM - Universidad (500ml)", key="hidrato_7")
    st.checkbox("22:00 PM - Shutdown (Cero líquidos)", key="hidrato_8")

# 5. SINCRONIZACIÓN AUTOMÁTICA Y PANTALLA PRINCIPAL
if not API_KEY:
    st.error("⚠️ Falta API Key en la configuración.")
else:
    with st.spinner("Sincronizando con Hevy de forma invisible..."):
        datos_crudos = obtener_datos_hevy_auto()
        
    if datos_crudos:
        df_rutinas, df_ejercicios = procesar_datos(datos_crudos)
        semana_auto = detectar_semana_actual(datos_crudos)
        
        if not df_rutinas.empty:
            st.title("Panel de Rendimiento Deportivo")
            
            # Tarjetas de Métricas (KPIs Profesionales)
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Sesiones Analizadas", f"{len(df_rutinas)} rutinas")
            with col2:
                rutina_max = df_rutinas.loc[df_rutinas['Volumen Total (Kg)'].idxmax()]
                st.metric("Récord de Volumen", f"{rutina_max['Volumen Total (Kg)']:,.0f} kg", f"Día de {rutina_max['Rutina']}")
            with col3:
                st.metric("Foco Actual", "Retención Muscular", "Alerta de Intensidad ON")

            st.write("---")

            # Pestañas
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
                ejercicio_elegido = st.selectbox("Selecciona un ejercicio para analizar:", ejercicios_unicos, key="ejercicio_rm")
                
                df_filtro = df_ejercicios[df_ejercicios["Ejercicio"] == ejercicio_elegido]
                df_max_rm = df_filtro.groupby("Fecha Solo")["1RM Est."].max().reset_index()
                df_max_rm["Fecha Solo"] = pd.to_datetime(df_max_rm["Fecha Solo"])
                
                st.write(f"Tendencia de fuerza en **{ejercicio_elegido}**")
                st.line_chart(df_max_rm.set_index("Fecha Solo"), y="1RM Est.", use_container_width=True)

            with tab3:
                st.subheader("Análisis Crítico de Rendimiento")
                rutinas_recientes = df_rutinas.head(15) 
                
                for tipo_rutina in ["Push", "Pull", "Torso", "Leg"]:
                    datos_tipo = rutinas_recientes[rutinas_recientes["Rutina"].str.contains(tipo_rutina, case=False, na=False)]
                    if len(datos_tipo) >= 2:
                        vol_actual = datos_tipo.iloc[0]["Volumen Total (Kg)"]
                        vol_anterior = datos_tipo.iloc[1]["Volumen Total (Kg)"]
                        if vol_actual < vol_anterior:
                            st.error(f"🚨 **ALERTA EN {tipo_rutina.upper()}:** El volumen cayó de {vol_anterior}kg a {vol_actual}kg.")
                        else:
                            st.success(f"✅ **ÓPTIMO EN {tipo_rutina.upper()}:** Volumen mantenido o en aumento ({vol_actual}kg).")

            with tab4:
                st.subheader("⚙️ Sistema de Hipertrofia (Controlador de Ciclos)")
                
                if "slider_semanas" not in st.session_state:
                    st.session_state.slider_semanas = semana_auto
                    
                semana = st.slider("Semana de tu ciclo:", 1, 8, key="slider_semanas")
                
                reglas_ciclo = {
                    1: {"fase": "Calibración", "tempo": "3-1", "rir": "2", "desc": "Encontrar peso base. NO llegues al fallo."},
                    2: {"fase": "Sobrecarga Inicial", "tempo": "3-1", "rir": "1-2", "desc": "Sube peso o haz 2 reps extra."},
                    3: {"fase": "Fuerza Pura", "tempo": "Normal", "rir": "1", "desc": "Aumenta peso obligatorio para 10-12 reps."},
                    4: {"fase": "Tortura Mecánica", "tempo": "4-2", "rir": "Fallo", "desc": "Usa EL MISMO PESO de la Sem 3. Pausa 2 seg."},
                    5: {"fase": "Reinicio Interno", "tempo": "3-1", "rir": "2", "desc": "Usa pesos de la Semana 2. Técnica impecable."},
                    6: {"fase": "Nuevo Pico de Fuerza", "tempo": "Normal", "rir": "0", "desc": "Rompe tu récord. Supera peso de Sem 3."},
                    7: {"fase": "La Prueba Final", "tempo": "4-2", "rir": "Fallo", "desc": "Usa pesos récord con bajada de 4 seg."},
                    8: {"fase": "Descarga (Eco)", "tempo": "Normal", "rir": "Fácil", "desc": "Baja TODOS los pesos al 50%. 1 serie menos."}
                }
                
                st.info(f"🎯 **{reglas_ciclo[semana]['fase']}** | ⏱️ Tempo: {reglas_ciclo[semana]['tempo']} | 🔋 RIR: {reglas_ciclo[semana]['rir']}\n\n📖 {reglas_ciclo[semana]['desc']}")
                
                st.write("---")
                ej_hipertrofia = st.selectbox("Calculadora de peso para:", df_ejercicios["Ejercicio"].unique(), key="select_hiper")
                df_hist_ej = df_ejercicios[df_ejercicios["Ejercicio"] == ej_hipertrofia]
                
                if not df_hist_ej.empty:
                    peso_maximo = df_hist_ej["Peso (Kg)"].max()
                    peso_reciente = df_hist_ej.iloc[0]["Peso (Kg)"]
                    
                    if semana == 8:
                        st.success(f"⚖️ **Peso hoy:** {peso_maximo * 0.5:.1f} kg *(El 50% de tu máximo histórico)*")
                    elif semana in [4, 7]:
                        st.warning(f"⚖️ **Peso hoy:** Mantén tu pesado ({peso_reciente} kg) pero con Tempo {reglas_ciclo[semana]['tempo']}.")
                    elif semana in [1, 5]:
                        st.info(f"⚖️ **Proyección:** Arrancas con peso de la Semana 2 anterior. Tu récord aquí fue {peso_maximo} kg.")
                    else:
                        st.info(f"📊 Peso máximo histórico: **{peso_maximo} kg**. Ajusta los discos según la regla.")
        else:
            st.warning("La API conectó pero tu historial de Hevy está vacío.")
    else:
        st.error("No se pudo obtener la conexión con Hevy. Revisa los registros.")