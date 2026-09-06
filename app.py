import streamlit as st
import sqlite3
import os
import hashlib
import datetime
import random
import string
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.units import inch
import io

# Configuración de página de Streamlit
st.set_page_config(
    page_title="Plataforma de Expediente Clínico y Recetas Digitales",
    page_icon="🩺",
    layout="wide"
)

# --- 1. CONFIGURACIÓN DE BASE DE DATOS (SQLite) ---
DB_NAME = "recetario_medico.db"

def get_db_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Tabla de Médicos (Cumple Art 29 RIS y Art 83 LGS)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS medicos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre_completo TEXT NOT NULL,
        cedula_profesional TEXT UNIQUE NOT NULL,
        institucion_titulo TEXT NOT NULL,
        tiene_especialidad INTEGER DEFAULT 0,
        especialidad TEXT,
        cedula_especialidad TEXT,
        institucion_especialidad TEXT,
        domicilio_consultorio TEXT NOT NULL,
        telefono TEXT,
        correo TEXT,
        color_primario TEXT DEFAULT '#003366',
        color_secundario TEXT DEFAULT '#444444',
        logo_path TEXT DEFAULT 'consultorio_logo.png'
    )
    """)
    
    # Robustez: Verificar si las columnas de personalización de estilo existen (migración de DB en caliente)
    cursor.execute("PRAGMA table_info(medicos)")
    columns = [row[1] for row in cursor.fetchall()]
    if 'color_primario' not in columns:
        cursor.execute("ALTER TABLE medicos ADD COLUMN color_primario TEXT DEFAULT '#003366'")
    if 'color_secundario' not in columns:
        cursor.execute("ALTER TABLE medicos ADD COLUMN color_secundario TEXT DEFAULT '#444444'")
    if 'logo_path' not in columns:
        cursor.execute("ALTER TABLE medicos ADD COLUMN logo_path TEXT DEFAULT 'consultorio_logo.png'")
        
    # Tabla de Pacientes (Cumple Art 247 LGS - CURP)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS pacientes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre_completo TEXT NOT NULL,
        curp TEXT UNIQUE NOT NULL,
        fecha_nacimiento TEXT NOT NULL,
        sexo TEXT NOT NULL,
        telefono TEXT,
        correo TEXT
    )
    """)
    
    # Tabla de Recetas (Cumple Art 109 Bis LGS)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS recetas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        id_medico INTEGER NOT NULL,
        id_paciente INTEGER NOT NULL,
        fecha_emision TEXT NOT NULL,
        folio TEXT UNIQUE NOT NULL,
        FOREIGN KEY (id_medico) REFERENCES medicos (id),
        FOREIGN KEY (id_paciente) REFERENCES pacientes (id)
    )
    """)
    
    # Tabla de Detalles de Receta (Cumple Art 30 y 31 RIS)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS receta_detalles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        id_receta INTEGER NOT NULL,
        denominacion_generica TEXT NOT NULL,  -- Obligatorio por Ley
        denominacion_distintiva TEXT,         -- Opcional (Marca)
        presentacion TEXT NOT NULL,           -- Ej. Tabletas 500mg
        dosis TEXT NOT NULL,                  -- Ej. 1 tableta
        via_administracion TEXT NOT NULL,     -- Ej. Oral
        frecuencia TEXT NOT NULL,             -- Ej. Cada 8 horas
        duracion_tratamiento TEXT NOT NULL,   -- Ej. 7 días
        indicaciones_adicionales TEXT,
        FOREIGN KEY (id_receta) REFERENCES recetas (id)
    )
    """)
    
    # Tabla de Usuarios para Inicio de Sesión Seguro (Salud Digital Art 71 Septies LGS)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS usuarios (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        id_medico INTEGER NOT NULL,
        FOREIGN KEY (id_medico) REFERENCES medicos (id)
    )
    """)
    
    # Nueva Tabla de Consultas Clínicas (Expediente Clínico Electrónico - Art. 109 Bis y 71 Septies LGS)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS consultas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        id_medico INTEGER NOT NULL,
        id_paciente INTEGER NOT NULL,
        fecha_consulta TEXT NOT NULL,
        motivo_consulta TEXT NOT NULL,
        sintomas TEXT,
        peso REAL,
        talla REAL,
        presion_arterial TEXT,
        temperatura REAL,
        frecuencia_cardiaca INTEGER,
        diagnostico TEXT NOT NULL,
        plan_tratamiento TEXT,
        id_receta INTEGER,
        FOREIGN KEY (id_medico) REFERENCES medicos (id),
        FOREIGN KEY (id_paciente) REFERENCES pacientes (id),
        FOREIGN KEY (id_receta) REFERENCES recetas (id)
    )
    """)
    
    # Insertar médico de prueba si la tabla está vacía
    cursor.execute("SELECT COUNT(*) FROM medicos")
    if cursor.fetchone()[0] == 0:
        cursor.execute("""
        INSERT INTO medicos (
            nombre_completo, cedula_profesional, institucion_titulo, 
            tiene_especialidad, especialidad, cedula_especialidad, 
            institucion_especialidad, domicilio_consultorio, telefono, correo,
            color_primario, color_secundario, logo_path
        ) VALUES (
            'Dra. María Elisa Gómez Pérez', '12345678', 'Universidad Nacional Autónoma de México',
            1, 'Medicina Familiar', '98765432', 'Consejo Mexicano de Medicina Familiar',
            'Av. Insurgentes Sur 1458, Col. Del Valle, Benito Juárez, CDMX, CP 03100', '55-5555-5555', 'dra.elisa@mail.com',
            '#003366', '#444444', 'consultorio_logo.png'
        )
        """)
        id_medico = cursor.lastrowid
        
        # Insertar usuario por defecto asociado a este médico
        # Usuario: doctora / Contraseña: doctora123 (hashed con SHA-256)
        pw_plain = "doctora123"
        pw_hash = hashlib.sha256(pw_plain.encode('utf-8')).hexdigest()
        cursor.execute("""
        INSERT INTO usuarios (username, password_hash, id_medico)
        VALUES ('doctora', ?, ?)
        """, (pw_hash, id_medico))
        
    conn.commit()
    conn.close()

init_db()

# --- 2. FUNCIONES AUXILIARES Y DE AUTENTICACIÓN ---
def hash_password(password):
    return hashlib.sha256(password.encode('utf-8')).hexdigest()

def verify_login(username, password):
    conn = get_db_connection()
    pw_hash = hash_password(password)
    user = conn.execute("""
        SELECT u.id, u.username, u.id_medico, m.nombre_completo 
        FROM usuarios u
        JOIN medicos m ON u.id_medico = m.id
        WHERE u.username = ? AND u.password_hash = ?
    """, (username, pw_hash)).fetchone()
    conn.close()
    return user

