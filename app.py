import streamlit as st
import numpy as np
import matplotlib.pyplot as plt

# --- PSY KROMETRISKA FUNKTIONER ---
def saturation_vapor_pressure(T):
    """Mättnadstryck för vattenånga (Pa) via Magnus-formeln"""
    return 611.2 * np.exp((17.67 * T) / (T + 243.5))

def rh_to_absolute_moisture(T, RH):
    """Konverterar RH (%) till absolut fuktighet (g/m³)"""
    P_sat = saturation_vapor_pressure(T)
    P_v = (RH / 100.0) * P_sat
    return (P_v / (461.5 * (T + 273.15))) * 1000 

def absolute_moisture_to_rh(T, rho_v):
    """Konverterar absolut fuktighet (g/m³) till RH (%)"""
    P_sat = saturation_vapor_pressure(T)
    P_v = (rho_v / 1000.0) * 461.5 * (T + 273.15)
    return min(100.0, max(0.0, (P_v / P_sat) * 100))

# --- PID-REGULATOR CLASS ---
class PIDController:
    def __init__(self, Kp, Ki, Kd, dt, output_limits=(0, 100)):
        self.Kp, self.Ki, self.Kd, self.dt = Kp, Ki, Kd, dt
        self.min_limit, self.max_limit = output_limits
        self.integral, self.last_error = 0.0, 0.0

    def calculate(self, setpoint, measurement):
        error = setpoint - measurement
        self.integral = max(-2000.0, min(2000.0, self.integral + error * self.dt))
        derivative = (error - self.last_error) / self.dt
        output = (self.Kp * error) + (self.Ki * self.integral) + (self.Kd * derivative)
        self.last_error = error
        return max(self.min_limit, min(output, self.max_limit))

# --- STRÄMLIT GRÄNSSNITT ---
st.set_page_config(layout="wide", page_title="Museum Klimatsimulering")
st.title("🏛️ Interaktivt Simuleringsverktyg: Klimatstyrt Museum")
st.markdown("Detta verktyg simulerar termodynamiken och fuktbalansen i en museisal under 24 timmar. Justera parametrarna i sidomenyn för att studera hur reglerstrategierna hanterar dygnsstörningar från solinstrålning och besökare.")

# Sidomeny (Sidebar) uppdelad i logiska sektioner
st.sidebar.header("🎯 Börvärden (Setpoints)")
T_setpoint = st.sidebar.slider("Börvärde Temperatur (°C)", 18.0, 25.0, 21.0, 0.5)
RH_setpoint = st.sidebar.slider("Börvärde Fukt (RH %)", 30.0, 70.0, 50.0, 5.0)

st.sidebar.header("🏢 Byggnad & Belastning")
Volym = st.sidebar.slider("Byggnadens Volym (m³)", 500, 5000, 1000, 100)
max_besökare = st.sidebar.slider("Max antal besökare (peak)", 0, 300, 80, 10)

st.sidebar.header("🔥 Radiatorkrets (Rumstemperatur)")
rad_Kp = st.sidebar.slider("Radiator Kp", 10, 1000, 400, 10)
rad_Ki = st.sidebar.slider("Radiator Ki", 0.00, 0.50, 0.05, 0.01)
rad_Kd = st.sidebar.slider("Radiator Kd", 0, 200, 50, 5)

st.sidebar.header("💨 Ventilation (LBU/AHU)")
ahu_Kp = st.sidebar.slider("Tilluft Temp Kp", 0.1, 5.0, 1.5, 0.1)
ahu_Ki = st.sidebar.slider("Tilluft Temp Ki", 0.000, 0.050, 0.002, 0.001)
fukt_Kp = st.sidebar.slider("Tilluft Fukt Kp", 0.05, 2.00, 0.40, 0.05)
fukt_Ki = st.sidebar.slider("Tilluft Fukt Ki", 0.0000, 0.0050, 0.0005, 0.0001)

# --- SIMULERINGSLOOP ---
dt = 60 
steg = int((24 * 3600) / dt)
U_total = 200.0
C_air = Volym * 1200.0
C_walls = C_air * 5.0

T_room, T_structure = 20.0, 20.0
g_rum = rh_to_absolute_moisture(T_room, 50.0)

pid_radiator = PIDController(rad_Kp, rad_Ki, rad_Kd, dt, output_limits=(0, 15000))
pid_ahu_temp = PIDController(ahu_Kp, ahu_Ki, 0.1, dt, output_limits=(15.0, 28.0))
pid_ahu_moisture = PIDController(fukt_Kp, fukt_Ki, 0.0, dt, output_limits=(3.0, 14.0))

history = {
    'tid': [], 'T_room': [], 'RH_room': [], 'T_out': [], 
    'personer': [], 'sol': [], 'rad_power': [], 'T_supply': []
}

