# teste_estresse.py
import requests
import threading
import time

URL_AGENDAMENTO = "http://127.0.0.1:5000/agendamentos"

NUMERO_DE_REQUISICOES = 10

PAYLOAD_CONFLITANTE = {
    "telescope_id": "hubble-acad",
    "cientista_id": 1,
    "start_utc": "2025-12-01T03:00:00Z",
    "end_utc": "2025-12-01T03:05:00Z",
    "request_timestamp_utc": "2025-10-26T18:00:04.999Z",
    "purpose": "Observação da Nebulosa X"
}

def fazer_requisicao_agendamento(thread_num):
    print(f"[Thread {thread_num}]: Iniciando requisição...")
    try:
        response = requests.post(URL_AGENDAMENTO, json=PAYLOAD_CONFLITANTE, timeout=10)
        print(f"[Thread {thread_num}]: Status Code: {response.status_code}, Body: {response.text[:200]}")
    except requests.exceptions.RequestException as e:
        print(f"[Thread {thread_num}]: Erro: {e}")

if __name__ == "__main__":
    threads = []
    start_time = time.time()
    for i in range(NUMERO_DE_REQUISICOES):
        t = threading.Thread(target=fazer_requisicao_agendamento, args=(i+1,))
        threads.append(t)
        t.start()
    for t in threads:
        t.join()
    print("Terminado. Tempo total: %.2f s" % (time.time() - start_time))
