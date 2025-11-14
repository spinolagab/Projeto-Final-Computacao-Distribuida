# Dockerfile para o Serviço Coordenador (Node.js)
FROM node:18-alpine

# Definir diretório de trabalho
WORKDIR /app

# Copiar package.json e package-lock.json (se existir)
COPY package*.json ./

# Instalar dependências
RUN npm install

# Copiar o código da aplicação
COPY . .

# Expor a porta do serviço
EXPOSE 3000

# Comando para iniciar o serviço
CMD ["node", "index.js"]