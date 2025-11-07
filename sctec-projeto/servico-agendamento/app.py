# app.py
import os
import uuid
import hmac
import hashlib
import json
from datetime import datetime
from functools import wraps

from flask import Flask, request, jsonify, g
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.exc import IntegrityError # IMPORTANTE: Adiciona a exceção de erro de integridade do DB
import logging
from logging.handlers import RotatingFileHandler

# --- Config ---
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH = os.environ.get("SCTEC_DB_PATH", os.path.join(BASE_DIR, "sctec.db"))
AUDIT_LOG_FILE = os.environ.get("SCTEC_AUDIT_LOG", os.path.join(BASE_DIR, "audit.log"))
APP_LOG_FILE = os.environ.get("SCTEC_APP_LOG", os.path.join(BASE_DIR, "app.log"))
AUDIT_HMAC_KEY = os.environ.get("SCTEC_AUDIT_KEY", "dev_audit_key_change_me")  # production: load from KMS

# Flask + SQLAlchemy
app = Flask(__name__)
# CONFIGURAÇÃO DE ISOLAMENTO DE TRANSAÇÃO (pode ajudar, mas não é a solução única para o SQLite)
# O SQLite por padrão usa 'DEFERRED'. 'IMMEDIATE' pode ser mais agressivo.
# No entanto, a falha real é tratar a exceção.
# Linha 48 CORRIGIDA
app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{DB_PATH}?isolation_level=IMMEDIATE"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)

