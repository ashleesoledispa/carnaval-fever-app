from flask import Flask, render_template, request, jsonify, redirect, session
import sqlite3
import unicodedata
from functools import wraps
import os
import psycopg2

app = Flask(__name__)
app.secret_key = 'carnaval_fever_secret'

# Cookies seguras para Render (HTTPS)
app.config['SESSION_COOKIE_SECURE'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

DB = 'asistentes.db'


# ================== CONEXIÓN ==================

def conectar():
    DATABASE_URL = os.environ.get("DATABASE_URL")

    # En Render → PostgreSQL
    if DATABASE_URL:
        return psycopg2.connect(DATABASE_URL)

    # En local → SQLite
    return sqlite3.connect(DB)


def es_postgres():
    return os.environ.get("DATABASE_URL") is not None


# ================== UTILIDADES ==================

def normalizar(texto):
    texto = texto.lower()
    return ''.join(
        c for c in unicodedata.normalize('NFD', texto)
        if unicodedata.category(c) != 'Mn'
    )


def login_requerido(f):
    @wraps(f)
    def decorador(*args, **kwargs):
        if 'usuario' not in session:
            return redirect('/login')
        return f(*args, **kwargs)
    return decorador


def solo_admin(f):
    @wraps(f)
    def decorador(*args, **kwargs):
        if session.get('rol') != 'admin':
            return jsonify(error='forbidden'), 403
        return f(*args, **kwargs)
    return decorador


# ================== BASE DE DATOS ==================

def init_db():
    con = conectar()
    cur = con.cursor()

    if es_postgres():
        cur.execute("""
            CREATE TABLE IF NOT EXISTS asistentes (
                id SERIAL PRIMARY KEY,
                nombre TEXT,
                normalizado TEXT,
                asistio BOOLEAN DEFAULT FALSE
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS usuarios (
                id SERIAL PRIMARY KEY,
                nombre TEXT,
                usuario TEXT UNIQUE,
                password TEXT,
                celular TEXT,
                rol TEXT,
                cargo TEXT
            )
        """)
    else:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS asistentes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre TEXT,
                normalizado TEXT,
                asistio INTEGER DEFAULT 0
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS usuarios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre TEXT,
                usuario TEXT UNIQUE,
                password TEXT,
                celular TEXT,
                rol TEXT,
                cargo TEXT
            )
        """)

    # Crear admin si no existe
    if es_postgres():
        cur.execute("SELECT id FROM usuarios WHERE usuario=%s", ('ashleesoledispa',))
    else:
        cur.execute("SELECT id FROM usuarios WHERE usuario=?", ('ashleesoledispa',))

    existe = cur.fetchone()

    if not existe:
        if es_postgres():
            cur.execute("""
                INSERT INTO usuarios
                (nombre, usuario, password, celular, rol, cargo)
                VALUES (%s,%s,%s,%s,%s,%s)
            """, (
                'Ashlee Soledispa',
                'ashleesoledispa',
                '1350830574',
                '',
                'admin',
                'Administradora General'
            ))
        else:
            cur.execute("""
                INSERT INTO usuarios
                (nombre, usuario, password, celular, rol, cargo)
                VALUES (?,?,?,?,?,?)
            """, (
                'Ashlee Soledispa',
                'ashleesoledispa',
                '1350830574',
                '',
                'admin',
                'Administradora General'
            ))

    con.commit()
    cur.close()
    con.close()


# ================== LOGIN ==================

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        u = request.form['usuario']
        p = request.form['password']

        con = conectar()
        cur = con.cursor()

        if es_postgres():
            cur.execute("""
                SELECT id, nombre, rol
                FROM usuarios
                WHERE usuario=%s AND password=%s
            """, (u, p))
        else:
            cur.execute("""
                SELECT id, nombre, rol
                FROM usuarios
                WHERE usuario=? AND password=?
            """, (u, p))

        user = cur.fetchone()
        cur.close()
        con.close()

        if user:
            session['id'] = user[0]
            session['usuario'] = u
            session['nombre'] = user[1]
            session['rol'] = user[2]
            return redirect('/')

        return render_template('login.html', error=True)

    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')


# ================== DASHBOARD ==================

@app.route('/')
@login_requerido
def dashboard():
    con = conectar()
    cur = con.cursor()

    cur.execute("SELECT COUNT(*) FROM asistentes")
    total = cur.fetchone()[0]

    if es_postgres():
        cur.execute("SELECT COUNT(*) FROM asistentes WHERE asistio=TRUE")
    else:
        cur.execute("SELECT COUNT(*) FROM asistentes WHERE asistio=1")

    asistieron = cur.fetchone()[0]

    cur.close()
    con.close()

    return render_template(
        'dashboard.html',
        total=total,
        asistieron=asistieron,
        no_asistieron=total - asistieron
    )


# ================== ASISTENTES ==================

@app.route('/asistentes')
@login_requerido
def asistentes():
    return render_template('asistentes.html')


@app.route('/cargar', methods=['POST'])
@login_requerido
@solo_admin
def cargar():
    texto = request.json.get('texto', '')
    lineas = texto.splitlines()

    con = conectar()
    cur = con.cursor()

    cur.execute("DELETE FROM asistentes")

    for linea in lineas:
        if linea.strip():
            if es_postgres():
                cur.execute(
                    "INSERT INTO asistentes (nombre, normalizado) VALUES (%s,%s)",
                    (linea.strip(), normalizar(linea))
                )
            else:
                cur.execute(
                    "INSERT INTO asistentes (nombre, normalizado) VALUES (?,?)",
                    (linea.strip(), normalizar(linea))
                )

    con.commit()
    cur.close()
    con.close()

    return jsonify(ok=True)


@app.route('/buscar')
@login_requerido
def buscar():
    q = normalizar(request.args.get('q', ''))

    con = conectar()
    cur = con.cursor()

    if es_postgres():
        cur.execute("""
            SELECT id, nombre, asistio
            FROM asistentes
            WHERE normalizado ILIKE %s
            ORDER BY nombre
        """, (f"%{q}%",))
    else:
        cur.execute("""
            SELECT id, nombre, asistio
            FROM asistentes
            WHERE normalizado LIKE ?
            ORDER BY nombre
        """, (f"%{q}%",))

    filas = cur.fetchall()

    cur.close()
    con.close()

    return jsonify([
        {"id": f[0], "nombre": f[1], "check": bool(f[2])}
        for f in filas
    ])


@app.route('/check', methods=['POST'])
@login_requerido
def check():
    id = request.json['id']

    con = conectar()
    cur = con.cursor()

    if es_postgres():
        cur.execute("UPDATE asistentes SET asistio = NOT asistio WHERE id = %s", (id,))
    else:
        cur.execute("UPDATE asistentes SET asistio = NOT asistio WHERE id = ?", (id,))

    con.commit()
    cur.close()
    con.close()

    return jsonify(ok=True)


# ================== USUARIOS ==================

@app.route('/usuarios')
@login_requerido
@solo_admin
def usuarios():
    con = conectar()
    cur = con.cursor()

    cur.execute("""
        SELECT id, nombre, usuario, celular, rol, cargo
        FROM usuarios
    """)

    usuarios = cur.fetchall()

    cur.close()
    con.close()

    return render_template('usuarios.html', usuarios=usuarios)


@app.route('/staff')
@login_requerido
def staff():
    con = conectar()
    cur = con.cursor()

    cur.execute("""
        SELECT nombre, usuario, celular, rol, cargo
        FROM usuarios
    """)

    usuarios = cur.fetchall()

    cur.close()
    con.close()

    return render_template('staff.html', usuarios=usuarios)


# ================== INIT ==================

init_db()

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=5000)
