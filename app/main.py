from datetime import date
from collections import defaultdict
from pathlib import Path
from uuid import uuid4
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
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
try:
    from sqlalchemy import text
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE calificaciones ADD COLUMN IF NOT EXISTS fecha VARCHAR(20)"))
        conn.execute(text("ALTER TABLE calificaciones ADD COLUMN IF NOT EXISTS nota_diaria TEXT"))
except Exception:
    pass

FOTOS_DIR = Path("app/static/fotos_alumnos")
FOTOS_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Portal Educativo â€” U.E Rafael Valery Maza")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

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
ASIGNATURAS_BASE = ['CASTELLANO', 'MATEMÁTICAS', 'CIENCIAS NATURALES', 'GHC', 'QUÍMICA', 'FÍSICA', 'ARTE Y PATRIMONIO', 'EDUCACIÃ“N FÃ\x8dSICA', 'INGLÉS', 'ORIENTACIÓN', 'GCRP', 'FSN', 'BIOLOGÍA', 'EDUCACIÓN FÍSICA']

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


def filtrar_horarios_para_usuario(db: Session, usuario: Usuario, horarios: list, ano_id: int | None):
    if not usuario or usuario.rol != "docente":
        return horarios
    q = db.query(AsignacionDocente).filter(AsignacionDocente.docente_id == usuario.id)
    if ano_id:
        q = q.filter(AsignacionDocente.ano_escolar_id == ano_id)
    asigs = q.all()
    if not asigs:
        return []
    filtrados = []
    for h in horarios:
        hg = (h.grado_ano or "").strip().lower()
        hs = (h.seccion or "").strip().lower()
        ha = (h.asignatura or "").strip().lower()
        for a in asigs:
            ag = (a.grado_ano or "").strip().lower()
            asec = (a.seccion or "").strip().lower()
            aasig = (a.asignatura or "").strip().lower()
            ok_grado = (not ag) or (ag == hg)
            ok_sec = (not asec) or (asec == "todas") or (asec == hs)
            ok_asig = (not aasig) or (aasig == ha)
            if ok_grado and ok_sec and ok_asig:
                filtrados.append(h)
                break
    return filtrados


def filtrar_horarios_docente(db: Session, usuario: Usuario, horarios: list, ano_id: int | None):
    if not usuario or usuario.rol != "docente":
        return horarios
    q = db.query(AsignacionDocente).filter(AsignacionDocente.docente_id == usuario.id)
    if ano_id:
        q = q.filter(AsignacionDocente.ano_escolar_id == ano_id)
    asignaciones = q.all()
    if not asignaciones:
        return []
    resultado = []
    for h in horarios:
        hg = (h.grado_ano or "").strip().lower()
        hs = (h.seccion or "").strip().lower()
        ha = (h.asignatura or "").strip().lower()
        for a in asignaciones:
            ag = (a.grado_ano or "").strip().lower()
            asec = (a.seccion or "").strip().lower()
            aasig = (a.asignatura or "").strip().lower()
            ok_g = (not ag) or (ag == hg)
            ok_s = (not asec) or (asec == "todas") or (asec == hs)
            ok_a = (not aasig) or (aasig == ha)
            if ok_g and ok_s and ok_a:
                resultado.append(h)
                break
    return resultado


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


