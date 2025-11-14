# Dockerfile para o Serviço de Agendamento (Python/Flask)
FROM python:3.11-slim

# Definir diretório de trabalho
WORKDIR /app

# Instalar dependências do sistema necessárias
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copiar requirements.txt
COPY requirements.txt .

# Instalar dependências Python
RUN pip install --no-cache-dir -r requirements.txt

# Adicionar flask-cors ao requirements se não estiver
RUN pip install --no-cache-dir flask-cors

# Copiar o código da aplicação
COPY . .

# Criar diretórios para dados persistentes
RUN mkdir -p /app/data

# Expor a porta do serviço
EXPOSE 5000

# Comando para iniciar o serviço
CMD ["python", "app.py"]