def calcular_edad(fecha_nac_str):
    try:
        nac = datetime.datetime.strptime(fecha_nac_str, "%Y-%m-%d").date()
        hoy = datetime.date.today()
        edad = hoy.year - nac.year - ((hoy.month, hoy.day) < (nac.month, nac.day))
        return f"{edad} años"
    except Exception:
        return "No especificada"

def calcular_imc(peso, talla):
    if peso and talla and talla > 0:
        imc = peso / (talla ** 2)
        if imc < 18.5:
            clasif = "Bajo peso"
            color = "blue"
        elif 18.5 <= imc < 25:
            clasif = "Peso normal"
            color = "green"
        elif 25 <= imc < 30:
            clasif = "Sobrepeso"
            color = "orange"
        else:
            clasif = "Obesidad"
            color = "red"
        return imc, clasif, color
    return None, None, None

# --- 3. GENERADOR DE PDF (REPORTLAB CON LOGO, COLORES Y SELLO DIGITAL) ---
def generar_pdf_receta(medico, paciente, folio, fecha, medicamentos):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, 
        pagesize=letter,
        rightMargin=40, leftMargin=40, 
        topMargin=40, bottomMargin=40
    )
    
    styles = getSampleStyleSheet()
    
    # Colores personalizados cargados de la base de datos (con fallback seguro)
    col_primario = medico.get('color_primario', '#003366')
    col_secundario = medico.get('color_secundario', '#444444')
    
    # Estilos personalizados para el PDF
    style_titulo_doctor = ParagraphStyle(
        'DocTitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=15,
        leading=18,
        textColor=colors.HexColor(col_primario),
        alignment=0 # Alineado a la izquierda para acomodarse con el logo
    )
    
    style_subtitulo_doctor = ParagraphStyle(
        'DocSub',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9,
        leading=13,
        textColor=colors.HexColor(col_secundario),
        alignment=0 # Alineado a la izquierda
    )
    
    style_cuerpo = ParagraphStyle(
        'Body',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=10,
        leading=14,
        textColor=colors.black
    )
    
    style_medicamento_gen = ParagraphStyle(
        'MedGen',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=11,
        leading=15,
        textColor=colors.HexColor(col_primario)
    )
    
    style_medicamento_com = ParagraphStyle(
        'MedCom',
        parent=styles['Normal'],
        fontName='Helvetica-Oblique',
        fontSize=9,
        leading=13,
        textColor=colors.HexColor('#666666')
    )

    story = []
    
    # --- PROCESAMIENTO DEL LOGOTIPO ---
    logo_path = medico.get('logo_path', 'consultorio_logo.png')
    resolved_logo_path = None
    
    # Buscamos de forma robusta la imagen en múltiples directorios posibles
    if logo_path:
        for p in [logo_path, os.path.join('/workspace/artifacts', logo_path), os.path.join('.', logo_path)]:
            if os.path.exists(p):
                resolved_logo_path = p
                break

    header_text_story = []
    header_text_story.append(Paragraph(f"<b>{medico['nombre_completo'].upper()}</b>", style_titulo_doctor))
    
    if medico['tiene_especialidad'] and medico['especialidad']:
        especialidad_texto = f"Especialista en: {medico['especialidad']}<br/>Ced. Especialidad: {medico['cedula_especialidad']} por {medico['institucion_especialidad']}"
        header_text_story.append(Paragraph(especialidad_texto, style_subtitulo_doctor))
    else:
        header_text_story.append(Paragraph("Médico General", style_subtitulo_doctor))
        
    titulo_prof = f"Título expedido por: {medico['institucion_titulo']} | Cédula Profesional: {medico['cedula_profesional']}"
    header_text_story.append(Paragraph(titulo_prof, style_subtitulo_doctor))
    
    # Si existe el logotipo, creamos una tabla estructurada para el membrete
    if resolved_logo_path:
        try:
            # Creamos el elemento Image ajustado a 1.1 x 1.1 pulgadas
            logo_img = Image(resolved_logo_path, width=1.1*inch, height=1.1*inch)
            
            # Tabla: [Imagen_Logo, Textos_Médicos]
            header_table_data = [[logo_img, header_text_story]]
            header_table = Table(header_table_data, colWidths=[1.3*inch, 5.7*inch])
            header_table.setStyle(TableStyle([
                ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
                ('LEFTPADDING', (1,0), (1,0), 10),
                ('RIGHTPADDING', (0,0), (-1,-1), 0),
                ('BOTTOMPADDING', (0,0), (-1,-1), 0),
                ('TOPPADDING', (0,0), (-1,-1), 0),
            ]))
            story.append(header_table)
        except Exception:
            # Fallback seguro por si falla la carga de imagen por librerías del sistema
            story.extend(header_text_story)
    else:
        # Si no hay logotipo, usamos el texto de encabezado centrado clásico
        style_titulo_doctor.alignment = 1 # Centrado
        style_subtitulo_doctor.alignment = 1 # Centrado
        story.extend(header_text_story)
        
    story.append(Spacer(1, 10))
    story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor(col_primario), spaceAfter=15))
    
    # INFORMACIÓN DE LA CONSULTA (Paciente, Fecha, Folio)
    info_consulta_data = [\
        [
            Paragraph(f"<b>Paciente:</b> {paciente['nombre_completo']}", style_cuerpo),
            Paragraph(f"<b>Folio:</b> {folio}", style_cuerpo)
        ],
        [
            Paragraph(f"<b>CURP:</b> {paciente['curp']} | <b>Fecha de Nac.:</b> {paciente['fecha_nacimiento']}", style_cuerpo),
            Paragraph(f"<b>Fecha:</b> {fecha}", style_cuerpo)
        ]
    ]
    t_info = Table(info_consulta_data, colWidths=[4.0*inch, 3.0*inch])
    t_info.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ('TOPPADDING', (0,0), (-1,-1), 4),
    ]))
    story.append(t_info)
    story.append(Spacer(1, 10))
    story.append(HRFlowable(width="100%", thickness=0.8, color=colors.HexColor('#CCCCCC'), spaceAfter=15))
    
    # CUERPO DE LA RECETA - PRESCRIPCIÓN (Art 30 & 31 RIS)
    story.append(Paragraph("<b>Rx - PRESCRIPCIÓN</b>", ParagraphStyle('Rx', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=12, textColor=colors.HexColor(col_primario), spaceAfter=10)))
    story.append(Spacer(1, 5))
    
    for idx, med in enumerate(medicamentos, 1):
        # Denominación Genérica (Obligatoria por Ley)
        texto_med = f"<b>{idx}. {med['denominacion_generica']}</b>"
        # Denominación Distintiva (Opcional)
        if med['denominacion_distintiva']:
            texto_med += f" (sugerido: <i>{med['denominacion_distintiva']}</i>)"
        
        texto_med += f" - {med['presentacion']}"
        story.append(Paragraph(texto_med, style_medicamento_gen))
        
        # Instrucciones de uso
        texto_instrucciones = f"<b>Vía de administración:</b> {med['via_administracion']} | " \
                              f"<b>Dosis:</b> {med['dosis']} | " \
                              f"<b>Frecuencia:</b> {med['frecuencia']} | " \
                              f"<b>Duración:</b> {med['duracion_tratamiento']}"
        story.append(Paragraph(texto_instrucciones, style_cuerpo))
        
        if med['indicaciones_adicionales']:
            story.append(Paragraph(f"<i>Indicaciones adicionales: {med['indicaciones_adicionales']}</i>", style_medicamento_com))
            
        story.append(Spacer(1, 12))
        
    story.append(Spacer(1, 30))
    
    # PIE DE PÁGINA (Sello Digital de Validación y Dirección del Consultorio)
    story.append(Spacer(1, 20))
    
    # Bloque de validación de firma digital
    style_sello_digital = ParagraphStyle(
        'SelloDigital',
        parent=styles['Normal'],
        fontName='Helvetica-BoldOblique',
        fontSize=8,
        leading=11,
        textColor=colors.HexColor(col_primario),
        alignment=1 # Centrado
    )
    
    # Generar un token único de verificación digital (hash) de la receta
    token_verificacion = hashlib.sha256(f"{folio}-{medico['cedula_profesional']}".encode('utf-8')).hexdigest()[:16].upper()
    
    texto_firma_digital = f"🛡️ RECETA DIGITAL VALIDADA ELECTRÓNICAMENTE<br/>" \
                           f"Firmado digitalmente por: {medico['nombre_completo']} | Cédula Profesional: {medico['cedula_profesional']}<br/>" \
                           f"Código de Verificación de Acto Clínico: {token_verificacion}"
                           
    # Sello digital en una caja gris con el borde del color de la marca
    sello_table_data = [[Paragraph(texto_firma_digital, style_sello_digital)]]
    sello_table = Table(sello_table_data, colWidths=[6.8*inch])
    sello_table.setStyle(TableStyle([
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#F4F6F6')),
        ('BOX', (0,0), (-1,-1), 1, colors.HexColor(col_primario)),
        ('TOPPADDING', (0,0), (-1,-1), 8),
        ('BOTTOMPADDING', (0,0), (-1,-1), 8),
    ]))
    
    story.append(sello_table)
    story.append(Spacer(1, 15))
    
    # Dirección del consultorio obligatoria en papelería (Art. 83 LGS / 29 RIS)
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor('#CCCCCC'), spaceAfter=10))
    style_subtitulo_doctor_center = ParagraphStyle('CenterFooter', parent=style_subtitulo_doctor, alignment=1)
    direccion_texto = f"<b>Consultorio:</b> {medico['domicilio_consultorio']}<br/>" \
                      f"Teléfono: {medico['telefono']} | Correo Electrónico: {medico['correo']}"
    story.append(Paragraph(direccion_texto, style_subtitulo_doctor_center))
    
    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()