@app.get("/login")
def login_get():
    return RedirectResponse(url="/", status_code=303)

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
    try:
        calificaciones = db.query(Calificacion).filter(Calificacion.matricula_id.in_(ids_mat)).all() if ids_mat else []
    except Exception:
        db.rollback()
        calificaciones = []
    asistencias = db.query(Asistencia).filter(Asistencia.matricula_id.in_(ids_mat)).all() if ids_mat else []
    partes = db.query(ParteDisciplinario).filter(ParteDisciplinario.matricula_id.in_(ids_mat)).all() if ids_mat else []

    matriz_cuaderno = construir_matriz_cuaderno(matriculas_cuaderno, calificaciones, asignaciones_docente)
    if filtro_materia.strip():
        fm = filtro_materia.strip().lower()
        matriz_cuaderno = [f for f in matriz_cuaderno if fm in (f["asignatura"] or "").lower()]

    horarios = filtrar_horarios_docente(
        db, usuario, horarios, ano_seleccionado.id if ano_seleccionado else None
    )
    fgh_filtro = (filtro_grado_horario or "").strip().lower()
    fsh_filtro = (filtro_seccion_horario or "").strip().lower()
    horarios_filtrados = [
        h for h in horarios
        if (not fgh_filtro or fgh_filtro in (h.grado_ano or "").strip().lower())
        and (not fsh_filtro or fsh_filtro in (h.seccion or "").strip().lower())
    ]
    rejilla_horario = construir_rejilla_horario(horarios_filtrados)
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
            "rejilla_horario": rejilla_horario,
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
    grado_ano: list[str] = Form(...),
    seccion: list[str] = Form(["TODAS"]),
    db: Session = Depends(get_db),
    _: Usuario = Depends(exigir_roles("director", "coordinador")),
):
    asig_limpia = asignatura.strip()
    if not asig_limpia:
        raise HTTPException(status_code=400, detail="La asignatura es obligatoria")

    grados_seleccionados = [g.strip() for g in grado_ano if g and g.strip()]
    if not grados_seleccionados:
        raise HTTPException(status_code=400, detail="Selecciona al menos un grado o año")

    secciones_raw = [s.strip() for s in seccion if s and s.strip()]
    todas_las_secciones = (not secciones_raw) or any(
        s.upper() in ("TODAS", "ALL", "*") for s in secciones_raw
    )

    # Secciones conocidas en el año escolar por grado/año
    secciones_por_grado: dict[str, list[str]] = {}
    mats = (
        db.query(MatriculaAnual.grado_ano, MatriculaAnual.seccion)
        .filter(MatriculaAnual.ano_escolar_id == ano_escolar_id)
        .all()
    )
    for g_val, s_val in mats:
        g_clean = (g_val or "").strip()
        s_clean = (s_val or "").strip()
        if g_clean and s_clean:
            secciones_por_grado.setdefault(g_clean, [])
            if s_clean not in secciones_por_grado[g_clean]:
                secciones_por_grado[g_clean].append(s_clean)

    # Evitar duplicados exactos
    existentes = (
        db.query(AsignacionDocente)
        .filter(
            AsignacionDocente.ano_escolar_id == ano_escolar_id,
            AsignacionDocente.docente_id == docente_id,
            AsignacionDocente.asignatura == asig_limpia,
        )
        .all()
    )
    claves_existentes = {
        ((a.grado_ano or "").strip(), (a.seccion or "").strip()) for a in existentes
    }

    agregadas = 0
    for g_item in grados_seleccionados:
        if todas_las_secciones:
            secs_objetivo = secciones_por_grado.get(g_item) or ["A", "B", "C"]
        else:
            secs_objetivo = secciones_raw

        for s_item in secs_objetivo:
            s_clean = s_item.strip()
            if not s_clean:
                continue
            clave = (g_item, s_clean)
            if clave in claves_existentes:
                continue
            db.add(
                AsignacionDocente(
                    ano_escolar_id=ano_escolar_id,
                    docente_id=docente_id,
                    asignatura=asig_limpia,
                    grado_ano=g_item,
                    seccion=s_clean,
                )
            )
            claves_existentes.add(clave)
            agregadas += 1

    if agregadas:
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
    from urllib.parse import urlencode
    qs = urlencode({
        "ano_id": ano_escolar_id,
        "filtro_grado_horario": grado_ano.strip(),
        "filtro_seccion_horario": seccion.strip(),
    })
    return RedirectResponse(url=f"/panel?{qs}", status_code=303)


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



@app.post("/matriculas/{matricula_id}/baja")
def dar_de_baja_matricula(
    matricula_id: int,
    db: Session = Depends(get_db),
    _: Usuario = Depends(exigir_roles("director", "coordinador")),
):
    matricula = db.query(MatriculaAnual).filter(MatriculaAnual.id == matricula_id).first()
    if not matricula:
        raise HTTPException(status_code=404, detail="Matr?cula no encontrada")

    ano_id = matricula.ano_escolar_id
    matricula.estatus_cierre = "baja"
    db.commit()
    destino = f"/panel?ano_id={ano_id}" if ano_id else "/panel"
    return RedirectResponse(url=destino, status_code=303)