for s in range(steg):
    t_timmar = (s * dt) / 3600.0
    T_outdoor = 12.0 + 8.0 * np.sin(2 * np.pi * (t_timmar - 8) / 24)
    sol_vinst = 4000.0 * max(0.0, np.sin(2 * np.pi * (t_timmar - 6) / 24)) if 6 < t_timmar < 18 else 0.0
    personer = int(max_besökare * np.sin(np.pi * (t_timmar - 10) / 8)) if 10.0 <= t_timmar <= 18.0 else 0
    
    int_varme_vinst = personer * 80.0
    int_fukt_vinst = personer * 50.0 / 3600

    rad_power = pid_radiator.calculate(T_setpoint, T_room)
    flow = ((3.0 * Volym) / 3600) if T_room > 22.0 else ((0.5 * Volym) / 3600)
    
    T_supply = pid_ahu_temp.calculate(T_setpoint, T_room)
    g_supply_setpoint = rh_to_absolute_moisture(T_setpoint, RH_setpoint)
    g_supply = pid_ahu_moisture.calculate(g_supply_setpoint, g_rum)

    q_trans = U_total * (T_room - T_outdoor)
    q_structure = 500.0 * (T_room - T_structure)
    q_vent = flow * 1.2 * 1000 * (T_supply - T_room)
    
    T_room += ((rad_power + q_vent + int_varme_vinst + sol_vinst - q_trans - q_structure) * dt) / C_air
    T_structure += (q_structure * dt) / C_walls
    g_rum += (((flow * (g_supply - g_rum)) + int_fukt_vinst) * dt) / Volym
    RH_room = absolute_moisture_to_rh(T_room, g_rum)

    history['tid'].append(t_timmar)
    history['T_room'].append(T_room)
    history['RH_room'].append(RH_room)
    history['T_out'].append(T_outdoor)
    history['personer'].append(personer)
    history['sol'].append(sol_vinst / 1000)
    history['rad_power'].append(rad_power / 1000)
    history['T_supply'].append(T_supply)

# --- RITA LAYOUT OCH GRAFER ---
col1, col2 = st.columns(2)

with col1:
    st.subheader("🌡️ Temperaturutveckling")
    fig1, ax1 = plt.subplots(figsize=(6, 3.5))
    ax1.plot(history['tid'], history['T_room'], 'r-', label="Innetemp (°C)", linewidth=2)
    ax1.axhline(T_setpoint, color='r', linestyle='--', alpha=0.6, label="Börvärde")
    ax1.plot(history['tid'], history['T_out'], 'k--', alpha=0.4, label="Utetemp (°C)")
    ax1.set_ylabel("Temperatur (°C)")
    ax1.set_xlabel("Tid (timmar)")
    ax1.grid(True)
    ax1.legend(loc='lower left', fontsize='small')
    st.pyplot(fig1)

    st.subheader("👥 Belastning & Störningar")
    fig3, ax3 = plt.subplots(figsize=(6, 3.5))
    ax3.plot(history['tid'], history['personer'], 'g-', label="Besökare (st)")
    ax3.set_ylabel("Personer (st)", color='g')
    ax3.set_xlabel("Tid (timmar)")
    ax3.grid(True)
    
    ax3_b = ax3.twinx()
    ax3_b.plot(history['tid'], history['sol'], 'y-', label="Sol (kW)")
    ax3_b.set_ylabel("Solinstrålning (kW)", color='y')
    
    lines, labels = ax3.get_legend_handles_labels()
    lines2, labels2 = ax3_b.get_legend_handles_labels()
    ax3.legend(lines + lines2, labels + labels2, loc='upper left', fontsize='small')
    st.pyplot(fig3)

with col2:
    st.subheader("💧 Relativ Fukt")
    fig2, ax2 = plt.subplots(figsize=(6, 3.5))
    ax2.plot(history['tid'], history['RH_room'], 'b-', label="Inne RH (%)", linewidth=2)
    ax2.axhline(RH_setpoint, color='b', linestyle='--', alpha=0.6, label="Börvärde")
    ax2.set_ylabel("Relativ Fuktighet (%)")
    ax2.set_xlabel("Tid (timmar)")
    ax2.set_ylim(20, 80)
    ax2.grid(True)
    ax2.legend(loc='lower left', fontsize='small')
    st.pyplot(fig2)

    st.subheader("⚡ Reglersystemets Pådrag")
    fig4, ax4 = plt.subplots(figsize=(6, 3.5))
    ax4.plot(history['tid'], history['rad_power'], 'r-', label="Radiator (kW)")
    ax4.plot(history['tid'], history['T_supply'], 'm-', label="Tilluft Temp (°C)")
    ax4.set_ylabel("Pådrag")
    ax4.set_xlabel("Tid (timmar)")
    ax4.grid(True)
    ax4.legend(loc='upper left', fontsize='small')
    st.pyplot(fig4)