# --- 4. GESTIÓN DE SESIÓN Y LOGIN ---
if 'logged_in' not in st.session_state:
    st.session_state['logged_in'] = False
if 'user_info' not in st.session_state:
    st.session_state['user_info'] = None

if not st.session_state['logged_in']:
    # Formulario de inicio de sesión centrado
    st.markdown("<br><br>", unsafe_allow_html=True)
    col_l, col_center, col_r = st.columns([1, 2, 1])
    
    with col_center:
        st.markdown("<h2 style='text-align: center; color: #003366;'>🔐 Acceso al Recetario Seguro</h2>", unsafe_allow_html=True)
        st.markdown("<p style='text-align: center; color: gray;'>Salud Digital y Confidencialidad de Datos (Art. 71 Septies Ley General de Salud)</p>", unsafe_allow_html=True)
        
        with st.form("login_form"):
            username = st.text_input("Usuario", placeholder="Ingresa tu nombre de usuario")
            password = st.text_input("Contraseña", type="password", placeholder="Ingresa tu contraseña")
            submit_login = st.form_submit_button("Iniciar Sesión")
            
            if submit_login:
                if not username or not password:
                    st.error("Por favor, introduce tu usuario y contraseña.")
                else:
                    user = verify_login(username.strip(), password)
                    if user:
                        st.session_state['logged_in'] = True
                        st.session_state['user_info'] = dict(user)
                        st.success("¡Acceso concedido!")
                        st.rerun()
                    else:
                        st.error("Usuario o contraseña incorrectos.")
                        
        st.info("ℹ️ **Prototipo local:** El usuario predeterminado de tu esposa es **`doctora`** y la contraseña es **`doctora123`**. Ella podrá modificar estos datos dentro del sistema.")