@app.post("/matriculas/{matricula_id}/eliminar")
def eliminar_matricula(
    matricula_id: int,
    db: Session = Depends(get_db),
    _: Usuario = Depends(exigir_roles("director", "coordinador")),
):
    matricula = db.query(MatriculaAnual).filter(MatriculaAnual.id == matricula_id).first()
    if not matricula:
        raise HTTPException(status_code=404, detail="Matr?cula no encontrada")

    ano_id = matricula.ano_escolar_id
    db.query(Calificacion).filter(Calificacion.matricula_id == matricula_id).delete(synchronize_session=False)
    db.query(Asistencia).filter(Asistencia.matricula_id == matricula_id).delete(synchronize_session=False)
    db.query(ParteDisciplinario).filter(ParteDisciplinario.matricula_id == matricula_id).delete(synchronize_session=False)
    db.delete(matricula)
    db.commit()
    destino = f"/panel?ano_id={ano_id}" if ano_id else "/panel"
    return RedirectResponse(url=destino, status_code=303)

@app.post("/calificaciones/guardar")
def guardar_calificacion(
    matricula_id: int = Form(...),
    asignatura: str = Form(...),
    lapso: str = Form("1er Momento"),
    nota_20: float = Form(...),
    fecha: str = Form(""),
    nota_diaria: str = Form(""),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(exigir_roles("docente", "director")),
):
    if nota_20 < 0 or nota_20 > 20:
        raise HTTPException(status_code=400, detail="Nota fuera de rango (0 a 20)")
    fecha_limpia = (fecha or "").strip() or date.today().isoformat()
    nota_diaria_limpia = (nota_diaria or "").strip() or None
    nuevo_reg = Calificacion(
        matricula_id=matricula_id,
        docente_id=usuario.id,
        asignatura=asignatura.strip(),
        lapso=(lapso or "1er Momento").strip(),
        nota_20=nota_20,
        fecha=fecha_limpia,
    )
    if hasattr(nuevo_reg, "nota_diaria"):
        nuevo_reg.nota_diaria = nota_diaria_limpia
    db.add(nuevo_reg)
    db.commit()
    return RedirectResponse(url="/panel", status_code=303)


@app.post("/calificaciones/{calificacion_id}/editar")
def editar_calificacion(
    calificacion_id: int,
    nota_20: float = Form(...),
    fecha: str = Form(""),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(exigir_roles("docente", "director")),
):
    if nota_20 < 1 or nota_20 > 20:
        raise HTTPException(status_code=400, detail="Nota fuera de rango (1 a 20)")
    reg = db.query(Calificacion).filter(Calificacion.id == calificacion_id).first()
    if not reg:
        raise HTTPException(status_code=404, detail="Calificaci?n no encontrada")
    reg.nota_20 = nota_20
    if (fecha or "").strip():
        reg.fecha = fecha.strip()
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
    from urllib.parse import urlencode
    qs = urlencode({
        "ano_id": ano_escolar_id,
        "filtro_grado_horario": grado_ano.strip(),
        "filtro_seccion_horario": seccion.strip(),
    })
    return RedirectResponse(url=f"/panel?{qs}", status_code=303)


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




