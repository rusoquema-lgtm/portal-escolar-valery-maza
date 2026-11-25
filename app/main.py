from collections import defaultdict
from pathlib import Path
from uuid import uuid4
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from .auth import crear_token, exigir_roles, hash_password, usuario_actual, verify_password
from .database import Base, SessionLocal, engine, get_db
from .models import (
    AnoEscolar,
    AsignacionDocente,
    Asistencia,
    AvisoCentro,
    Calificacion,
    ConfiguracionCentro,
    Estudiante,
    HorarioClase,
    MatriculaAnual,
    ParteDisciplinario,
    Usuario,
)

Base.metadata.create_all(bind=engine)

FOTOS_DIR = Path("app/static/fotos_alumnos")
FOTOS_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Portal Educativo â€” U.E Rafael Valery Maza")
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

LAPSOS_ORDEN = ["1er Momento", "2do Momento", "3er Momento"]
DIAS_SEMANA = ["Lunes", "Martes", "MiÃ©rcoles", "Jueves", "Viernes"]
BLOQUES_BASE = [
    "12:15 PM - 01:35 PM",
    "01:35 PM - 02:50 PM",
    "02:50 PM - 04:10 PM",
    "04:10 PM - 05:20 PM",
]
CURSOS_BASE = [
    ("1er AÃ±o", "A"),
    ("1er AÃ±o", "B"),
    ("1er AÃ±o", "C"),
    ("2do AÃ±o", "A"),
    ("2do AÃ±o", "B"),
    ("2do AÃ±o", "C"),
    ("2do AÃ±o", "D"),
    ("3er AÃ±o", "A"),
    ("3er AÃ±o", "B"),
    ("3er AÃ±o", "C"),
    ("3er AÃ±o", "D"),
    ("4to AÃ±o", "A"),
    ("4to AÃ±o", "B"),
    ("4to AÃ±o", "C"),
]
ASIGNATURAS_BASE = ['CASTELLANO', 'MATEMÃ\x81TICAS', 'CIENCIAS NATURALES', 'GHC: GEOGRAFÃ\x8dA E HISTORIA', 'QUÃ\x8dMICA', 'FÃ\x8dSICA', 'ARTE Y PATRIMONIO', 'EDUCACIÃ“N FÃ\x8dSICA', 'INGLÃ‰S', 'ORIENTACIÓN', 'GCRP', 'FSN', 'BIOLOGÍA']

NOMBRE_ESCUELA_DEFECTO = "U.E Rafael Valery Maza"
UBICACION_ESCUELA_DEFECTO = "Pedregales, Estado Nueva Esparta, Venezuela"


def obtener_o_crear_centro(db: Session) -> ConfiguracionCentro:
    centro = db.query(ConfiguracionCentro).first()
    if not centro:
        centro = ConfiguracionCentro(
            nombre_escuela=NOMBRE_ESCUELA_DEFECTO,
            codigo_dea="",
            ubicacion=UBICACION_ESCUELA_DEFECTO,
        )
        db.add(centro)
        db.commit()
        db.refresh(centro)
    else:
        actualizado = False
        if not centro.nombre_escuela or centro.nombre_escuela == "Unidad Educativa Nacional":
            centro.nombre_escuela = NOMBRE_ESCUELA_DEFECTO
            actualizado = True
        if not centro.ubicacion:
            centro.ubicacion = UBICACION_ESCUELA_DEFECTO
            actualizado = True
        if actualizado:
            db.commit()
            db.refresh(centro)
    return centro


@app.on_event("startup")
def datos_iniciales():
    db = SessionLocal()
    try:
        obtener_o_crear_centro(db)
        if not db.query(Usuario).filter(Usuario.cedula == "01663212J").first():
            db.add(
                Usuario(
                    cedula="01663212J",
                    nombre_completo="Aomar Alfonso",
                    password_hash=hash_password("admin123"),
                    rol="director",
                )
            )
        if not db.query(AnoEscolar).filter(AnoEscolar.nombre == "2026-2027").first():
            db.add(AnoEscolar(nombre="2026-2027", activo=True, cerrado=False))
        db.commit()
    finally:
        db.close()


