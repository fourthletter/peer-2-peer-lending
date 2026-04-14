const express = require("express");
const cors = require("cors");
const path = require("path");
const pool = require("./db/pool");
const config = require("./config");
const createBasicAuthMiddleware = require("./middleware/basicAuth");
const {
  profilesRouter,
  contributionsRouter,
  loanRequestsRouter,
  repaymentsRouter,
  adminRouter,
} = require("./routes");

const app = express();
const adminBasicAuth = createBasicAuthMiddleware({
  username: process.env.ADMIN_USERNAME || config.adminUsername,
  password: process.env.ADMIN_PASSWORD || config.adminPassword,
});

app.use(cors());
app.use(express.json());
app.get("/admin.html", adminBasicAuth, (_req, res) => {
  res.sendFile(path.join(__dirname, "..", "public", "admin.html"));
});

app.get("/health", async (_req, res) => {
  try {
    await pool.query("SELECT 1");
    res.json({ ok: true });
  } catch (_err) {
    res.status(500).json({ ok: false, message: "Database unavailable" });
  }
});

app.use("/api/profiles", profilesRouter);
app.use("/api/contributions", contributionsRouter);
app.use("/api/loan-requests", loanRequestsRouter);
app.use("/api/repayments", repaymentsRouter);
app.use("/api/admin", adminBasicAuth, adminRouter);
app.use(express.static(path.join(__dirname, "..", "public")));

app.use((err, _req, res, _next) => {
  console.error(err);
  res.status(500).json({ message: "Internal server error" });
});

module.exports = app;