@app.post("/api/public/matriculas")
async def inscribir_desde_web_publica(
    request: Request,
    db: Session = Depends(get_db),
):
    content_type = (request.headers.get("content-type") or "").lower()
    if "application/json" in content_type:
        data = await request.json()
    else:
        form = await request.form()
        data = dict(form)

    cedula_escolar = str(data.get("cedula_escolar") or "").strip()
    nombres = str(data.get("nombres") or "").strip()
    apellidos = str(data.get("apellidos") or "").strip()
    grado_ano = str(data.get("grado_ano") or "").strip()
    seccion = str(data.get("seccion") or "A").strip() or "A"

    if not cedula_escolar or not nombres or not apellidos or not grado_ano:
        raise HTTPException(
            status_code=400,
            detail="Faltan campos obligatorios: cedula_escolar, nombres, apellidos y grado_ano",
        )

    anos = db.query(AnoEscolar).order_by(AnoEscolar.id.desc()).all()
    ano_activo = next((a for a in anos if a.activo), anos[0] if anos else None)
    if not ano_activo:
        raise HTTPException(status_code=400, detail="No hay un a?o escolar configurado")

    sexo = str(data.get("sexo") or "").strip() or None
    nombre_madre_padre = str(data.get("nombre_madre_padre") or "").strip() or None
    rep_legal = str(data.get("representante_legal") or nombre_madre_padre or "").strip() or None
    numero_contacto = str(data.get("numero_contacto") or "").strip() or None
    correo_personal = str(data.get("correo_personal") or "").strip() or None
    alergias = str(data.get("alergias") or "").strip() or None
    direccion = str(data.get("direccion") or "").strip() or None

    rep_user = (
        db.query(Usuario).filter(Usuario.rol == "representante").order_by(Usuario.id.asc()).first()
        or db.query(Usuario).order_by(Usuario.id.asc()).first()
    )
    if not rep_user:
        raise HTTPException(
            status_code=400,
            detail="No existe un usuario representante o base en el sistema para asignar representante_id",
        )

    est = db.query(Estudiante).filter(Estudiante.cedula_escolar == cedula_escolar).first()
    if not est:
        est = Estudiante(
            cedula_escolar=cedula_escolar,
            nombres=nombres,
            apellidos=apellidos,
            sexo=sexo,
            nombre_madre_padre=nombre_madre_padre,
            representante_legal=rep_legal,
            numero_contacto=numero_contacto,
            correo_personal=correo_personal,
            alergias=alergias,
            direccion=direccion,
            representante_id=rep_user.id,
        )
        db.add(est)
        db.flush()
    else:
        est.nombres = nombres
        est.apellidos = apellidos
        if sexo:
            est.sexo = sexo
        if nombre_madre_padre:
            est.nombre_madre_padre = nombre_madre_padre
        if rep_legal:
            est.representante_legal = rep_legal
        if numero_contacto:
            est.numero_contacto = numero_contacto
        if correo_personal:
            est.correo_personal = correo_personal
        if alergias is not None:
            est.alergias = alergias or None
        if direccion:
            est.direccion = direccion
        if not est.representante_id:
            est.representante_id = rep_user.id

    matricula_existente = (
        db.query(MatriculaAnual)
        .filter(
            MatriculaAnual.estudiante_id == est.id,
            MatriculaAnual.ano_escolar_id == ano_activo.id,
        )
        .first()
    )
    if matricula_existente:
        matricula_existente.grado_ano = grado_ano
        matricula_existente.seccion = seccion
        if not matricula_existente.estatus_cierre:
            matricula_existente.estatus_cierre = "pendiente"
        matricula_id = matricula_existente.id
    else:
        nueva_mat = MatriculaAnual(
            estudiante_id=est.id,
            ano_escolar_id=ano_activo.id,
            grado_ano=grado_ano,
            seccion=seccion,
            estatus_cierre="pendiente",
        )
        db.add(nueva_mat)
        db.flush()
        matricula_id = nueva_mat.id

    db.commit()
    return {
        "ok": True,
        "estado_solicitud": "pendiente",
        "mensaje": "Solicitud enviada a la escuela. Queda pendiente de revisi?n y aceptaci?n",
        "matricula_id": matricula_id,
        "estudiante_id": est.id,
        "ano_escolar": ano_activo.nombre,
    }


@app.post("/matriculas/{matricula_id}/aceptar")
def aceptar_matricula_solicitada(
    matricula_id: int,
    db: Session = Depends(get_db),
    _: Usuario = Depends(exigir_roles("director", "coordinador")),
):
    matricula = db.query(MatriculaAnual).filter(MatriculaAnual.id == matricula_id).first()
    if not matricula:
        raise HTTPException(status_code=404, detail="Matr?cula no encontrada")

    ano_id = matricula.ano_escolar_id
    matricula.estatus_cierre = "en_curso"
    db.commit()
    destino = f"/panel?ano_id={ano_id}" if ano_id else "/panel"
    return RedirectResponse(url=destino, status_code=303)