def calcular_boletin_matricula(db: Session, matricula_id: int):
    notas = db.query(Calificacion).filter(Calificacion.matricula_id == matricula_id).all()
    por_materia = defaultdict(list)
    for n in notas:
        por_materia[n.asignatura].append(n.nota_20)

    resumen_materias = []
    definitivas = []
    reprobadas = 0

    for materia, lista_notas in por_materia.items():
        definitiva = round(sum(lista_notas) / len(lista_notas), 2)
        definitivas.append(definitiva)
        aprobada = definitiva >= 10.0
        if not aprobada:
            reprobadas += 1
        resumen_materias.append(
            {
                "asignatura": materia,
                "notas": lista_notas,
                "definitiva": definitiva,
                "estado": "Aprobada" if aprobada else "RevisiÃ³n / Aplazada",
            }
        )

    promedio_general = round(sum(definitivas) / len(definitivas), 2) if definitivas else None
    if promedio_general is None:
        condicion = "Sin calificaciones"
    elif reprobadas == 0 and promedio_general >= 10.0:
        condicion = "Promovido / Aprobado"
    elif reprobadas <= 2:
        condicion = "RevisiÃ³n / Materia Pendiente"
    else:
        condicion = "Repitiente"

    return {
        "materias": resumen_materias,
        "promedio_general": promedio_general,
        "condicion": condicion,
    }


def construir_matriz_cuaderno(matriculas, calificaciones, asignaciones_permitidas=None):
    notas_por_mat = defaultdict(list)
    for c in calificaciones:
        notas_por_mat[c.matricula_id].append(c)

    filas = []
    for m in matriculas:
        curso_clave = (m.grado_ano.strip().lower(), m.seccion.strip().lower())
        lista_c = notas_por_mat.get(m.id, [])

        if asignaciones_permitidas is not None:
            materias_mat = [
                a.asignatura.strip()
                for a in asignaciones_permitidas
                if (a.grado_ano.strip().lower(), a.seccion.strip().lower()) == curso_clave
            ]
            if not materias_mat:
                continue
            asignaturas_unicas = sorted(set(materias_mat) | {c.asignatura for c in lista_c if c.asignatura.strip() in set(materias_mat)})
        else:
            asignaturas_unicas = sorted({c.asignatura for c in lista_c})

        if not asignaturas_unicas:
            filas.append(
                {
                    "matricula": m,
                    "estudiante": m.estudiante,
                    "asignatura": "â€”",
                    "m1": None,
                    "m2": None,
                    "m3": None,
                    "definitiva": None,
                    "estado": "Pendiente",
                }
            )
            continue

        for asig in asignaturas_unicas:
            agrupado = defaultdict(list)
            for c in lista_c:
                if c.asignatura.strip().lower() == asig.strip().lower():
                    agrupado[c.lapso].append(c.nota_20)

            vals_lapsos = {}
            for lap in LAPSOS_ORDEN:
                nums = agrupado.get(lap, [])
                vals_lapsos[lap] = round(sum(nums) / len(nums), 2) if nums else None

            presentes = [v for v in vals_lapsos.values() if v is not None]
            definitiva = round(sum(presentes) / len(presentes), 2) if presentes else None
            estado = (
                "Pendiente"
                if definitiva is None
                else ("Aprobado" if definitiva >= 10.0 else "RevisiÃ³n")
            )

            filas.append(
                {
                    "matricula": m,
                    "estudiante": m.estudiante,
                    "asignatura": asig,
                    "m1": vals_lapsos["1er Momento"],
                    "m2": vals_lapsos["2do Momento"],
                    "m3": vals_lapsos["3er Momento"],
                    "definitiva": definitiva,
                    "estado": estado,
                }
            )
    return filas


def construir_rejilla_horario(horarios):
    mapa = {}
    bloques_ordenados = list(BLOQUES_BASE)
    for h in horarios:
        if h.bloque_hora not in bloques_ordenados:
            bloques_ordenados.append(h.bloque_hora)
        mapa[(h.bloque_hora, h.dia_semana)] = h

    rejilla = []
    for bloque in bloques_ordenados:
        fila = {"bloque": bloque, "dias": []}
        for dia in DIAS_SEMANA:
            fila["dias"].append(mapa.get((bloque, dia)))
        rejilla.append(fila)
    return rejilla


