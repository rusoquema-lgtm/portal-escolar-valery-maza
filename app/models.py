from datetime import datetime
from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship
from .database import Base


class ConfiguracionCentro(Base):
    __tablename__ = "configuracion_centro"

    id = Column(Integer, primary_key=True, index=True)
    nombre_escuela = Column(String(160), nullable=False, default="U.E Rafael Valery Maza")
    codigo_dea = Column(String(40), nullable=True)
    ubicación = Column(String(160), nullable=True)


class AnoEscolar(Base):
    __tablename__ = "anos_escolares"

    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(25), unique=True, nullable=False)
    activo = Column(Boolean, default=True)
    cerrado = Column(Boolean, default=False)


class Usuario(Base):
    __tablename__ = "usuarios"

    id = Column(Integer, primary_key=True, index=True)
    cedula = Column(String(20), unique=True, index=True, nullable=False)
    nombre_completo = Column(String(120), nullable=False)
    password_hash = Column(String(255), nullable=False)
    rol = Column(String(20), nullable=False)
    activo = Column(Boolean, default=True)


class AsignacionDocente(Base):
    __tablename__ = "asignaciones_docentes"

    id = Column(Integer, primary_key=True, index=True)
    ano_escolar_id = Column(Integer, ForeignKey("anos_escolares.id"), nullable=False)
    docente_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    asignatura = Column(String(80), nullable=False)
    grado_ano = Column(String(40), nullable=False)
    seccion = Column(String(20), nullable=False)

    ano_escolar = relationship("AnoEscolar")
    docente = relationship("Usuario")


class Estudiante(Base):
    __tablename__ = "estudiantes"

    id = Column(Integer, primary_key=True, index=True)
    cedula_escolar = Column(String(30), unique=True, index=True, nullable=False)
    nombres = Column(String(100), nullable=False)
    apellidos = Column(String(100), nullable=False)
    sexo = Column(String(15), nullable=True)
    nombre_madre_padre = Column(String(140), nullable=True)
    representante_legal = Column(String(160), nullable=True)
    numero_contacto = Column(String(40), nullable=True)
    correo_personal = Column(String(140), nullable=True)
    alergias = Column(Text, nullable=True)
    direccion = Column(String(220), nullable=True)
    foto_filename = Column(String(180), nullable=True)
    representante_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)

    representante = relationship("Usuario")


class MatriculaAnual(Base):
    __tablename__ = "matriculas_anuales"

    id = Column(Integer, primary_key=True, index=True)
    estudiante_id = Column(Integer, ForeignKey("estudiantes.id"), nullable=False)
    ano_escolar_id = Column(Integer, ForeignKey("anos_escolares.id"), nullable=False)
    grado_ano = Column(String(40), nullable=False)
    seccion = Column(String(20), nullable=False)
    estatus_cierre = Column(String(30), default="en_curso")
    promedio_final = Column(Float, nullable=True)

    estudiante = relationship("Estudiante")
    ano_escolar = relationship("AnoEscolar")


class Calificacion(Base):
    __tablename__ = "calificaciones"

    id = Column(Integer, primary_key=True, index=True)
    matricula_id = Column(Integer, ForeignKey("matriculas_anuales.id"), nullable=False)
    docente_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    asignatura = Column(String(80), nullable=False)
    lapso = Column(String(25), nullable=False)
    nota_20 = Column(Float, nullable=False)


class Asistencia(Base):
    __tablename__ = "asistencias"

    id = Column(Integer, primary_key=True, index=True)
    matricula_id = Column(Integer, ForeignKey("matriculas_anuales.id"), nullable=False)
    docente_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    fecha = Column(String(20), nullable=False)
    estado = Column(String(20), nullable=False)
    motivo_justificacion = Column(Text, nullable=True)
    estado_justificacion = Column(String(25), default="Sin justificar")
    revisado_por_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)

    matrícula = relationship("MatriculaAnual")


class ParteDisciplinario(Base):
    __tablename__ = "partes_disciplinarios"

    id = Column(Integer, primary_key=True, index=True)
    matricula_id = Column(Integer, ForeignKey("matriculas_anuales.id"), nullable=False)
    reportado_por_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    gravedad = Column(String(20), nullable=False)
    descripcion = Column(Text, nullable=False)
    medida_pedagogica = Column(Text, nullable=False)
    fecha = Column(DateTime, default=datetime.utcnow)


class HorarioClase(Base):
    __tablename__ = "horarios_clases"

    id = Column(Integer, primary_key=True, index=True)
    ano_escolar_id = Column(Integer, ForeignKey("anos_escolares.id"), nullable=False)
    grado_ano = Column(String(40), nullable=False)
    seccion = Column(String(20), nullable=False)
    dia_semana = Column(String(15), nullable=False)
    bloque_hora = Column(String(25), nullable=False)
    asignatura = Column(String(80), nullable=False)
    aula = Column(String(30), nullable=True)

    ano_escolar = relationship("AnoEscolar")


class AvisoCentro(Base):
    __tablename__ = "avisos_centro"

    id = Column(Integer, primary_key=True, index=True)
    ano_escolar_id = Column(Integer, ForeignKey("anos_escolares.id"), nullable=True)
    autor_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    titulo = Column(String(160), nullable=False)
    mensaje = Column(Text, nullable=False)
    dirigido_a = Column(String(40), default="Todos")
    fecha_creacion = Column(DateTime, default=datetime.utcnow)

    autor = relationship("Usuario")