# --- Models ---
class Scientist(db.Model):
    __tablename__ = "scientists"
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String, nullable=False)
    email = db.Column(db.String, unique=True, nullable=False)
    instituicao = db.Column(db.String, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Telescope(db.Model):
    __tablename__ = "telescopes"
    id = db.Column(db.String, primary_key=True)  # ex: hubble-acad
    nome = db.Column(db.String)
    descricao = db.Column(db.String)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    # capabilities omitted for simplicity

class Booking(db.Model):
    __tablename__ = "bookings"
    id = db.Column(db.Integer, primary_key=True)
    telescope_id = db.Column(db.String, db.ForeignKey("telescopes.id"), nullable=False)
    cientista_id = db.Column(db.Integer, db.ForeignKey("scientists.id"), nullable=False)
    start_utc = db.Column(db.String, nullable=False)  # keep as RFC3339 string for simplicity
    end_utc = db.Column(db.String, nullable=False)
    status = db.Column(db.String, default="CONFIRMED")
    request_timestamp_utc = db.Column(db.String, nullable=True)
    audit_log_ref = db.Column(db.String, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

# --- Logging setup ---
# Application logger (human + JSON lines via structured logger if needed)
app_logger = logging.getLogger("sctec_app")
app_logger.setLevel(logging.INFO)
formatter = logging.Formatter('%(levelname)s:%(asctime)s:%(name)s:%(message)s', "%Y-%m-%dT%H:%M:%S%z")

file_handler = RotatingFileHandler(APP_LOG_FILE, maxBytes=5*1024*1024, backupCount=2)
file_handler.setFormatter(formatter)
app_logger.addHandler(file_handler)

stream_handler = logging.StreamHandler()
stream_handler.setFormatter(formatter)
app_logger.addHandler(stream_handler)

# Audit log writer (append-only JSONL with HMAC signature)
def write_audit_log(entry: dict):
    # add generated id and timestamp if not present
    if "id" not in entry:
        entry["id"] = str(uuid.uuid4())
    if "timestamp_utc" not in entry:
        entry["timestamp_utc"] = datetime.utcnow().isoformat() + "Z"
    # compute signature (HMAC-SHA256 of canonical JSON)
    payload = json.dumps(entry, separators=(",", ":"), sort_keys=True, ensure_ascii=False)
    sig = hmac.new(AUDIT_HMAC_KEY.encode(), payload.encode(), hashlib.sha256).digest()
    signature = "hmac-sha256:" + sig.hex()
    entry["signature"] = signature
    # append to file
    with open(AUDIT_LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    # also log a short app-log line
    app_logger.info(f"AUDIT:{entry.get('event_type')} request_id={entry.get('request_id')} audit_id={entry.get('id')}")

# --- Helpers ---
def now_rfc3339_ms():
    return datetime.utcnow().isoformat(timespec="milliseconds") + "Z"

def gen_request_id():
    return f"req-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"

def require_json(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not request.is_json:
            app_logger.info(f"BadRequest: non-json request path={request.path} remote={request.remote_addr}")
            return jsonify({"error":"BAD_REQUEST","message":"Content-Type must be application/json"}), 400
        return f(*args, **kwargs)
    return wrapper

# --- Routes ---
@app.before_request
def attach_request_id():
    g.request_id = request.headers.get("X-Request-Id") or gen_request_id()
    g.remote_ip = request.remote_addr

@app.route("/time", methods=["GET"])
def get_time():
    app_logger.info(f"GET /time request_id={g.request_id} remote={g.remote_ip}")
    return jsonify({
        "server_time_utc": now_rfc3339_ms(),
        "server_unix_ms": int(datetime.utcnow().timestamp() * 1000)
    })

@app.route("/telescopios", methods=["GET"])
def list_telescopes():
    app_logger.info(f"GET /telescopios request_id={g.request_id}")
    telescopes = Telescope.query.all()
    out = []
    for t in telescopes:
        out.append({"id":t.id, "nome":t.nome, "links":[{"rel":"self","href":f"/telescopios/{t.id}"}]})
    return jsonify({"telescopes": out, "links":[{"rel":"create_booking","href":"/agendamentos","method":"POST"}]})

# FUNÇÃO REINTRODUZIDA PARA VERIFICAÇÃO INICIAL
def overlaps(telescope_id, start_utc, end_utc):
    # naive string-based iso comparisons; acceptable here as inputs are RFC3339 UTC identical format
    q = Booking.query.filter(Booking.telescope_id == telescope_id).all()
    for b in q:
        if not (end_utc <= b.start_utc or start_utc >= b.end_utc):
            return True
    return False

@app.route("/agendamentos", methods=["POST"])
@require_json
def create_booking():
    payload = request.get_json()
    app_logger.info(f"Requisição recebida para POST /agendamentos request_id={g.request_id} remote={g.remote_ip} payload_keys={list(payload.keys())}")
    # Basic validation
    required = ["telescope_id", "cientista_id", "start_utc", "end_utc", "request_timestamp_utc"]
    for r in required:
        if r not in payload:
            app_logger.info(f"Bad request missing field {r} request_id={g.request_id}")
            return jsonify({"error":"BAD_REQUEST","message":f"missing {r}","request_id":g.request_id}), 400
    telescope_id = payload["telescope_id"]
    cientista_id = payload["cientista_id"]
    start_utc = payload["start_utc"]
    end_utc = payload["end_utc"]

    app_logger.info(f"Tentando verificar conflito no BD request_id={g.request_id} telescope={telescope_id} start={start_utc}")

    # --------- CRITICAL SECTION (CORRIGIDA COM TRATAMENTO DE EXCEÇÃO DE DB) -----------
    try:
        # 1. Checagem inicial de sobreposição (ainda vulnerável na corrida, mas filtra a maioria)
        conflict = overlaps(telescope_id, start_utc, end_utc)
        if conflict:
            app_logger.info(f"Conflito detectado: agendamento existente no DB request_id={g.request_id}")
            # Se a reserva já existe, rejeita e audita.
            audit = {
                "timestamp_utc": now_rfc3339_ms(),
                "level": "AUDIT",
                "event_type": "AGENDAMENTO_RECUSADO",
                "service": "servico-agendamento",
                "request_id": g.request_id,
                "details": {
                    "telescope_id": telescope_id,
                    "cientista_id": cientista_id,
                    "start_utc": start_utc,
                    "end_utc": end_utc,
                    "reason": "OVERLAP"
                }
            }
            write_audit_log(audit)
            return jsonify({"error":"RESOURCE_CONFLICT","message":"Time slot already taken","request_id":g.request_id}), 409

        # 2. No conflict -> create booking
        booking = Booking(
            telescope_id=telescope_id,
            cientista_id=cientista_id,
            start_utc=start_utc,
            end_utc=end_utc,
            request_timestamp_utc=payload.get("request_timestamp_utc"),
            status="CONFIRMED"
        )
        db.session.add(booking)
        
        # 3. Tentativa de COMMIT (aqui ocorre o conflito de transação/bloqueio)
        db.session.commit() # <-- Se outra thread comitou um agendamento conflitante AQUI, esta linha falhará
        
        # 4. create audit entry for AGENDAMENTO_CRIADO
        audit = {
            "timestamp_utc": now_rfc3339_ms(),
            "level": "AUDIT",
            "event_type": "AGENDAMENTO_CRIADO",
            "service": "servico-agendamento",
            "request_id": g.request_id,
            "details": {
                "agendamento_id": booking.id,
                "cientista_id": cientista_id,
                "telescope_id": telescope_id,
                "start_utc": start_utc,
                "end_utc": end_utc,
                "request_timestamp_utc": payload.get("request_timestamp_utc")
            }
        }
        write_audit_log(audit)

        # 5. update booking.audit_log_ref
        booking.audit_log_ref = audit["id"]
        db.session.add(booking)
        db.session.commit()

    # TRATAMENTO DA FALHA DE CONCORRÊNCIA:
    except IntegrityError as e:
        # Captura o erro que ocorre quando duas threads tentam comitar ao mesmo tempo 
        # e a primeira já garantiu o bloqueio da tabela no SQLite.
        app_logger.info(f"CONCORRÊNCIA DETECTADA: Falha de Integridade/Bloqueio no COMMIT. request_id={g.request_id}")
        db.session.rollback() # Obriga o rollback da transação com falha
        
        # Audita a rejeição devido à concorrência
        audit = {
            "timestamp_utc": now_rfc3339_ms(),
            "level": "AUDIT",
            "event_type": "AGENDAMENTO_RECUSADO",
            "service": "servico-agendamento",
            "request_id": g.request_id,
            "details": {
                "telescope_id": telescope_id,
                "cientista_id": cientista_id,
                "start_utc": start_utc,
                "end_utc": end_utc,
                "reason": "CONCURRENCY_COMMIT_FAIL"
            }
        }
        write_audit_log(audit)
        return jsonify({"error":"RESOURCE_CONFLICT","message":"Time slot already taken (Concurrency Detected)","request_id":g.request_id}), 409

    except Exception as e:
        app_logger.exception(f"Erro interno ao criar agendamento request_id={g.request_id} err={e}")
        db.session.rollback()
        return jsonify({"error":"INTERNAL_ERROR","message":"internal server error","request_id":g.request_id}), 500

    # HATEOAS links in response
    response_body = {
        "id": booking.id,
        "telescope_id": booking.telescope_id,
        "start_utc": booking.start_utc,
        "end_utc": booking.end_utc,
        "status": booking.status,
        "request_id": g.request_id,
        "links": [
            {"rel":"self","href":f"/agendamentos/{booking.id}","method":"GET"},
            {"rel":"cancel","href":f"/agendamentos/{booking.id}","method":"DELETE"},
            {"rel":"telescopio","href":f"/telescopios/{booking.telescope_id}","method":"GET"}
        ]
    }
    app_logger.info(f"Salvando novo agendamento no BD request_id={g.request_id} booking_id={booking.id}")
    return jsonify(response_body), 201

@app.route("/agendamentos", methods=["GET"])
def list_bookings():
    telescope_id = request.args.get("telescopio")
    # simple list all or by telescope
    q = Booking.query
    if telescope_id:
        q = q.filter(Booking.telescope_id == telescope_id)
    bookings = q.all()
    out = []
    for b in bookings:
        out.append({
            "id": b.id,
            "telescope_id": b.telescope_id,
            "start_utc": b.start_utc,
            "end_utc": b.end_utc,
            "status": b.status,
            "links":[{"rel":"self","href":f"/agendamentos/{b.id}"}]
        })
    return jsonify({"bookings": out, "links":[{"rel":"create","href":"/agendamentos","method":"POST"}]})

@app.route("/agendamentos/<int:booking_id>", methods=["GET"])
def get_booking(booking_id):
    b = Booking.query.get_or_404(booking_id)
    return jsonify({
        "id": b.id,
        "telescope_id": b.telescope_id,
        "start_utc": b.start_utc,
        "end_utc": b.end_utc,
        "status": b.status,
        "links":[
            {"rel":"cancel","href":f"/agendamentos/{b.id}","method":"DELETE"},
            {"rel":"telescopio","href":f"/telescopios/{b.telescope_id}","method":"GET"}
        ]
    })

# Utility: initialize DB with sample data
@app.cli.command("initdb")
def initdb_command():
    db.create_all()
    # create sample telescope + scientist if not exists
    if not Telescope.query.get("hubble-acad"):
        t = Telescope(id="hubble-acad", nome="Hubble Academic", descricao="Telescópio acadêmico")
        db.session.add(t)
    if not Scientist.query.filter_by(email="marie.curie@example.com").first():
        s = Scientist(nome="Marie Curie", email="marie.curie@example.com", instituicao="Institut de Radiologie")
        db.session.add(s)
    db.session.commit()
    print("Initialized database.")

# Run
if __name__ == "__main__":
    # Garante que o DB exista E contenha os dados de amostra
    # ao rodar 'python app.py'
    with app.app_context():
        db.create_all()
        # Popula os dados essenciais (da lógica do initdb)
        if not Telescope.query.get("hubble-acad"):
            t = Telescope(id="hubble-acad", nome="Hubble Academic", descricao="Telescópio acadêmico")
            db.session.add(t)
            print("Telescópio 'hubble-acad' criado.")
        if not Scientist.query.filter_by(email="marie.curie@example.com").first():
            s = Scientist(nome="Marie Curie", email="marie.curie@example.com", instituicao="Institut de Radiologie")
            db.session.add(s)
            print("Cientista 'Marie Curie' (ID 1) criada.")
        db.session.commit()
        
    app.run(host="127.0.0.1", port=5000, debug=False)