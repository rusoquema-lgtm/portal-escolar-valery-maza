from datetime import datetime, timedelta
import bcrypt
from fastapi import Depends, HTTPException, Request, status
from jose import JWTError, jwt
from sqlalchemy.orm import Session
from .database import get_db
from .models import Usuario

import os

SECRET_KEY = os.getenv("SECRET_KEY", "clave_secreta_escolar_cambiar_en_produccion")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 12


def hash_password(password: str) -> str:
    pwd_bytes = password.encode("utf-8")[:72]
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(pwd_bytes, salt).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    pwd_bytes = plain_password.encode("utf-8")[:72]
    return bcrypt.checkpw(pwd_bytes, hashed_password.encode("utf-8"))


def crear_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def usuario_actual(request: Request, db: Session = Depends(get_db)) -> Usuario:
    token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Inicia sesión primero")
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        cedula: str = payload.get("sub")
        if not cedula:
            raise HTTPException(status_code=401, detail="Sesión inválida")
    except JWTError:
        raise HTTPException(status_code=401, detail="Sesión caducada")

    usuario = db.query(Usuario).filter(Usuario.cedula == cedula, Usuario.activo == True).first()
    if not usuario:
        raise HTTPException(status_code=401, detail="Usuario no encontrado o inactivo")
    return usuario


def exigir_roles(*roles_permitidos: str):
    def _verificar(usuario: Usuario = Depends(usuario_actual)) -> Usuario:
        if usuario.rol not in roles_permitidos:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Sin permiso para este rol")
        return usuario
    return _verificar
