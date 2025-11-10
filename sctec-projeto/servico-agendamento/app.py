# app.py
import os
import uuid
import hmac
import hashlib
import json
import requests  
from flask_cors import CORS
from flask import send_from_directory
from datetime import datetime
from functools import wraps

from flask import Flask, request, jsonify, g
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.exc import IntegrityError
import logging
from logging.handlers import RotatingFileHandler

# --- Config ---
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH = os.environ.get("SCTEC_DB_PATH", os.path.join(BASE_DIR, "sctec.db"))
AUDIT_LOG_FILE = os.environ.get("SCTEC_AUDIT_LOG", os.path.join(BASE_DIR, "audit.log"))
APP_LOG_FILE = os.environ.get("SCTEC_APP_LOG", os.path.join(BASE_DIR, "app.log"))
AUDIT_HMAC_KEY = os.environ.get("SCTEC_AUDIT_KEY", "dev_audit_key_change_me")

# 🔹 NOVO: URL do Coordenador
COORDENADOR_URL = os.environ.get("COORDENADOR_URL", "http://127.0.0.1:3000")

# Flask + SQLAlchemy
app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{DB_PATH}?isolation_level=IMMEDIATE"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

CORS(app, resources={
    r"/*": {
        "origins": ["*"],  # 🔹 ESPECÍFICO
        "methods": ["GET", "POST", "DELETE", "OPTIONS"],
        "allow_headers": ["Content-Type", "X-Request-Id"],
        "expose_headers": ["X-Request-Id"],
        "supports_credentials": False
    }
})

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
    id = db.Column(db.String, primary_key=True)
    nome = db.Column(db.String)
    descricao = db.Column(db.String)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Booking(db.Model):
    __tablename__ = "bookings"
    id = db.Column(db.Integer, primary_key=True)
    telescope_id = db.Column(db.String, db.ForeignKey("telescopes.id"), nullable=False)
    cientista_id = db.Column(db.Integer, db.ForeignKey("scientists.id"), nullable=False)
    start_utc = db.Column(db.String, nullable=False)
    end_utc = db.Column(db.String, nullable=False)
    status = db.Column(db.String, default="CONFIRMED")
    request_timestamp_utc = db.Column(db.String, nullable=True)
    audit_log_ref = db.Column(db.String, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

# --- Logging setup ---
app_logger = logging.getLogger("sctec_app")
app_logger.setLevel(logging.INFO)
formatter = logging.Formatter('%(levelname)s:%(asctime)s:%(name)s:%(message)s', "%Y-%m-%dT%H:%M:%S%z")

file_handler = RotatingFileHandler(APP_LOG_FILE, maxBytes=5*1024*1024, backupCount=2)
file_handler.setFormatter(formatter)
app_logger.addHandler(file_handler)
stream_handler = logging.StreamHandler()
stream_handler.setFormatter(formatter)
app_logger.addHandler(stream_handler)


def overlaps(telescope_id, start_utc, end_utc):
    """Verifica se há sobreposição de horários para o telescópio"""
    existing = Booking.query.filter(
        Booking.telescope_id == telescope_id,
        Booking.status == "CONFIRMED",
        Booking.start_utc < end_utc,
        Booking.end_utc > start_utc
    ).first()
    return existing is not None

# --- Audit Log ---
def write_audit_log(entry: dict):
    if "id" not in entry:
        entry["id"] = str(uuid.uuid4())
    if "timestamp_utc" not in entry:
        entry["timestamp_utc"] = datetime.utcnow().isoformat() + "Z"
    payload = json.dumps(entry, separators=(",", ":"), sort_keys=True, ensure_ascii=False)
    sig = hmac.new(AUDIT_HMAC_KEY.encode(), payload.encode(), hashlib.sha256).digest()
    entry["signature"] = "hmac-sha256:" + sig.hex()
    with open(AUDIT_LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
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
            app_logger.info(f"BadRequest: non-json request path={request.path}")
            return jsonify({"error":"BAD_REQUEST","message":"Content-Type must be application/json"}), 400
        return f(*args, **kwargs)
    return wrapper

@app.before_request
def attach_request_id():
    g.request_id = request.headers.get("X-Request-Id") or gen_request_id()
    g.remote_ip = request.remote_addr

# --- NOVO: Funções para lock/unlock ---
def acquire_lock(resource_id, owner_id="servico-agendamento-1", ttl_seconds=30):
    """Tenta adquirir lock no coordenador"""
    try:
        response = requests.post(
            f"{COORDENADOR_URL}/lock",
            json={"resource": resource_id},
            timeout=5
        )
        if response.status_code == 200:
            app_logger.info(f"Lock adquirido: {resource_id}")
            return True
        else:
            app_logger.warning(f"Lock negado: {resource_id}")
            return False
    except Exception as e:
        app_logger.error(f"Erro ao adquirir lock: {e}")
        return False

def release_lock(resource_id):
    """Libera lock no coordenador"""
    try:
        response = requests.post(
            f"{COORDENADOR_URL}/unlock",
            json={"resource": resource_id},
            timeout=5
        )
        app_logger.info(f"Lock liberado: {resource_id}")
    except Exception as e:
        app_logger.error(f"Erro ao liberar lock: {e}")

# --- Rotas ---

@app.route("/")
def index():
    return send_from_directory(".", "index.html")

@app.route("/<path:filename>")
def static_files(filename):
    return send_from_directory(".", filename)

@app.route("/time", methods=["GET"])
def get_time():
    # 🔹 NOVO: Log de aplicação
    app_logger.info(f"GET /time request_id={g.request_id} remote_ip={g.remote_ip}")
    
    server_time = now_rfc3339_ms()
    
    return jsonify({
        "server_time_utc": server_time,
        "server_unix_ms": int(datetime.utcnow().timestamp() * 1000)
    })

# 🔹 NOVO: Endpoint de Cancelamento
@app.route("/agendamentos/<int:booking_id>", methods=["DELETE"])
def cancel_booking(booking_id):
    """Cancela um agendamento existente"""
    app_logger.info(f"DELETE /agendamentos/{booking_id} request_id={g.request_id} remote_ip={g.remote_ip}")
    
    booking = db.session.get(Booking, booking_id)
    if not booking:
        app_logger.warning(f"Agendamento não encontrado: {booking_id}")
        return jsonify({
            "error": "NOT_FOUND",
            "message": f"Agendamento {booking_id} não encontrado"
        }), 404
    
    if booking.status == "CANCELLED":
        return jsonify({
            "error": "ALREADY_CANCELLED",
            "message": "Este agendamento já foi cancelado"
        }), 400
    
    # Armazena dados antes de cancelar
    old_status = booking.status
    telescope_id = booking.telescope_id
    cientista_id = booking.cientista_id
    start_utc = booking.start_utc
    
    # Cancela o agendamento
    booking.status = "CANCELLED"
    booking.updated_at = datetime.utcnow()
    db.session.commit()
    
    # 🔹 AUDITORIA: Log do cancelamento
    audit = {
        "timestamp_utc": now_rfc3339_ms(),
        "level": "AUDIT",
        "event_type": "AGENDAMENTO_CANCELADO",
        "service": "servico-agendamento",
        "request_id": g.request_id,
        "remote_ip": g.remote_ip,
        "details": {
            "agendamento_id": booking_id,
            "cientista_id": cientista_id,
            "telescope_id": telescope_id,
            "start_utc": start_utc,
            "old_status": old_status,
            "new_status": "CANCELLED"
        }
    }
    write_audit_log(audit)
    
    app_logger.info(f"Agendamento {booking_id} cancelado com sucesso")
    
    return jsonify({
        "message": "Agendamento cancelado com sucesso",
        "id": booking_id,
        "status": "CANCELLED",
        "request_id": g.request_id,
        "links": [
            {"rel": "self", "href": f"/agendamentos/{booking_id}", "method": "GET"},
            {"rel": "list", "href": "/agendamentos", "method": "GET"}
        ]
    }), 200

# 🔹 NOVO: Obter detalhes de um agendamento (para links HATEOAS)
@app.route("/agendamentos/<int:booking_id>", methods=["GET"])
def get_booking(booking_id):
    """Retorna detalhes de um agendamento específico"""
    app_logger.info(f"GET /agendamentos/{booking_id} request_id={g.request_id}")
    
    # 🔹 CORRIGIDO: Usar db.session.get()
    booking = db.session.get(Booking, booking_id)
    if not booking:
        return jsonify({"error": "NOT_FOUND"}), 404
    
    response = {
        "id": booking.id,
        "telescope_id": booking.telescope_id,
        "cientista_id": booking.cientista_id,
        "start_utc": booking.start_utc,
        "end_utc": booking.end_utc,
        "status": booking.status,
        "request_timestamp_utc": booking.request_timestamp_utc,
        "created_at": booking.created_at.isoformat() + "Z",
        "links": [
            {"rel": "self", "href": f"/agendamentos/{booking_id}", "method": "GET"},
            {"rel": "list", "href": "/agendamentos", "method": "GET"}
        ]
    }
    
    # 🔹 HATEOAS: Só adiciona link de cancelamento se não estiver cancelado
    if booking.status != "CANCELLED":
        response["links"].append({
            "rel": "cancel",
            "href": f"/agendamentos/{booking_id}",
            "method": "DELETE"
        })
    
    return jsonify(response), 200

@app.route("/agendamentos", methods=["POST"])
@require_json
def create_booking():
    payload = request.get_json()
    app_logger.info(f"Requisição recebida para POST /agendamentos request_id={g.request_id}")
    
    # Validação
    required = ["telescope_id", "cientista_id", "start_utc", "end_utc", "request_timestamp_utc"]
    for r in required:
        if r not in payload:
            return jsonify({"error":"BAD_REQUEST","message":f"missing {r}"}), 400
    
    telescope_id = payload["telescope_id"]
    cientista_id = payload["cientista_id"]
    start_utc = payload["start_utc"]
    end_utc = payload["end_utc"]
    
    # Criar resource_id único para o lock
    resource_id = f"{telescope_id}_{start_utc}"
    
    # 1. TENTAR ADQUIRIR LOCK
    if not acquire_lock(resource_id):
        audit = {
            "timestamp_utc": now_rfc3339_ms(),
            "level": "AUDIT",
            "event_type": "LOCK_CONFLICT",
            "service": "servico-agendamento",
            "request_id": g.request_id,
            "details": {"resource_id": resource_id, "reason": "LOCK_DENIED"}
        }
        write_audit_log(audit)
        return jsonify({"error":"RESOURCE_LOCKED","message":"Recurso está sendo acessado por outro processo"}), 409
    
    try:
        # 2. VERIFICAR CONFLITO
        conflict = overlaps(telescope_id, start_utc, end_utc)
        if conflict:
            audit = {
                "timestamp_utc": now_rfc3339_ms(),
                "level": "AUDIT",
                "event_type": "AGENDAMENTO_RECUSADO",
                "service": "servico-agendamento",
                "request_id": g.request_id,
                "details": {
                    "telescope_id": telescope_id,
                    "start_utc": start_utc,
                    "end_utc": end_utc,
                    "reason": "OVERLAP"
                }
            }
            write_audit_log(audit)
            return jsonify({"error":"RESOURCE_CONFLICT","message":"Horário já reservado"}), 409
        
        # 3. CRIAR BOOKING
        booking = Booking(
            telescope_id=telescope_id,
            cientista_id=cientista_id,
            start_utc=start_utc,
            end_utc=end_utc,
            request_timestamp_utc=payload.get("request_timestamp_utc"),
            status="CONFIRMED"
        )
        db.session.add(booking)
        db.session.commit()
        
        # 4. AUDITAR
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
                "end_utc": end_utc
            }
        }
        write_audit_log(audit)
        
        return jsonify({
            "id": booking.id,
            "telescope_id": booking.telescope_id,
            "start_utc": booking.start_utc,
            "end_utc": booking.end_utc,
            "status": booking.status,
            "links": [
                {"rel":"self","href":f"/agendamentos/{booking.id}","method":"GET"},
                {"rel":"cancel","href":f"/agendamentos/{booking.id}","method":"DELETE"}
            ]
        }), 201
    
    except IntegrityError:
        db.session.rollback()
        audit = {
            "timestamp_utc": now_rfc3339_ms(),
            "level": "AUDIT",
            "event_type": "AGENDAMENTO_RECUSADO",
            "service": "servico-agendamento",
            "request_id": g.request_id,
            "details": {"reason": "CONCURRENCY_COMMIT_FAIL"}
        }
        write_audit_log(audit)
        return jsonify({"error":"RESOURCE_CONFLICT","message":"Conflito de concorrência"}), 409
    
    finally:
        # 5. LIBERAR LOCK (SEMPRE)
        release_lock(resource_id)