def construir_horarios_por_curso(horarios, filtro_grado="", filtro_seccion=""):
    fgh = (filtro_grado or "").strip().lower()
    fsh = (filtro_seccion or "").strip().lower()

    grupos = {}
    orden_claves = []

    for grado, seccion in CURSOS_BASE:
        if fgh and fgh not in grado.lower():
            continue
        if fsh and fsh not in seccion.lower():
            continue
        clave = (grado.lower(), seccion.lower())
        if clave not in grupos:
            grupos[clave] = {
                "grado_ano": grado,
                "seccion": seccion,
                "titulo": f'{grado} "{seccion}"',
                "clases": [],
            }
            orden_claves.append(clave)

    for h in horarios:
        grado = (h.grado_ano or "").strip()
        seccion = (h.seccion or "").strip()
        if fgh and fgh not in grado.lower():
            continue
        if fsh and fsh not in seccion.lower():
            continue
        clave = (grado.lower(), seccion.lower())
        if clave not in grupos:
            grupos[clave] = {
                "grado_ano": grado,
                "seccion": seccion,
                "titulo": f'{grado} "{seccion}"'.strip(),
                "clases": [],
            }
            orden_claves.append(clave)
        grupos[clave]["clases"].append(h)

    resultado = []
    for clave in orden_claves:
        info = grupos[clave]
        resultado.append(
            {
                "grado_ano": info["grado_ano"],
                "seccion": info["seccion"],
                "titulo": info["titulo"],
                "rejilla": construir_rejilla_horario(info["clases"]),
            }
        )
    return resultado


def guardar_foto_alumno(foto: UploadFile | None) -> str | None:
    if not foto or not foto.filename:
        return None
    ext = Path(foto.filename).suffix.lower()
    if ext not in {".jpg", ".jpeg", ".png", ".webp"}:
        ext = ".jpg"
    nombre_archivo = f"{uuid4().hex}{ext}"
    destino = FOTOS_DIR / nombre_archivo
    contenido = foto.file.read()
    if not contenido:
        return None
    destino.write_bytes(contenido)
    return nombre_archivo


@app.get("/", response_class=HTMLResponse)
def vista_login(request: Request, db: Session = Depends(get_db)):
    centro = obtener_o_crear_centro(db)
    return templates.TemplateResponse(request, "login.html", {"error": None, "centro": centro})


