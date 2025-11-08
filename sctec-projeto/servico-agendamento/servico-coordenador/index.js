// index.js
import express from "express";

const app = express();
app.use(express.json());

// Porta padrão (pode ser alterada via variável de ambiente)
const PORT = process.env.PORT || 3000;

// Estrutura de dados em memória para os locks ativos
const locks = new Map();

/**
 * POST /lock
 * Corpo esperado: { "resource": "hubble-acad_2025-12-01T03:00:00Z" }
 */
app.post("/lock", (req, res) => {
  const resource = req.body.resource;
  if (!resource) {
    console.log(`[Coordenador] ⚠️ Pedido de lock sem campo 'resource'.`);
    return res.status(400).json({ error: "Missing resource" });
  }

  console.log(`[Coordenador] 🔒 Recebido pedido de lock para recurso: ${resource}`);

  if (locks.has(resource)) {
    console.log(`[Coordenador] ❌ Recurso ${resource} já em uso, negando lock.`);
    return res.status(409).json({ error: "Resource already locked" });
  }

  // Cria o lock
  locks.set(resource, {
    lockedAt: new Date().toISOString(),
  });

  console.log(`[Coordenador] ✅ Lock concedido para recurso: ${resource}`);
  return res.status(200).json({ message: "Lock acquired", resource });
});

/**
 * POST /unlock
 * Corpo esperado: { "resource": "hubble-acad_2025-12-01T03:00:00Z" }
 */
app.post("/unlock", (req, res) => {
  const resource = req.body.resource;
  if (!resource) {
    console.log(`[Coordenador] ⚠️ Pedido de unlock sem campo 'resource'.`);
    return res.status(400).json({ error: "Missing resource" });
  }

  if (locks.has(resource)) {
    locks.delete(resource);
    console.log(`[Coordenador] 🔓 Lock liberado para recurso: ${resource}`);
    return res.status(200).json({ message: "Lock released", resource });
  } else {
    console.log(`[Coordenador] ℹ️ Pedido de unlock ignorado, recurso ${resource} não estava travado.`);
    return res.status(200).json({ message: "No lock to release", resource });
  }
});

/**
 * Endpoint auxiliar (GET /status)
 * Retorna a lista atual de locks em memória.
 */
app.get("/status", (req, res) => {
  const activeLocks = Array.from(locks.entries()).map(([key, value]) => ({
    resource: key,
    lockedAt: value.lockedAt,
  }));
  res.json({ activeLocks });
});

app.listen(PORT, () => {
  console.log(`🚀 Serviço Coordenador rodando na porta ${PORT}`);
});