# --- Demais rotas (sem alteração significativa) ---
@app.route("/telescopios", methods=["GET"])
def list_telescopes():
    telescopes = Telescope.query.all()
    out = [{"id": t.id, "nome": t.nome, "links": [{"rel": "self", "href": f"/telescopios/{t.id}"}]} for t in telescopes]
    return jsonify({"telescopes": out, "links": [{"rel": "create_booking", "href": "/agendamentos", "method": "POST"}]})

@app.route("/agendamentos", methods=["GET"])
def list_bookings():
    telescope_id = request.args.get("telescopio")
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
            "links": [{"rel": "self", "href": f"/agendamentos/{b.id}"}]
        })
    return jsonify({"bookings": out})

# Run
if __name__ == "__main__":
    with app.app_context():
        db.create_all()
        if not db.session.get(Telescope, "hubble-acad"):
            db.session.add(Telescope(id="hubble-acad", nome="Hubble Academic", descricao="Telescópio acadêmico"))
        
        # 🔹 CORRIGIDO: Verificar por email (campo único)
        if not Scientist.query.filter_by(email="marie.curie@example.com").first():
            db.session.add(Scientist(nome="Marie Curie", email="marie.curie@example.com", instituicao="Institut de Radiologie"))
        db.session.commit()

    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)