@app.post("/matriculas/{matricula_id}/rechazar")
def rechazar_matricula_solicitada(
    matricula_id: int,
    db: Session = Depends(get_db),
    _: Usuario = Depends(exigir_roles("director", "coordinador")),
):
    matricula = db.query(MatriculaAnual).filter(MatriculaAnual.id == matricula_id).first()
    if not matricula:
        raise HTTPException(status_code=404, detail="Matr?cula no encontrada")

    ano_id = matricula.ano_escolar_id
    db.query(Calificacion).filter(Calificacion.matricula_id == matricula_id).delete(synchronize_session=False)
    db.query(Asistencia).filter(Asistencia.matricula_id == matricula_id).delete(synchronize_session=False)
    db.query(ParteDisciplinario).filter(ParteDisciplinario.matricula_id == matricula_id).delete(synchronize_session=False)
    db.delete(matricula)
    db.commit()
    destino = f"/panel?ano_id={ano_id}" if ano_id else "/panel"
    return RedirectResponse(url=destino, status_code=303)




@app.delete("/api/panel/galeria/{nombre_archivo}")
def eliminar_foto_galeria(nombre_archivo: str, request: Request):
    usuario_id = request.session.get("usuario_id")
    rol = (request.session.get("rol") or "").lower()
    if not usuario_id or rol not in ("director", "coordinador", "admin", "administrador", "directivo"):
        raise HTTPException(status_code=403, detail="Acceso denegado")
    carpeta = Path("app/static/galeria").resolve()
    archivo_seguro = Path(nombre_archivo).name
    destino = (carpeta / archivo_seguro).resolve()
    if destino.parent != carpeta or not destino.exists() or not destino.is_file():
        raise HTTPException(status_code=404, detail="Imagen no encontrada")
    destino.unlink()
    return {"ok": True, "eliminado": archivo_seguro}

@app.get("/api/public/galeria")
def listar_galeria_publica(request: Request):
    carpeta = Path("app/static/galeria")
    carpeta.mkdir(parents=True, exist_ok=True)
    base_url = str(request.base_url).rstrip("/")
    archivos = []
    exts = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
    for f in sorted(carpeta.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if f.is_file() and f.suffix.lower() in exts:
            partes = f.stem.split("__", 1)
            titulo = partes[1].replace("_", " ") if len(partes) == 2 else f.stem.replace("_", " ")
            archivos.append({
                "archivo": f.name,
                "titulo": titulo,
                "url": f"{base_url}/static/galeria/{f.name}",
            })
    return {"fotos": archivos}


@app.post("/api/public/galeria")
async def subir_foto_galeria(
    request: Request,
    usuario_id = request.session.get("usuario_id")
    rol = (request.session.get("rol") or "").lower()
    if not usuario_id or rol not in ("director", "coordinador", "admin", "administrador", "directivo"):
        raise HTTPException(status_code=403, detail="Solo el administrador autenticado puede subir imagenes")
    titulo: str = Form("Actividad escolar"),
    categoria: str = Form("Escuela"),
    foto: UploadFile = File(...),
):
    carpeta = Path("app/static/galeria")
    carpeta.mkdir(parents=True, exist_ok=True)
    ext = Path(foto.filename or "foto.jpg").suffix.lower()
    if ext not in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
        raise HTTPException(status_code=400, detail="Formato de imagen no permitido (usa JPG, PNG o WEBP)")

    contenido = await foto.read()
    if not contenido:
        raise HTTPException(status_code=400, detail="El archivo de imagen est? vac?o")

    titulo_limpio = "".join(c if c.isalnum() or c in (" ", "-", "_") else "" for c in (titulo or "Actividad")).strip().replace(" ", "_")[:45] or "Actividad"
    cat_limpia = "".join(c if c.isalnum() else "" for c in (categoria or "Escuela"))[:20] or "Escuela"
    nombre_final = f"{cat_limpia}_{uuid.uuid4().hex[:8]}__{titulo_limpio}{ext}"
    (carpeta / nombre_final).write_bytes(contenido)

    base_url = str(request.base_url).rstrip("/")
    return {
        "ok": True,
        "mensaje": "Imagen subida correctamente a la galer?a",
        "foto": {
            "archivo": nombre_final,
            "titulo": titulo_limpio.replace("_", " "),
            "categoria": cat_limpia,
            "url": f"{base_url}/static/galeria/{nombre_final}",
        },
    }
