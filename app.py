from flask import Flask, render_template, request, jsonify, redirect, session
import sqlite3
import unicodedata
from functools import wraps

app = Flask(__name__)
app.secret_key = 'carnaval_fever_secret'
DB = 'asistentes.db'

# ================== UTILIDADES ==================

def conectar():
    return sqlite3.connect(DB)

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

# 🔥 IMPORTANTE: NO REDIRECT AQUÍ (para fetch)
def solo_admin(f):
    @wraps(f)
    def decorador(*args, **kwargs):
        if session.get('rol') != 'admin':
            return jsonify(error='forbidden'), 403
        return f(*args, **kwargs)
    return decorador

# ================== BASE DE DATOS ==================

def init_db():
    with conectar() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS asistentes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre TEXT,
                normalizado TEXT,
                asistio INTEGER DEFAULT 0
            )
        """)

        con.execute("""
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

        # Usuario admin fijo
        existe = con.execute(
            "SELECT id FROM usuarios WHERE usuario='ashleesoledispa'"
        ).fetchone()

        if not existe:
            con.execute("""
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

# ================== LOGIN ==================

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        u = request.form['usuario']
        p = request.form['password']

        with conectar() as con:
            user = con.execute("""
                SELECT id, nombre, rol
                FROM usuarios
                WHERE usuario=? AND password=?
            """, (u, p)).fetchone()

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
    with conectar() as con:
        total = con.execute("SELECT COUNT(*) FROM asistentes").fetchone()[0]
        asistieron = con.execute(
            "SELECT COUNT(*) FROM asistentes WHERE asistio=1"
        ).fetchone()[0]

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

    with conectar() as con:
        con.execute("DELETE FROM asistentes")
        for linea in lineas:
            if linea.strip():
                con.execute("""
                    INSERT INTO asistentes (nombre, normalizado)
                    VALUES (?,?)
                """, (linea.strip(), normalizar(linea)))

    return jsonify(ok=True)

@app.route('/buscar')
@login_requerido
def buscar():
    q = normalizar(request.args.get('q', ''))

    with conectar() as con:
        filas = con.execute("""
            SELECT id, nombre, asistio
            FROM asistentes
            WHERE normalizado LIKE ?
            ORDER BY nombre
        """, (f"%{q}%",)).fetchall()

    return jsonify([
        {"id": f[0], "nombre": f[1], "check": bool(f[2])}
        for f in filas
    ])

@app.route('/check', methods=['POST'])
@login_requerido
def check():
    id = request.json['id']
    with conectar() as con:
        con.execute("""
            UPDATE asistentes
            SET asistio = NOT asistio
            WHERE id = ?
        """, (id,))
    return jsonify(ok=True)

# ================== USUARIOS ==================

@app.route('/usuarios')
@login_requerido
@solo_admin
def usuarios():
    with conectar() as con:
        usuarios = con.execute("""
            SELECT id, nombre, usuario, celular, rol, cargo
            FROM usuarios
        """).fetchall()

    return render_template('usuarios.html', usuarios=usuarios)

@app.route('/crear_usuario', methods=['POST'])
@login_requerido
@solo_admin
def crear_usuario():
    d = request.form
    with conectar() as con:
        con.execute("""
            INSERT INTO usuarios
            (nombre, usuario, password, celular, rol, cargo)
            VALUES (?,?,?,?,?,?)
        """, (
            d['nombre'], d['usuario'], d['password'],
            d['celular'], d['rol'], d['cargo']
        ))
    return redirect('/usuarios')

@app.route('/editar_usuario/<int:id>', methods=['GET', 'POST'])
@login_requerido
@solo_admin
def editar_usuario(id):
    with conectar() as con:
        if request.method == 'POST':
            d = request.form
            con.execute("""
                UPDATE usuarios SET
                nombre=?, usuario=?, password=?,
                celular=?, rol=?, cargo=?
                WHERE id=?
            """, (
                d['nombre'], d['usuario'], d['password'],
                d['celular'], d['rol'], d['cargo'], id
            ))
            return redirect('/usuarios')

        usuario = con.execute("""
            SELECT id, nombre, usuario, password, celular, rol, cargo
            FROM usuarios WHERE id=?
        """, (id,)).fetchone()

    return render_template('editar_usuario.html', u=usuario)

@app.route('/eliminar_usuario/<int:id>', methods=['POST'])
@login_requerido
@solo_admin
def eliminar_usuario(id):
    if session.get('id') == id:
        return redirect('/usuarios')

    with conectar() as con:
        con.execute("DELETE FROM usuarios WHERE id=?", (id,))
    return redirect('/usuarios')

@app.route('/reset_password/<int:id>', methods=['POST'])
@login_requerido
@solo_admin
def reset_password(id):
    nueva = request.form['password']
    with conectar() as con:
        con.execute(
            "UPDATE usuarios SET password=? WHERE id=?",
            (nueva, id)
        )
    return redirect('/usuarios')

# ================== STAFF ==================

@app.route('/staff')
@login_requerido
def staff():
    with conectar() as con:
        usuarios = con.execute("""
            SELECT nombre, usuario, celular, rol, cargo
            FROM usuarios
        """).fetchall()

    return render_template('staff.html', usuarios=usuarios)

# ================== INIT ==================

init_db()

if __name__ == '__main__':
    app.run()