else:
    # --- 5. INTERFAZ DE LA PLATAFORMA ---
    user_info = st.session_state['user_info']
    id_medico = user_info['id_medico']
    
    # Obtener datos actualizados del médico logueado
    conn = get_db_connection()
    medico_db = conn.execute("SELECT * FROM medicos WHERE id = ?", (id_medico,)).fetchone()
    medico = dict(medico_db) if medico_db else {}
    conn.close()

    # Sidebar de Navegación
    st.sidebar.markdown(f"<h3 style='color: {medico.get('color_primario', '#003366')};'>👩‍⚕️ Bienvenida, {medico.get('nombre_completo')}</h3>", unsafe_allow_html=True)
    st.sidebar.caption(f"Cédula: {medico.get('cedula_profesional')}")
    st.sidebar.divider()
    
    # Añadimos los flujos del Expediente Clínico de forma amigable
    menu = [
        "Nueva Consulta / Receta", 
        "Expediente Clínico", 
        "Administrar Pacientes", 
        "Historial de Recetas", 
        "Configuración Médica"
    ]
    choice = st.sidebar.selectbox("Navegación", menu)
    
    st.sidebar.divider()
    if st.sidebar.button("🚪 Cerrar Sesión"):
        st.session_state['logged_in'] = False
        st.session_state['user_info'] = None
        st.rerun()
        
    st.sidebar.caption("🩺 Plataforma de Expediente Clínico v5.0")

    # --- TAB: CONFIGURACIÓN MÉDICA ---
    if choice == "Configuración Médica":
        st.header("⚙️ Configuración del Perfil Médico")
        st.write("Mantén tus datos actualizados. La Ley General de Salud exige que tu cédula, universidad y dirección de consultorio estén visibles en toda receta.")
        
        tab_perfil, tab_seguridad, tab_estilo = st.tabs(["Perfil Profesional", "Seguridad de Acceso", "🎨 Estilo y Personalización"])
        
        with tab_perfil:
            with st.form("perfil_medico_form"):
                col1, col2 = st.columns(2)
                with col1:
                    nombre = st.text_input("Nombre Completo (con título, ej: Dra. María Gómez)", medico.get('nombre_completo'))
                    cedula = st.text_input("Cédula Profesional General", medico.get('cedula_profesional'))
                    institucion = st.text_input("Institución de Título (Universidad)", medico.get('institucion_titulo'))
                    tel = st.text_input("Teléfono del Consultorio", medico.get('telefono'))
                    correo = st.text_input("Correo de contacto", medico.get('correo'))
                with col2:
                    tiene_esp = st.checkbox("¿Cuenta con Especialidad?", value=bool(medico.get('tiene_especialidad')))
                    esp = st.text_input("Especialidad Médica", medico.get('especialidad') if medico.get('especialidad') else "")
                    cedula_esp = st.text_input("Cédula de Especialidad", medico.get('cedula_especialidad') if medico.get('cedula_especialidad') else "")
                    inst_esp = st.text_input("Institución de Especialidad", medico.get('institucion_especialidad') if medico.get('institucion_especialidad') else "")
                    domicilio = st.text_area("Domicilio Completo del Consultorio (Obligatorio)", medico.get('domicilio_consultorio'))
                    
                submit = st.form_submit_button("Guardar Cambios de Perfil")
                
                if submit:
                    if not nombre or not cedula or not institucion or not domicilio:
                        st.error("Por favor llena todos los campos obligatorios para cumplir con la normatividad.")
                    else:
                        conn = get_db_connection()
                        conn.execute("""
                        UPDATE medicos SET 
                            nombre_completo = ?, cedula_profesional = ?, institucion_titulo = ?,
                            tiene_especialidad = ?, especialidad = ?, cedula_especialidad = ?,
                            institucion_especialidad = ?, domicilio_consultorio = ?, telefono = ?, correo = ?
                        WHERE id = ?
                        """, (nombre, cedula, institucion, 1 if tiene_esp else 0, esp, cedula_esp, inst_esp, domicilio, tel, correo, id_medico))
                        conn.commit()
                        conn.close()
                        st.success("Perfil médico actualizado con éxito. Los datos se verán reflejados en las nuevas recetas.")
                        st.rerun()
                        
        with tab_seguridad:
            st.subheader("🔑 Cambiar Contraseña de Acceso")
            st.write("Protege el acceso a tus recetas y expedientes clínicos (Art. 71 Septies LGS).")
            with st.form("password_change_form"):
                current_pw = st.password_input("Contraseña Actual", type="password")
                new_pw = st.password_input("Nueva Contraseña", type="password")
                confirm_pw = st.password_input("Confirmar Nueva Contraseña", type="password")
                
                submit_pw = st.form_submit_button("Actualizar Contraseña")
                
                if submit_pw:
                    if not current_pw or not new_pw or not confirm_pw:
                        st.error("Todos los campos de contraseña son obligatorios.")
                    elif new_pw != confirm_pw:
                        st.error("La nueva contraseña y la confirmación no coinciden.")
                    else:
                        # Verificar contraseña actual
                        conn = get_db_connection()
                        current_hash = hash_password(current_pw)
                        user_db = conn.execute("SELECT * FROM usuarios WHERE id_medico = ? AND password_hash = ?", (id_medico, current_hash)).fetchone()
                        
                        if not user_db:
                            st.error("La contraseña actual es incorrecta.")
                            conn.close()
                        else:
                            new_hash = hash_password(new_pw)
                            conn.execute("UPDATE usuarios SET password_hash = ? WHERE id_medico = ?", (new_hash, id_medico))
                            conn.commit()
                            conn.close()
                            st.success("¡Tu contraseña ha sido actualizada con éxito!")
                            
        with tab_estilo:
            st.subheader("🎨 Personalización de Marca y Colores")
            st.write("Configura de manera amigable la identidad visual de las recetas impresas en PDF.")
            
            # Paletas predefinidas para facilitar la selección a la doctora
            paletas = {
                "Azul Clínico (Predeterminado)": ("#003366", "#444444"),
                "Verde Sanitario (Clásico)": ("#005B54", "#2E403F"),
                "Gris Elegante (Charcoal)": ("#2C3E50", "#5D6D7E"),
                "Rojo Salud (Cruz Roja)": ("#990000", "#501212")
            }
            
            current_primary = medico.get('color_primario', '#003366')
            current_secondary = medico.get('color_secundario', '#444444')
            
            # Detectar si los colores actuales coinciden con alguna paleta predefinida
            match_palette = "Personalizado"
            for name, colors_tup in paletas.items():
                if colors_tup[0].upper() == current_primary.upper() and colors_tup[1].upper() == current_secondary.upper():
                    match_palette = name
                    break
            
            select_paleta = st.selectbox(
                "Selecciona una paleta de colores predeterminada:",
                list(paletas.keys()) + ["Personalizado"],
                index=list(paletas.keys()).index(match_palette) if match_palette in paletas else len(paletas)
            )
            
            # Si eligen una predefinida, actualizamos las variables
            if select_paleta != "Personalizado":
                prim_col, sec_col = paletas[select_paleta]
            else:
                prim_col = current_primary
                sec_col = current_secondary
            
            col_c1, col_c2 = st.columns(2)
            with col_c1:
                color_p = st.color_picker("Color Primario (Títulos y Medicamentos):", value=prim_col)
            with col_c2:
                color_s = st.color_picker("Color Secundario (Subtítulos e Información):", value=sec_col)
            
            st.markdown("---")
            st.write("##### 🖼️ Logotipo de la Receta")
            
            # Buscar el logotipo de forma local
            logo_path_current = medico.get('logo_path', 'consultorio_logo.png')
            resolved_logo = None
            if logo_path_current:
                for p in [logo_path_current, os.path.join('/workspace/artifacts', logo_path_current), os.path.join('.', logo_path_current)]:
                    if os.path.exists(p):
                        resolved_logo = p
                        break
            
            if resolved_logo:
                st.image(resolved_logo, width=120, caption="Logotipo actual que aparecerá en tus recetas PDF")
            else:
                st.warning("⚠️ No se ha detectado el logotipo predeterminado. La receta se generará con un diseño elegante de solo texto.")
                
            uploaded_logo = st.file_uploader("Sube un nuevo logotipo personalizado (Formatos PNG o JPG recomendados de 1:1 ratio):", type=["png", "jpg", "jpeg"])
            
            col_btn1, col_btn2 = st.columns(2)
            with col_btn1:
                if st.button("💾 Guardar Cambios de Estilo", type="primary"):
                    new_logo_path = logo_path_current
                    if uploaded_logo is not None:
                        # Guardamos el logotipo subido localmente en la app
                        new_logo_path = "logo_personalizado.png"
                        with open(new_logo_path, "wb") as f:
                            f.write(uploaded_logo.getbuffer())
                    
                    conn = get_db_connection()
                    conn.execute("""
                        UPDATE medicos SET 
                            color_primario = ?, color_secundario = ?, logo_path = ?
                        WHERE id = ?
                    """, (color_p, color_s, new_logo_path, id_medico))
                    conn.commit()
                    conn.close()
                    st.success("¡Estilos visuales de tu receta actualizados con éxito!")
                    st.rerun()
            with col_btn2:
                if st.button("🔄 Restaurar Logo Predeterminado"):
                    conn = get_db_connection()
                    conn.execute("""
                        UPDATE medicos SET logo_path = 'consultorio_logo.png'
                        WHERE id = ?
                    """, (id_medico,))
                    conn.commit()
                    conn.close()
                    st.info("Logotipo predeterminado restaurado.")
                    st.rerun()

    # --- TAB: ADMINISTRAR PACIENTES ---
    elif choice == "Administrar Pacientes":
        st.header("👥 Gestión de Pacientes")
        
        tab1, tab2, tab3 = st.tabs(["Registrar Nuevo Paciente", "Ver Pacientes Registrados", "✏️ Modificar Paciente"])
        
        with tab1:
            st.subheader("Registrar Paciente")
            with st.form("paciente_form"):
                col1, col2 = st.columns(2)
                with col1:
                    p_nombre = st.text_input("Nombre Completo del Paciente")
                    p_curp = st.text_input("CURP (Clave Única de Registro de Población)")
                    p_nacimiento = st.date_input(
                        "Fecha de Nacimiento",
                        value=datetime.date(1990, 1, 1),
                        min_value=datetime.date(1900, 1, 1),
                        max_value=datetime.date.today()
                    ).strftime("%Y-%m-%d")
                with col2:
                    p_sexo = st.selectbox("Sexo al Nacer", ["M", "F", "Otro"])
                    p_tel = st.text_input("Teléfono del Paciente (Opcional)")
                    p_correo = st.text_input("Correo del Paciente (Opcional)")
                    
                p_submit = st.form_submit_button("Registrar Paciente")
                
                if p_submit:
                    if not p_nombre or not p_curp:
                        st.error("El nombre y la CURP son obligatorios.")
                    elif len(p_curp) != 18:
                        st.warning("Verifica la CURP ingresada. Generalmente consta de 18 caracteres.")
                    else:
                        try:
                            conn = get_db_connection()
                            conn.execute("""
                            INSERT INTO pacientes (nombre_completo, curp, fecha_nacimiento, sexo, telefono, correo)
                            VALUES (?, ?, ?, ?, ?, ?)
                            """, (p_nombre, p_curp.upper().strip(), p_nacimiento, p_sexo, p_tel, p_correo))
                            conn.commit()
                            conn.close()
                            st.success(f"Paciente '{p_nombre}' registrado correctamente.")
                        except sqlite3.IntegrityError:
                            st.error("Un paciente con esta CURP ya se encuentra registrado.")
                            
        with tab2:
            st.subheader("Directorio de Pacientes")
            conn = get_db_connection()
            pacientes_db = conn.execute("SELECT * FROM pacientes ORDER BY nombre_completo").fetchall()
            conn.close()
            
            if pacientes_db:
                for p in pacientes_db:
                    with st.expander(f"👤 {p['nombre_completo']} ({p['curp']})"):
                        st.write(f"**Fecha de Nacimiento:** {p['fecha_nacimiento']} ({calcular_edad(p['fecha_nacimiento'])})")
                        st.write(f"**Sexo:** {p['sexo']}")
                        st.write(f"**Teléfono:** {p['telefono'] if p['telefono'] else 'No registrado'}")
                        st.write(f"**Correo:** {p['correo'] if p['correo'] else 'No registrado'}")
            else:
                st.info("No hay pacientes registrados aún.")
                
        with tab3:
            st.subheader("Modificar Datos de Pacientes Registrados")
            conn = get_db_connection()
            p_list = conn.execute("SELECT id, nombre_completo, curp FROM pacientes ORDER BY nombre_completo").fetchall()
            conn.close()
            
            if not p_list:
                st.info("No hay pacientes registrados aún para modificar.")
            else:
                p_options = {f"{row['nombre_completo']} ({row['curp']})": row['id'] for row in p_list}
                p_select = st.selectbox("Selecciona el paciente a modificar:", list(p_options.keys()))
                id_p_mod = p_options[p_select]
                
                # Obtener datos del paciente seleccionado
                conn = get_db_connection()
                pac_data = conn.execute("SELECT * FROM pacientes WHERE id = ?", (id_p_mod,)).fetchone()
                conn.close()
                
                if pac_data:
                    # Formulario para editar
                    with st.form("edit_paciente_form"):
                        col1, col2 = st.columns(2)
                        with col1:
                            e_nombre = st.text_input("Nombre Completo del Paciente", value=pac_data['nombre_completo'])
                            e_curp = st.text_input("CURP (Clave Única de Registro de Población)", value=pac_data['curp'])
                            
                            # Parsear fecha de nacimiento anterior de forma robusta
                            try:
                                def_date = datetime.datetime.strptime(pac_data['fecha_nacimiento'], "%Y-%m-%d").date()
                            except Exception:
                                def_date = datetime.date(1990, 1, 1)
                                
                            e_nacimiento = st.date_input(
                                "Fecha de Nacimiento",
                                value=def_date,
                                min_value=datetime.date(1900, 1, 1),
                                max_value=datetime.date.today()
                            )
                        with col2:
                            e_sexo = st.selectbox("Sexo al Nacer", ["M", "F", "Otro"], index=["M", "F", "Otro"].index(pac_data['sexo']) if pac_data['sexo'] in ["M", "F", "Otro"] else 0)
                            e_tel = st.text_input("Teléfono del Paciente (Opcional)", value=pac_data['telefono'] if pac_data['telefono'] else "")
                            e_correo = st.text_input("Correo del Paciente (Opcional)", value=pac_data['correo'] if pac_data['correo'] else "")
                            
                        e_submit = st.form_submit_button("💾 Guardar Cambios del Paciente")
                        
                        if e_submit:
                            if not e_nombre or not e_curp:
                                st.error("El nombre y la CURP son obligatorios.")
                            elif len(e_curp) != 18:
                                st.warning("La CURP debe tener exactamente 18 caracteres.")
                            else:
                                try:
                                    conn = get_db_connection()
                                    conn.execute("""
                                        UPDATE pacientes SET
                                            nombre_completo = ?,
                                            curp = ?,
                                            fecha_nacimiento = ?,
                                            sexo = ?,
                                            telefono = ?,
                                            correo = ?
                                        WHERE id = ?
                                    """, (e_nombre, e_curp.upper().strip(), e_nacimiento.strftime("%Y-%m-%d"), e_sexo, e_tel, e_correo, id_p_mod))
                                    conn.commit()
                                    conn.close()
                                    st.success(f"¡Los datos de '{e_nombre}' se actualizaron con éxito!")
                                    st.rerun()
                                except sqlite3.IntegrityError:
                                    st.error("Error de integridad: La CURP ingresada ya le pertenece a otro paciente registrado.")

    # --- NUEVO TAB: NUEVA CONSULTA / RECETA ---
    elif choice == "Nueva Consulta / Receta":
        st.header("🩺 Registro de Consulta Clínica y Recetario")
        st.write("La Ley General de Salud exige el correcto registro de cada acto médico (Art. 71 Septies y 109 Bis).")
        
        conn = get_db_connection()
        pacientes_db = conn.execute("SELECT id, nombre_completo, curp, fecha_nacimiento FROM pacientes ORDER BY nombre_completo").fetchall()
        conn.close()
        
        if not pacientes_db:
            st.warning("⚠️ Primero debes registrar al menos un paciente en la pestaña 'Administrar Pacientes'.")
        else:
            pacientes_dict = {f"{p['nombre_completo']} ({p['curp']})": p['id'] for p in pacientes_db}
            paciente_seleccionado = st.selectbox("Selecciona al Paciente:", list(pacientes_dict.keys()))
            id_paciente = pacientes_dict[paciente_seleccionado]
            
            # Obtener datos de nacimiento del paciente seleccionado para mostrar la edad en tiempo real
            fecha_nac_sel = [p['fecha_nacimiento'] for p in pacientes_db if p['id'] == id_paciente][0]
            st.caption(f"**Paciente seleccionado:** {paciente_seleccionado} | **Edad:** {calcular_edad(fecha_nac_sel)}")
            
            st.divider()
            
            col_clinica, col_signos = st.columns([3, 2])
            
            with col_clinica:
                st.subheader("📋 Nota Clínica (Subjetivo y Diagnóstico)")
                motivo = st.text_area("Motivo de la Consulta (Obligatorio)*", placeholder="Ej. Paciente acude por dolor de garganta y fiebre de 2 días de evolución.")
                sintomas = st.text_area("Síntomas y Evolución", placeholder="Refiere cefalea leve, odinofagia intensa, tos seca esporádica. Niega disnea.")
                diagnostico = st.text_input("Diagnóstico Clínico (Obligatorio)*", placeholder="Ej. Faringoamigdalitis aguda bacteriana")
                plan = st.text_area("Plan de Tratamiento / Recomendaciones Generales", placeholder="Ej. Reposo por 3 días, abundante hidratación, gárgaras de agua tibia con sal, evitar cambios bruscos de temperatura.")
                
            with col_signos:
                st.subheader("📊 Exploración Física y Signos Vitales")
                peso = st.number_input("Peso (kg)", min_value=0.0, max_value=250.0, value=70.0, step=0.1)
                talla = st.number_input("Talla (m)", min_value=0.0, max_value=2.50, value=1.70, step=0.01)
                
                # Calcular IMC en vivo
                imc, clasif, color_imc = calcular_imc(peso, talla)
                if imc:
                    st.markdown(f"**IMC:** `{imc:.2f}` (<span style='color:{color_imc}; font-weight:bold;'>{clasif}</span>)", unsafe_allow_html=True)
                
                presion = st.text_input("Presión Arterial (mmHg)", placeholder="Ej. 120/80")
                temperatura = st.number_input("Temperatura (°C)", min_value=30.0, max_value=45.0, value=36.5, step=0.1)
                frecuencia = st.number_input("Frecuencia Cardíaca (lpm)", min_value=0, max_value=200, value=75, step=1)
                
            st.divider()
            
            # --- SECCIÓN: RECETA VINCULADA ---
            generar_receta = st.checkbox("➕ Generar Receta Médica asociada a esta consulta")
            
            if generar_receta:
                st.subheader("💊 Prescribir Medicamentos")
                st.info("⚠️ La legislación exige recetar usando la **Denominación Genérica** (Fórmula). La marca es sugerida y opcional (Art. 31 RIS).")
                
                if 'medicamentos_receta' not in st.session_state:
                    st.session_state['medicamentos_receta'] = []
                    
                with st.form("med_form", clear_on_submit=True):
                    col_med1, col_med2 = st.columns(2)
                    with col_med1:
                        m_generico = st.text_input("Denominación Genérica (Obligatorio)*", placeholder="Ej. Paracetamol, Amoxicilina")
                        m_distintiva = st.text_input("Denominación Distintiva (Marca opcional)", placeholder="Ej. Tempra, Amoxil")
                        m_presentacion = st.text_input("Presentación (Concentración/Forma)*", placeholder="Ej. Tabletas de 500 mg, Suspensión 250mg/5ml")
                        m_dosis = st.text_input("Dosis / Cantidad*", placeholder="Ej. 1 tableta, 5 ml")
                    with col_med2:
                        m_via = st.selectbox("Vía de Administración*", ["Oral", "Intramuscular", "Intravenosa", "Oftálmica", "Nasal", "Cutánea", "Sublingual", "Inhalatoria"])
                        m_frecuencia = st.text_input("Frecuencia*", placeholder="Ej. Cada 8 horas, Cada 24 horas")
                        m_duracion = st.text_input("Duración del Tratamiento*", placeholder="Ej. 7 días, 5 días")
                        m_adicional = st.text_input("Indicaciones Adicionales", placeholder="Ej. Tomar después de alimentos")
                        
                    add_med = st.form_submit_button("➕ Agregar Medicamento a la Receta")
                    
                    if add_med:
                        if not m_generico or not m_presentacion or not m_dosis or not m_frecuencia or not m_duracion:
                            st.error("Todos los campos con asterisco (*) son obligatorios por ley.")
                        else:
                            st.session_state['medicamentos_receta'].append({
                                'denominacion_generica': m_generico.strip(),
                                'denominacion_distintiva': m_distintiva.strip() if m_distintiva else None,
                                'presentacion': m_presentacion.strip(),
                                'dosis': m_dosis.strip(),
                                'via_administracion': m_via,
                                'frecuencia': m_frecuencia.strip(),
                                'duracion_tratamiento': m_duracion.strip(),
                                'indicaciones_adicionales': m_adicional.strip() if m_adicional else None
                            })
                            st.success(f"Se agregó '{m_generico}' a la receta actual.")
                            st.rerun()
                
                # Mostrar medicamentos en la receta actual
                if st.session_state['medicamentos_receta']:
                    st.write("##### Lista de Medicamentos Agregados:")
                    for i, med in enumerate(st.session_state['medicamentos_receta'], 1):
                        marca = f" ({med['denominacion_distintiva']})" if med['denominacion_distintiva'] else ""
                        st.markdown(f"**{i}. {med['denominacion_generica']}{marca}** - {med['presentacion']}")
                        st.caption(f"Dosis: {med['dosis']} | Vía: {med['via_administracion']} | Frecuencia: {med['frecuencia']} | Duración: {med['duracion_tratamiento']}")
                    
                    if st.button("❌ Vaciar Lista de Medicamentos"):
                        st.session_state['medicamentos_receta'] = []
                        st.rerun()
            
            # --- GUARDAR TODO ---
            st.divider()
            
            btn_guardar = st.button("💾 Guardar Consulta y Cerrar Expediente", type="primary")
            
            if btn_guardar:
                if not motivo or not diagnostico:
                    st.error("Por favor completa los campos obligatorios de la Nota Clínica (Motivo y Diagnóstico).")
                elif generar_receta and not st.session_state['medicamentos_receta']:
                    st.error("Activaste la opción de generar receta, pero no has agregado ningún medicamento.")
                else:
                    conn = get_db_connection()
                    cursor = conn.cursor()
                    fecha_hoy = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
                    id_receta = None
                    
                    # 1. Si lleva receta, la registramos primero
                    if generar_receta and st.session_state['medicamentos_receta']:
                        # Generar Folio Único
                        random_suffix = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
                        folio = f"REC-{datetime.datetime.now().strftime('%Y%m%d')}-{random_suffix}"
                        
                        cursor.execute("""
                        INSERT INTO recetas (id_medico, id_paciente, fecha_emision, folio)
                        VALUES (?, ?, ?, ?)
                        """, (id_medico, id_paciente, fecha_hoy, folio))
                        id_receta = cursor.lastrowid
                        
                        # Insertar detalles
                        for med in st.session_state['medicamentos_receta']:
                            cursor.execute("""
                            INSERT INTO receta_detalles (
                                id_receta, denominacion_generica, denominacion_distintiva,
                                presentacion, dosis, via_administracion, frecuencia, 
                                duracion_tratamiento, indicaciones_adicionales
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """, (
                                id_receta, med['denominacion_generica'], med['denominacion_distintiva'],
                                med['presentacion'], med['dosis'], med['via_administracion'],
                                med['frecuencia'], med['duracion_tratamiento'], med['indicaciones_adicionales']
                            ))
                    
                    # 2. Insertar Consulta
                    cursor.execute("""
                    INSERT INTO consultas (
                        id_medico, id_paciente, fecha_consulta, motivo_consulta, sintomas,
                        peso, talla, presion_arterial, temperatura, frecuencia_cardiaca,
                        diagnostico, plan_tratamiento, id_receta
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        id_medico, id_paciente, fecha_hoy, motivo, sintomas,
                        peso, talla, presion, temperatura, frecuencia,
                        diagnostico, plan, id_receta
                    ))
                    
                    conn.commit()
                    conn.close()
                    
                    st.success("¡Consulta médica guardada de manera exitosa en el expediente clínico del paciente!")
                    
                    if id_receta:
                        st.balloons()
                        st.success(f"Receta emitida con Folio: {folio}. Puedes consultarla en la sección 'Expediente Clínico' o 'Historial de Recetas' para descargar el PDF.")
                    
                    st.session_state['medicamentos_receta'] = [] # Limpiar receta actual
                    
                    # Pequeña pausa y refrescar
                    import time
                    st.info("Refrescando sistema...")
                    time.sleep(1.5)
                    st.rerun()

    # --- TAB: EXPEDIENTE CLÍNICO COMPLETO ---
    elif choice == "Expediente Clínico":
        st.header("🗂️ Expediente Clínico de Pacientes (Historial de Consultas)")
        st.write("Consulta y audita el historial clínico completo del paciente, sus signos vitales históricos y tratamientos prescritos.")
        
        conn = get_db_connection()
        pacientes_db = conn.execute("SELECT id, nombre_completo, curp, fecha_nacimiento, sexo, telefono, correo FROM pacientes ORDER BY nombre_completo").fetchall()
        conn.close()
        
        if not pacientes_db:
            st.info("No hay pacientes registrados en el sistema aún.")
        else:
            pacientes_dict = {f"{p['nombre_completo']} ({p['curp']})": p['id'] for p in pacientes_db}
            paciente_seleccionado = st.selectbox("Selecciona un Paciente para ver su Expediente:", list(pacientes_dict.keys()))
            id_paciente = pacientes_dict[paciente_seleccionado]
            
            # Obtener datos del paciente
            paciente = next(dict(p) for p in pacientes_db if p['id'] == id_paciente)
            
            # Mostrar Resumen Ficha Identificación
            col_ficha1, col_ficha2 = st.columns(2)
            with col_ficha1:
                st.markdown("#### 👤 Ficha de Identificación del Paciente")
                st.write(f"**Nombre:** {paciente['nombre_completo']}")
                st.write(f"**CURP:** {paciente['curp']}")
                st.write(f"**Edad:** {calcular_edad(paciente['fecha_nacimiento'])} ({paciente['fecha_nacimiento']})")
            with col_ficha2:
                st.write(f"**Género:** {paciente['sexo']}")
                st.write(f"**Teléfono:** {paciente['telefono'] if paciente['telefono'] else 'No registrado'}")
                st.write(f"**Correo Electrónico:** {paciente['correo'] if paciente['correo'] else 'No registrado'}")
                
            st.divider()
            
            # Obtener todas las consultas de este paciente
            conn = get_db_connection()
            consultas_db = conn.execute("""
                SELECT * FROM consultas 
                WHERE id_paciente = ? AND id_medico = ?
                ORDER BY id DESC
            """, (id_paciente, id_medico)).fetchall()
            conn.close()
            
            if not consultas_db:
                st.info("Este paciente no cuenta con consultas médicas registradas aún.")
            else:
                st.markdown(f"### 🗄️ Historial de Consultas Médicas ({len(consultas_db)} registradas)")
                
                for cons in consultas_db:
                    fecha_c = cons['fecha_consulta']
                    diag_c = cons['diagnostico']
                    
                    with st.expander(f"📅 {fecha_c} - Diagnóstico: {diag_c}"):
                        col_cons1, col_cons2 = st.columns([3, 2])
                        
                        with col_cons1:
                            st.write(f"**Motivo de Consulta:** {cons['motivo_consulta']}")
                            if cons['sintomas']:
                                st.write(f"**Sintomatología:** {cons['sintomas']}")
                            st.write(f"**Impresión Diagnóstica:** `{diag_c}`")
                            if cons['plan_tratamiento']:
                                st.write(f"**Plan de Tratamiento / Indicaciones:**")
                                st.info(cons['plan_tratamiento'])
                                
                        with col_cons2:
                            st.markdown("**💡 Exploración Física y Vitales:**")
                            st.write(f"- **Peso:** {cons['peso']} kg  |  **Talla:** {cons['talla']} m")
                            
                            # Recalcular IMC histórico
                            p_h = cons['peso']
                            t_h = cons['talla']
                            imc_h, clas_h, color_h = calcular_imc(p_h, t_h)
                            if imc_h:
                                st.markdown(f"- **IMC:** `{imc_h:.2f}` (<span style='color:{color_h}; font-weight:bold;'>{clas_h}</span>)", unsafe_allow_html=True)
                                
                            st.write(f"- **Presión Arterial:** {cons['presion_arterial'] if cons['presion_arterial'] else 'N/E'}")
                            st.write(f"- **Temperatura:** {cons['temperatura']} °C")
                            st.write(f"- **Frecuencia Cardíaca:** {cons['frecuencia_cardiaca']} lpm")
                            
                        # Si la consulta tiene una receta asociada, permitir descargarla
                        if cons['id_receta']:
                            st.divider()
                            st.markdown("##### 💊 Receta Médica Emitida en esta Consulta")
                            
                            conn = get_db_connection()
                            receta_db = conn.execute("SELECT * FROM recetas WHERE id = ?", (cons['id_receta'],)).fetchone()
                            receta = dict(receta_db) if receta_db else {}
                            
                            medicamentos_rec = conn.execute("SELECT * FROM receta_detalles WHERE id_receta = ?", (cons['id_receta'],)).fetchall()
                            conn.close()
                            
                            if receta:
                                st.write(f"**Folio de Receta:** `{receta['folio']}`")
                                meds_list = []
                                for idx, med in enumerate(medicamentos_rec, 1):
                                    med_dict = dict(med)
                                    meds_list.append(med_dict)
                                    marca = f" ({med['denominacion_distintiva']})" if med['denominacion_distintiva'] else ""
                                    st.write(f"*{idx}. {med['denominacion_generica']}{marca}* - {med['presentacion']} | Dosis: {med['dosis']} | Vía: {med['via_administracion']} | Frecuencia: {med['frecuencia']} | Duración: {med['duracion_tratamiento']}")
                                    
                                # Botón de descarga PDF
                                pdf_data = generar_pdf_receta(medico, paciente, receta['folio'], receta['fecha_emision'], meds_list)
                                st.download_button(
                                    label=f"📥 Descargar Receta {receta['folio']} (PDF)",
                                    data=pdf_data,
                                    file_name=f"Receta_{receta['folio']}.pdf",
                                    mime="application/pdf",
                                    key=f"dl_exp_{cons['id_receta']}"
                                )

    # --- TAB: HISTORIAL DE RECETAS ---
    elif choice == "Historial de Recetas":
        st.header("🗄️ Historial Clínico de Recetas")
        st.write("De acuerdo con el Art. 109 Bis de la Ley General de Salud, los registros clínicos electrónicos deben estar disponibles para consulta.")
        
        conn = get_db_connection()
        recetas_db = conn.execute("""
        SELECT r.id, r.folio, r.fecha_emision, p.nombre_completo as paciente_nombre, p.curp as paciente_curp
        FROM recetas r
        JOIN pacientes p ON r.id_paciente = p.id
        WHERE r.id_medico = ?
        ORDER BY r.id DESC
        """, (id_medico,)).fetchall()
        conn.close()
        
        if not recetas_db:
            st.info("No hay recetas registradas en el historial.")
        else:
            for rec in recetas_db:
                with st.expander(f"📄 Folio: {rec['folio']} - Paciente: {rec['paciente_nombre']} ({rec['fecha_emision']})"):
                    conn = get_db_connection()
                    paciente = dict(conn.execute("SELECT * FROM pacientes WHERE curp = ?", (rec['paciente_curp'],)).fetchone())
                    medicamentos_rec = conn.execute("SELECT * FROM receta_detalles WHERE id_receta = ?", (rec['id'],)).fetchall()
                    conn.close()
                    
                    # Mostrar detalles
                    st.write(f"**Paciente:** {rec['paciente_nombre']} | **CURP:** {rec['paciente_curp']}")
                    st.write(f"**Fecha de Emisión:** {rec['fecha_emision']}")
                    st.markdown("---")
                    
                    meds_list = []
                    for i, med in enumerate(medicamentos_rec, 1):
                        med_dict = dict(med)
                        meds_list.append(med_dict)
                        marca = f" ({med['denominacion_distintiva']})" if med['denominacion_distintiva'] else ""
                        st.write(f"**{i}. {med['denominacion_generica']}{marca}** - {med['presentacion']}")
                        st.write(f"  * Dosis: {med['dosis']} | Vía: {med['via_administracion']} | Frecuencia: {med['frecuencia']} | Duración: {med['duracion_tratamiento']}")
                        if med['indicaciones_adicionales']:
                            st.write(f"  * _Indicaciones adicionales: {med['indicaciones_adicionales']}_")
                    
                    st.markdown("---")
                    # Botón de Descarga PDF generado al vuelo
                    pdf_data = generar_pdf_receta(medico, paciente, rec['folio'], rec['fecha_emision'], meds_list)
                    st.download_button(
                        label="📥 Descargar Receta en PDF",
                        data=pdf_data,
                        file_name=f"Receta_{rec['folio']}.pdf",
                        mime="application/pdf",
                        key=f"dl_{rec['id']}"
                    )