@app.post("/login")
def login(
    request: Request,
    cedula: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    centro = obtener_o_crear_centro(db)
    usuario = db.query(Usuario).filter(Usuario.cedula == cedula.strip()).first()
    if not usuario or not verify_password(password, usuario.password_hash) or not usuario.activo:
        return templates.TemplateResponse(
            request, "login.html", {"error": "CÃ©dula o contraseÃ±a incorrecta", "centro": centro}
        )
    token = crear_token({"sub": usuario.cedula, "rol": usuario.rol})
    resp = RedirectResponse(url="/panel", status_code=303)
    resp.set_cookie(key="access_token", value=token, httponly=True, path="/", samesite="lax")
    return resp


@app.get("/logout")
def logout():
    resp = RedirectResponse(url="/", status_code=303)
    resp.delete_cookie("access_token", path="/")
    return resp


@app.get("/panel", response_class=HTMLResponse)
def panel(
    request: Request,
    ano_id: int | None = None,
    editar_id: int | None = None,
    buscar_alumno: str = "",
    filtro_curso: str = "",
    filtro_materia: str = "",
    filtro_grado_horario: str = "",
    filtro_seccion_horario: str = "",
    clase_asistencia: str = "",
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(usuario_actual),
):
    centro = obtener_o_crear_centro(db)
    anos = db.query(AnoEscolar).order_by(AnoEscolar.id.desc()).all()
    ano_activo = next((a for a in anos if a.activo), anos[0] if anos else None)
    ano_seleccionado = next((a for a in anos if a.id == ano_id), ano_activo)

    matriculas_query = db.query(MatriculaAnual)
    horarios_query = db.query(HorarioClase)
    asignaciones_query = db.query(AsignacionDocente)
    if ano_seleccionado:
        matriculas_query = matriculas_query.filter(MatriculaAnual.ano_escolar_id == ano_seleccionado.id)
        horarios_query = horarios_query.filter(HorarioClase.ano_escolar_id == ano_seleccionado.id)
        asignaciones_query = asignaciones_query.filter(AsignacionDocente.ano_escolar_id == ano_seleccionado.id)

    matriculas = matriculas_query.all()
    horarios = horarios_query.all()
    asignaciones_ano = asignaciones_query.all()

    if usuario.rol == "representante":
        matriculas = [m for m in matriculas if m.estudiante.representante_id == usuario.id]

    matriculas_ficha = matriculas
    if buscar_alumno.strip():
        q = buscar_alumno.strip().lower()
        matriculas_ficha = [
            m
            for m in matriculas
            if q in (m.estudiante.nombres or "").lower()
            or q in (m.estudiante.apellidos or "").lower()
            or q in f"{m.estudiante.nombres or ''} {m.estudiante.apellidos or ''}".lower()
            or q in (m.estudiante.cedula_escolar or "").lower()
        ]

    asignaciones_docente = None
    if usuario.rol == "docente":
        asignaciones_docente = [a for a in asignaciones_ano if a.docente_id == usuario.id]
        if asignaciones_docente:
            pares_permitidos = {
                (a.grado_ano.strip().lower(), a.seccion.strip().lower()) for a in asignaciones_docente
            }
            matriculas_cuaderno = [
                m
                for m in matriculas
                if (m.grado_ano.strip().lower(), m.seccion.strip().lower()) in pares_permitidos
            ]
        else:
            matriculas_cuaderno = []
    else:
        matriculas_cuaderno = matriculas

    if filtro_curso.strip():
        fc = filtro_curso.strip().lower()
        matriculas_cuaderno = [
            m for m in matriculas_cuaderno if f"{m.grado_ano} {m.seccion}".lower().find(fc) != -1
        ]

    matricula_editar = next((m for m in matriculas if m.id == editar_id), None)

    ids_mat = [m.id for m in matriculas]
    calificaciones = db.query(Calificacion).filter(Calificacion.matricula_id.in_(ids_mat)).all() if ids_mat else []
    asistencias = db.query(Asistencia).filter(Asistencia.matricula_id.in_(ids_mat)).all() if ids_mat else []
    partes = db.query(ParteDisciplinario).filter(ParteDisciplinario.matricula_id.in_(ids_mat)).all() if ids_mat else []

    matriz_cuaderno = construir_matriz_cuaderno(matriculas_cuaderno, calificaciones, asignaciones_docente)
    if filtro_materia.strip():
        fm = filtro_materia.strip().lower()
        matriz_cuaderno = [f for f in matriz_cuaderno if fm in (f["asignatura"] or "").lower()]

    horarios_por_curso = construir_horarios_por_curso(
        horarios, filtro_grado_horario, filtro_seccion_horario
    )

    avisos_query = db.query(AvisoCentro).order_by(AvisoCentro.id.desc())
    if ano_seleccionado:
        avisos_query = avisos_query.filter(
            (AvisoCentro.ano_escolar_id == ano_seleccionado.id) | (AvisoCentro.ano_escolar_id.is_(None))
        )
    avisos = avisos_query.all()
    if usuario.rol == "representante":
        avisos = [av for av in avisos if av.dirigido_a in ("Todos", "Representantes")]
    elif usuario.rol == "docente":
        avisos = [av for av in avisos if av.dirigido_a in ("Todos", "Docentes")]

    boletines = []
    for m in matriculas:
        info = calcular_boletin_matricula(db, m.id)
        boletines.append(
            {
                "matricula": m,
                "estudiante": m.estudiante,
                "ano": m.ano_escolar.nombre,
                **info,
            }
        )

    representantes = db.query(Usuario).filter(Usuario.rol == "representante").all()
    docentes = db.query(Usuario).filter(Usuario.rol == "docente").all()
    usuarios_lista = db.query(Usuario).all()

    return templates.TemplateResponse(
        request,
        "panel.html",
        {
            "centro": centro,
            "usuario": usuario,
            "anos": anos,
            "ano_seleccionado": ano_seleccionado,
            "matriculas": matriculas,
            "matriculas_ficha": matriculas_ficha,
            "buscar_alumno": buscar_alumno,
            "matriculas_cuaderno": matriculas_cuaderno,
            "matricula_editar": matricula_editar,
            "representantes": representantes,
            "docentes": docentes,
            "asignaciones_ano": asignaciones_ano,
            "asignaciones_docente": asignaciones_docente,
            "filtro_curso": filtro_curso,
            "filtro_materia": filtro_materia,
            "filtro_grado_horario": filtro_grado_horario,
            "filtro_seccion_horario": filtro_seccion_horario,
            "usuarios_lista": usuarios_lista,
            "calificaciones": calificaciones,
            "matriz_cuaderno": matriz_cuaderno,
            "horarios_por_curso": horarios_por_curso,
            "asignaturas_base": ASIGNATURAS_BASE,
            "dias_semana": DIAS_SEMANA,
            "asistencias": asistencias,
            "partes": partes,
            "avisos": avisos,
            "boletines": boletines,
        },
    )


@app.post("/docentes/asignar")
def asignar_docente_materia(
    ano_escolar_id: int = Form(...),
    docente_id: int = Form(...),
    asignatura: str = Form(...),
    grado_ano: str = Form(...),
    seccion: str = Form(...),
    db: Session = Depends(get_db),
    _: Usuario = Depends(exigir_roles("director", "coordinador")),
):
    db.add(
        AsignacionDocente(
            ano_escolar_id=ano_escolar_id,
            docente_id=docente_id,
            asignatura=asignatura.strip(),
            grado_ano=grado_ano.strip(),
            seccion=seccion.strip(),
        )
    )
    db.commit()
    return RedirectResponse(url=f"/panel?ano_id={ano_escolar_id}", status_code=303)


@app.post("/docentes/asignaciones/{asignacion_id}/eliminar")
def eliminar_asignacion_docente(
    asignacion_id: int,
    db: Session = Depends(get_db),
    _: Usuario = Depends(exigir_roles("director", "coordinador")),
):
    asig = db.query(AsignacionDocente).filter(AsignacionDocente.id == asignacion_id).first()
    ano_id = asig.ano_escolar_id if asig else None
    if asig:
        db.delete(asig)
        db.commit()
    destino = f"/panel?ano_id={ano_id}" if ano_id else "/panel"
    return RedirectResponse(url=destino, status_code=303)


@app.post("/centro/guardar")
def guardar_centro(
    nombre_escuela: str = Form(...),
    codigo_dea: str = Form(""),
    ubicacion: str = Form(""),
    db: Session = Depends(get_db),
    _: Usuario = Depends(exigir_roles("director")),
):
    centro = obtener_o_crear_centro(db)
    centro.nombre_escuela = nombre_escuela.strip()
    centro.codigo_dea = codigo_dea.strip() or None
    centro.ubicacion = ubicacion.strip() or None
    db.commit()
    return RedirectResponse(url="/panel", status_code=303)

@app.post("/usuarios/{usuario_id}/editar")
def editar_usuario(
    usuario_id: int,
    cedula: str = Form(...),
    nombre_completo: str = Form(...),
    rol: str = Form(...),
    activo: str = Form("true"),
    password: str = Form(""),
    db: Session = Depends(get_db),
    director: Usuario = Depends(exigir_roles("director")),
):
    objetivo = db.query(Usuario).filter(Usuario.id == usuario_id).first()
    if not objetivo:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    cedula_limpia = cedula.strip()
    duplicado = db.query(Usuario).filter(Usuario.cedula == cedula_limpia, Usuario.id != usuario_id).first()
    if duplicado:
        raise HTTPException(status_code=400, detail="Esa cédula ya pertenece a otro usuario")

    if rol not in ("director", "coordinador", "docente", "representante"):
        raise HTTPException(status_code=400, detail="Rol no válido")

    es_activo = str(activo).lower() in ("true", "1", "on", "yes")
    if objetivo.id == director.id and not es_activo:
        raise HTTPException(status_code=400, detail="No puedes desactivar tu propia cuenta activa")

    objetivo.cedula = cedula_limpia
    objetivo.nombre_completo = nombre_completo.strip()
    objetivo.rol = rol
    objetivo.activo = es_activo
    if password.strip():
        objetivo.password_hash = hash_password(password.strip())

    db.commit()
    return RedirectResponse(url="/panel", status_code=303)


@app.post("/usuarios/{usuario_id}/eliminar")
def eliminar_usuario(
    usuario_id: int,
    db: Session = Depends(get_db),
    director: Usuario = Depends(exigir_roles("director")),
):
    objetivo = db.query(Usuario).filter(Usuario.id == usuario_id).first()
    if not objetivo:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    if objetivo.id == director.id:
        raise HTTPException(status_code=400, detail="No puedes eliminar tu propio usuario en sesión")

    tiene_vinculos = (
        db.query(AsignacionDocente).filter(AsignacionDocente.docente_id == usuario_id).first()
        or db.query(Estudiante).filter(Estudiante.representante_id == usuario_id).first()
        or db.query(Calificacion).filter(Calificacion.docente_id == usuario_id).first()
        or db.query(Asistencia).filter(
            (Asistencia.docente_id == usuario_id) | (Asistencia.revisado_por_id == usuario_id)
        ).first()
        or db.query(ParteDisciplinario).filter(ParteDisciplinario.reportado_por_id == usuario_id).first()
        or db.query(AvisoCentro).filter(AvisoCentro.autor_id == usuario_id).first()
    )
    if tiene_vinculos:
        raise HTTPException(
            status_code=400,
            detail="El usuario tiene registros académicos o administrativos asociados; edítalo para marcarlo como Inactivo",
        )

    db.delete(objetivo)
    db.commit()
    return RedirectResponse(url="/panel", status_code=303)


@app.post("/anos/crear")
def crear_ano_escolar(
    nombre: str = Form(...),
    activar: bool = Form(True),
    db: Session = Depends(get_db),
    _: Usuario = Depends(exigir_roles("director")),
):
    if activar:
        for a in db.query(AnoEscolar).all():
            a.activo = False
    db.add(AnoEscolar(nombre=nombre.strip(), activo=activar, cerrado=False))
    db.commit()
    return RedirectResponse(url="/panel", status_code=303)


@app.post("/anos/{ano_id}/cerrar")
def cerrar_ano_escolar(
    ano_id: int,
    db: Session = Depends(get_db),
    _: Usuario = Depends(exigir_roles("director")),
):
    ano = db.query(AnoEscolar).filter(AnoEscolar.id == ano_id).first()
    if not ano:
        raise HTTPException(status_code=404, detail="AÃ±o escolar no encontrado")
    ano.cerrado = True
    ano.activo = False

    matriculas = db.query(MatriculaAnual).filter(MatriculaAnual.ano_escolar_id == ano_id).all()
    for m in matriculas:
        res = calcular_boletin_matricula(db, m.id)
        m.promedio_final = res["promedio_general"]
        m.estatus_cierre = res["condicion"]

    db.commit()
    return RedirectResponse(url="/panel", status_code=303)


@app.post("/usuarios/crear")
def crear_usuario(
    cedula: str = Form(...),
    nombre_completo: str = Form(...),
    password: str = Form(...),
    rol: str = Form(...),
    db: Session = Depends(get_db),
    _: Usuario = Depends(exigir_roles("director")),
):
    if db.query(Usuario).filter(Usuario.cedula == cedula.strip()).first():
        raise HTTPException(status_code=400, detail="La cÃ©dula ya existe")
    db.add(
        Usuario(
            cedula=cedula.strip(),
            nombre_completo=nombre_completo.strip(),
            password_hash=hash_password(password),
            rol=rol,
        )
    )
    db.commit()
    return RedirectResponse(url="/panel", status_code=303)


@app.post("/estudiantes/inscribir-matricula")
def inscribir_y_matricular(
    cedula_escolar: str = Form(...),
    nombres: str = Form(...),
    apellidos: str = Form(...),
    sexo: str = Form(...),
    nombre_madre_padre: str = Form(...),
    representante_legal: str = Form(...),
    numero_contacto: str = Form(...),
    correo_personal: str = Form(""),
    alergias: str = Form(""),
    direccion: str = Form(...),
    representante_id: int = Form(...),
    ano_escolar_id: int = Form(...),
    grado_ano: str = Form(...),
    seccion: str = Form(...),
    foto: UploadFile | None = File(None),
    db: Session = Depends(get_db),
    _: Usuario = Depends(exigir_roles("director", "coordinador")),
):
    foto_guardada = guardar_foto_alumno(foto)
    correo_limpio = correo_personal.strip() or None
    rep_legal_limpio = representante_legal.strip() or None

    est = db.query(Estudiante).filter(Estudiante.cedula_escolar == cedula_escolar.strip()).first()
    if not est:
        est = Estudiante(
            cedula_escolar=cedula_escolar.strip(),
            nombres=nombres.strip(),
            apellidos=apellidos.strip(),
            sexo=sexo.strip() or None,
            nombre_madre_padre=nombre_madre_padre.strip() or None,
            representante_legal=rep_legal_limpio,
            numero_contacto=numero_contacto.strip() or None,
            correo_personal=correo_limpio,
            alergias=alergias.strip() or None,
            direccion=direccion.strip() or None,
            foto_filename=foto_guardada,
            representante_id=representante_id,
        )
        db.add(est)
        db.flush()
    else:
        est.nombres = nombres.strip()
        est.apellidos = apellidos.strip()
        est.sexo = sexo.strip() or est.sexo
        est.nombre_madre_padre = nombre_madre_padre.strip() or est.nombre_madre_padre
        est.representante_legal = rep_legal_limpio or est.representante_legal
        est.numero_contacto = numero_contacto.strip() or est.numero_contacto
        est.correo_personal = correo_limpio
        est.alergias = alergias.strip() if alergias.strip() else None
        est.direccion = direccion.strip() or est.direccion
        est.representante_id = representante_id
        if foto_guardada:
            est.foto_filename = foto_guardada

    db.add(
        MatriculaAnual(
            estudiante_id=est.id,
            ano_escolar_id=ano_escolar_id,
            grado_ano=grado_ano.strip(),
            seccion=seccion.strip(),
        )
    )
    db.commit()
    return RedirectResponse(url=f"/panel?ano_id={ano_escolar_id}", status_code=303)


@app.post("/matriculas/{matricula_id}/actualizar")
def actualizar_matricula_y_alumno(
    matricula_id: int,
    nombres: str = Form(...),
    apellidos: str = Form(...),
    sexo: str = Form(...),
    nombre_madre_padre: str = Form(...),
    representante_legal: str = Form(...),
    numero_contacto: str = Form(...),
    correo_personal: str = Form(""),
    alergias: str = Form(""),
    direccion: str = Form(...),
    representante_id: int = Form(...),
    grado_ano: str = Form(...),
    seccion: str = Form(...),
    foto: UploadFile | None = File(None),
    db: Session = Depends(get_db),
    _: Usuario = Depends(exigir_roles("director", "coordinador")),
):
    matricula = db.query(MatriculaAnual).filter(MatriculaAnual.id == matricula_id).first()
    if not matricula:
        raise HTTPException(status_code=404, detail="MatrÃ­cula no encontrada")

    estudiante = matricula.estudiante
    estudiante.nombres = nombres.strip()
    estudiante.apellidos = apellidos.strip()
    estudiante.sexo = sexo.strip() or None
    estudiante.nombre_madre_padre = nombre_madre_padre.strip() or None
    estudiante.representante_legal = representante_legal.strip() or None
    estudiante.numero_contacto = numero_contacto.strip() or None
    estudiante.correo_personal = correo_personal.strip() or None
    estudiante.alergias = alergias.strip() if alergias.strip() else None
    estudiante.direccion = direccion.strip() or None
    estudiante.representante_id = representante_id

    foto_guardada = guardar_foto_alumno(foto)
    if foto_guardada:
        estudiante.foto_filename = foto_guardada

    matricula.grado_ano = grado_ano.strip()
    matricula.seccion = seccion.strip()

    db.commit()
    return RedirectResponse(url=f"/panel?ano_id={matricula.ano_escolar_id}", status_code=303)


@app.post("/calificaciones/guardar")
def guardar_calificacion(
    matricula_id: int = Form(...),
    asignatura: str = Form(...),
    lapso: str = Form(...),
    nota_20: float = Form(...),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(exigir_roles("docente", "director")),
):
    if nota_20 < 1 or nota_20 > 20:
        raise HTTPException(status_code=400, detail="Nota fuera de rango (1 a 20)")
    db.add(
        Calificacion(
            matricula_id=matricula_id,
            docente_id=usuario.id,
            asignatura=asignatura.strip(),
            lapso=lapso.strip(),
            nota_20=nota_20,
        )
    )
    db.commit()
    return RedirectResponse(url="/panel", status_code=303)


@app.post("/horarios/guardar")
def guardar_horario(
    ano_escolar_id: int = Form(...),
    grado_ano: str = Form(...),
    seccion: str = Form(...),
    dia_semana: str = Form(...),
    bloque_hora: str = Form(...),
    asignatura: str = Form(...),
    aula: str = Form(""),
    db: Session = Depends(get_db),
    _: Usuario = Depends(exigir_roles("director", "coordinador")),
):
    db.add(
        HorarioClase(
            ano_escolar_id=ano_escolar_id,
            grado_ano=grado_ano.strip(),
            seccion=seccion.strip(),
            dia_semana=dia_semana.strip(),
            bloque_hora=bloque_hora.strip(),
            asignatura=asignatura.strip(),
            aula=aula.strip() if aula else None,
        )
    )
    db.commit()
    return RedirectResponse(url=f"/panel?ano_id={ano_escolar_id}", status_code=303)


@app.post("/horarios/{horario_id}/eliminar")
def eliminar_horario(
    horario_id: int,
    db: Session = Depends(get_db),
    _: Usuario = Depends(exigir_roles("director", "coordinador")),
):
    clase = db.query(HorarioClase).filter(HorarioClase.id == horario_id).first()
    ano_id = clase.ano_escolar_id if clase else None
    if clase:
        db.delete(clase)
        db.commit()
    destino = f"/panel?ano_id={ano_id}" if ano_id else "/panel"
    return RedirectResponse(url=destino, status_code=303)


@app.post("/asistencias/registrar")
def registrar_asistencia(
    matricula_id: int = Form(...),
    fecha: str = Form(...),
    estado: str = Form(...),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(exigir_roles("docente", "coordinador", "director")),
):
    estado_limpio = estado.strip()
    estado_just = "Sin justificar" if estado_limpio in ("Inasistente", "Retardo") else "No aplica"
    db.add(
        Asistencia(
            matricula_id=matricula_id,
            docente_id=usuario.id,
            fecha=fecha.strip(),
            estado=estado_limpio,
            estado_justificacion=estado_just,
        )
    )
    db.commit()
    return RedirectResponse(url="/panel", status_code=303)


@app.post("/asistencias/{asistencia_id}/justificar")
def justificar_asistencia(
    asistencia_id: int,
    motivo_justificacion: str = Form(...),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(usuario_actual),
):
    asistencia = db.query(Asistencia).filter(Asistencia.id == asistencia_id).first()
    if not asistencia:
        raise HTTPException(status_code=404, detail="Registro de asistencia no encontrado")
    if usuario.rol == "representante" and asistencia.matricula.estudiante.representante_id != usuario.id:
        raise HTTPException(status_code=403, detail="No autorizado para justificar esta falta")
    asistencia.motivo_justificacion = motivo_justificacion.strip()
    asistencia.estado_justificacion = "Pendiente"
    db.commit()
    return RedirectResponse(url="/panel", status_code=303)


@app.post("/asistencias/{asistencia_id}/revisar-justificacion")
def revisar_justificacion(
    asistencia_id: int,
    decision: str = Form(...),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(exigir_roles("docente", "coordinador", "director")),
):
    asistencia = db.query(Asistencia).filter(Asistencia.id == asistencia_id).first()
    if not asistencia:
        raise HTTPException(status_code=404, detail="Registro de asistencia no encontrado")
    if decision not in ("Aprobada", "Rechazada"):
        raise HTTPException(status_code=400, detail="DecisiÃ³n no vÃ¡lida")
    asistencia.estado_justificacion = decision
    asistencia.revisado_por_id = usuario.id
    db.commit()
    return RedirectResponse(url="/panel", status_code=303)

@app.post("/asistencias/{asistencia_id}/editar")
def editar_asistencia(
    asistencia_id: int,
    estado: str = Form(...),
    fecha: str = Form(""),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(exigir_roles("docente", "coordinador", "director")),
):
    registro = db.query(Asistencia).filter(Asistencia.id == asistencia_id).first()
    if not registro:
        raise HTTPException(status_code=404, detail="Registro de asistencia no encontrado")

    estado_limpio = estado.strip()
    if estado_limpio not in ("Presente", "Inasistente", "Retardo"):
        raise HTTPException(status_code=400, detail="Estado de asistencia no válido")

    registro.estado = estado_limpio
    if fecha.strip():
        registro.fecha = fecha.strip()
    if estado_limpio == "Presente":
        registro.estado_justificacion = "No aplica"
    elif registro.estado_justificacion == "No aplica":
        registro.estado_justificacion = "Sin justificar"

    db.commit()
    return RedirectResponse(url="/panel", status_code=303)



@app.post("/avisos/crear")
def crear_aviso(
    ano_escolar_id: int | None = Form(None),
    titulo: str = Form(...),
    mensaje: str = Form(...),
    dirigido_a: str = Form("Todos"),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(exigir_roles("director", "coordinador")),
):
    db.add(
        AvisoCentro(
            ano_escolar_id=ano_escolar_id,
            autor_id=usuario.id,
            titulo=titulo.strip(),
            mensaje=mensaje.strip(),
            dirigido_a=dirigido_a.strip() or "Todos",
        )
    )
    db.commit()
    return RedirectResponse(url="/panel", status_code=303)


@app.post("/partes/registrar")
def registrar_parte(
    matricula_id: int = Form(...),
    gravedad: str = Form(...),
    descripcion: str = Form(...),
    medida_pedagogica: str = Form(...),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(exigir_roles("docente", "coordinador", "director")),
):
    db.add(
        ParteDisciplinario(
            matricula_id=matricula_id,
            reportado_por_id=usuario.id,
            gravedad=gravedad.strip(),
            descripcion=descripcion.strip(),
            medida_pedagogica=medida_pedagogica.strip(),
        )
    )
    db.commit()
    return RedirectResponse(url="/panel", status_code=303)


