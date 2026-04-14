const express = require("express");
const { z } = require("zod");
const pool = require("../db/pool");

const profilesRouter = express.Router();
const contributionsRouter = express.Router();
const loanRequestsRouter = express.Router();
const repaymentsRouter = express.Router();
const adminRouter = express.Router();

const profileSchema = z.object({
  fullName: z.string().min(2),
  email: z.string().email(),
  city: z.string().optional().nullable(),
  workerType: z.string().optional().nullable(),
  contributionTier: z.enum(["starter", "core", "builder"]),
  monthlyContribution: z.number().positive(),
});

profilesRouter.post("/", async (req, res, next) => {
  try {
    const data = profileSchema.parse(req.body);
    const query = `
      INSERT INTO profiles
      (full_name, email, city, worker_type, contribution_tier, monthly_contribution)
      VALUES ($1, $2, $3, $4, $5, $6)
      RETURNING *`;
    const values = [
      data.fullName,
      data.email,
      data.city || null,
      data.workerType || null,
      data.contributionTier,
      data.monthlyContribution,
    ];
    const { rows } = await pool.query(query, values);
    res.status(201).json(rows[0]);
  } catch (err) {
    if (err instanceof z.ZodError) return res.status(400).json({ errors: err.issues });
    next(err);
  }
});

profilesRouter.get("/:id", async (req, res, next) => {
  try {
    const { rows } = await pool.query("SELECT * FROM profiles WHERE id = $1", [req.params.id]);
    if (!rows[0]) return res.status(404).json({ message: "Profile not found" });
    res.json(rows[0]);
  } catch (err) {
    next(err);
  }
});

profilesRouter.patch("/:id", async (req, res, next) => {
  try {
    const updateSchema = profileSchema.partial();
    const data = updateSchema.parse(req.body);
    const keyMap = {
      fullName: "full_name",
      email: "email",
      city: "city",
      workerType: "worker_type",
      contributionTier: "contribution_tier",
      monthlyContribution: "monthly_contribution",
    };
    const entries = Object.entries(data);
    if (!entries.length) return res.status(400).json({ message: "No fields provided" });

    const setters = entries.map(([key], idx) => `${keyMap[key]} = $${idx + 1}`);
    const values = entries.map(([, value]) => value);
    values.push(req.params.id);

    const query = `
      UPDATE profiles
      SET ${setters.join(", ")}, updated_at = NOW()
      WHERE id = $${values.length}
      RETURNING *`;
    const { rows } = await pool.query(query, values);
    if (!rows[0]) return res.status(404).json({ message: "Profile not found" });
    res.json(rows[0]);
  } catch (err) {
    if (err instanceof z.ZodError) return res.status(400).json({ errors: err.issues });
    next(err);
  }
});

const contributionSchema = z.object({
  profileId: z.number().int().positive(),
  contributionMonth: z.string().min(7),
  amount: z.number().positive(),
  status: z.enum(["recorded", "pending", "settled", "failed"]).optional(),
});

contributionsRouter.post("/", async (req, res, next) => {
  try {
    const data = contributionSchema.parse(req.body);
    const query = `
      INSERT INTO contributions (profile_id, contribution_month, amount, status)
      VALUES ($1, $2, $3, COALESCE($4, 'recorded'))
      RETURNING *`;
    const { rows } = await pool.query(query, [
      data.profileId,
      data.contributionMonth,
      data.amount,
      data.status || null,
    ]);
    res.status(201).json(rows[0]);
  } catch (err) {
    if (err instanceof z.ZodError) return res.status(400).json({ errors: err.issues });
    next(err);
  }
});

contributionsRouter.get("/", async (req, res, next) => {
  try {
    const values = [];
    const clauses = [];
    if (req.query.profileId) {
      values.push(Number(req.query.profileId));
      clauses.push(`profile_id = $${values.length}`);
    }
    if (req.query.month) {
      values.push(req.query.month);
      clauses.push(`to_char(contribution_month, 'YYYY-MM') = $${values.length}`);
    }
    const where = clauses.length ? `WHERE ${clauses.join(" AND ")}` : "";
    const { rows } = await pool.query(
      `SELECT * FROM contributions ${where} ORDER BY contribution_month DESC`,
      values
    );
    res.json(rows);
  } catch (err) {
    next(err);
  }
});

const loanRequestSchema = z.object({
  profileId: z.number().int().positive(),
  amount: z.number().positive(),
  purpose: z.string().min(5),
  repaymentMonths: z.number().int().min(1).max(12),
});

loanRequestsRouter.post("/", async (req, res, next) => {
  try {
    const data = loanRequestSchema.parse(req.body);
    const { rows } = await pool.query(
      `INSERT INTO loan_requests (profile_id, amount, purpose, repayment_months)
       VALUES ($1, $2, $3, $4)
       RETURNING *`,
      [data.profileId, data.amount, data.purpose, data.repaymentMonths]
    );
    res.status(201).json(rows[0]);
  } catch (err) {
    if (err instanceof z.ZodError) return res.status(400).json({ errors: err.issues });
    next(err);
  }
});

loanRequestsRouter.get("/", async (req, res, next) => {
  try {
    const values = [];
    const clauses = [];
    if (req.query.status) {
      values.push(req.query.status);
      clauses.push(`status = $${values.length}`);
    }
    if (req.query.profileId) {
      values.push(Number(req.query.profileId));
      clauses.push(`profile_id = $${values.length}`);
    }
    const where = clauses.length ? `WHERE ${clauses.join(" AND ")}` : "";
    const { rows } = await pool.query(
      `SELECT * FROM loan_requests ${where} ORDER BY requested_at DESC`,
      values
    );
    res.json(rows);
  } catch (err) {
    next(err);
  }
});

const repaymentScheduleSchema = z.object({
  loanRequestId: z.number().int().positive(),
  startDate: z.string().optional(),
});

repaymentsRouter.post("/schedule", async (req, res, next) => {
  const client = await pool.connect();
  try {
    const data = repaymentScheduleSchema.parse(req.body);
    await client.query("BEGIN");

    const loanResult = await client.query("SELECT * FROM loan_requests WHERE id = $1", [
      data.loanRequestId,
    ]);
    const loan = loanResult.rows[0];
    if (!loan) {
      await client.query("ROLLBACK");
      return res.status(404).json({ message: "Loan request not found" });
    }
    if (loan.status === "rejected") {
      await client.query("ROLLBACK");
      return res.status(400).json({ message: "Cannot schedule repayments for rejected loan" });
    }

    await client.query("DELETE FROM repayments WHERE loan_request_id = $1", [loan.id]);

    const monthlyAmount = Number(loan.amount) / loan.repayment_months;
    const startDate = data.startDate ? new Date(data.startDate) : new Date();
    const inserts = [];

    for (let i = 1; i <= loan.repayment_months; i += 1) {
      const dueDate = new Date(startDate);
      dueDate.setMonth(dueDate.getMonth() + i);
      const amountDue = Number(monthlyAmount.toFixed(2));
      const { rows } = await client.query(
        `INSERT INTO repayments
         (loan_request_id, installment_number, due_date, amount_due)
         VALUES ($1, $2, $3, $4)
         RETURNING *`,
        [loan.id, i, dueDate.toISOString().slice(0, 10), amountDue]
      );
      inserts.push(rows[0]);
    }

    await client.query("UPDATE loan_requests SET status = 'funded' WHERE id = $1", [loan.id]);
    await client.query("COMMIT");
    res.status(201).json(inserts);
  } catch (err) {
    await client.query("ROLLBACK");
    if (err instanceof z.ZodError) return res.status(400).json({ errors: err.issues });
    next(err);
  } finally {
    client.release();
  }
});

const repaymentRecordSchema = z.object({
  repaymentId: z.number().int().positive(),
  amountPaid: z.number().positive(),
});

repaymentsRouter.post("/pay", async (req, res, next) => {
  const client = await pool.connect();
  try {
    const data = repaymentRecordSchema.parse(req.body);
    await client.query("BEGIN");

    const repaymentResult = await client.query("SELECT * FROM repayments WHERE id = $1", [
      data.repaymentId,
    ]);
    const repayment = repaymentResult.rows[0];
    if (!repayment) {
      await client.query("ROLLBACK");
      return res.status(404).json({ message: "Repayment record not found" });
    }

    const newPaid = Number(repayment.amount_paid) + data.amountPaid;
    const isPaid = newPaid >= Number(repayment.amount_due);
    const { rows } = await client.query(
      `UPDATE repayments
       SET amount_paid = $1, status = $2, paid_at = CASE WHEN $2 = 'paid' THEN NOW() ELSE paid_at END
       WHERE id = $3
       RETURNING *`,
      [newPaid, isPaid ? "paid" : "scheduled", repayment.id]
    );

    await client.query("COMMIT");
    res.json(rows[0]);
  } catch (err) {
    await client.query("ROLLBACK");
    if (err instanceof z.ZodError) return res.status(400).json({ errors: err.issues });
    next(err);
  } finally {
    client.release();
  }
});

repaymentsRouter.get("/", async (req, res, next) => {
  try {
    const values = [];
    const clauses = [];
    if (req.query.loanRequestId) {
      values.push(Number(req.query.loanRequestId));
      clauses.push(`loan_request_id = $${values.length}`);
    }
    const where = clauses.length ? `WHERE ${clauses.join(" AND ")}` : "";
    const { rows } = await pool.query(
      `SELECT * FROM repayments ${where} ORDER BY loan_request_id, installment_number`,
      values
    );
    res.json(rows);
  } catch (err) {
    next(err);
  }
});

const loanStatusSchema = z.object({
  status: z.enum(["approved", "rejected", "funded", "repaid"]),
  reviewedBy: z.string().optional(),
  notes: z.string().optional(),
});

adminRouter.patch("/loan-requests/:id/status", async (req, res, next) => {
  try {
    const data = loanStatusSchema.parse(req.body);
    const { rows } = await pool.query(
      `UPDATE loan_requests
       SET status = $1, reviewed_at = NOW(), reviewed_by = $2, notes = $3
       WHERE id = $4
       RETURNING *`,
      [data.status, data.reviewedBy || "admin", data.notes || null, req.params.id]
    );
    if (!rows[0]) return res.status(404).json({ message: "Loan request not found" });
    res.json(rows[0]);
  } catch (err) {
    if (err instanceof z.ZodError) return res.status(400).json({ errors: err.issues });
    next(err);
  }
});

adminRouter.get("/profiles", async (_req, res, next) => {
  try {
    const { rows } = await pool.query(
      `SELECT
         p.id,
         p.full_name,
         p.email,
         p.city,
         p.worker_type,
         p.contribution_tier,
         p.monthly_contribution,
         p.created_at,
         COUNT(DISTINCT lr.id) AS total_loan_requests,
         COALESCE(SUM(c.amount), 0) AS total_contributions
       FROM profiles p
       LEFT JOIN loan_requests lr ON lr.profile_id = p.id
       LEFT JOIN contributions c ON c.profile_id = p.id
       GROUP BY p.id
       ORDER BY p.created_at DESC`
    );
    res.json(rows);
  } catch (err) {
    next(err);
  }
});

adminRouter.get("/payments", async (_req, res, next) => {
  try {
    const [summaryResult, byMemberResult] = await Promise.all([
      pool.query(
        `SELECT
           COUNT(*)::int AS total_repayments,
           COALESCE(SUM(amount_due), 0) AS total_due,
           COALESCE(SUM(amount_paid), 0) AS total_paid,
           COALESCE(SUM(amount_due - amount_paid), 0) AS outstanding_balance,
           COUNT(*) FILTER (WHERE status = 'paid')::int AS paid_installments,
           COUNT(*) FILTER (WHERE status <> 'paid')::int AS open_installments
         FROM repayments`
      ),
      pool.query(
        `SELECT
           p.id AS profile_id,
           p.full_name,
           p.email,
           COALESCE(SUM(r.amount_due), 0) AS total_due,
           COALESCE(SUM(r.amount_paid), 0) AS total_paid,
           COALESCE(SUM(r.amount_due - r.amount_paid), 0) AS outstanding_balance,
           COUNT(r.id)::int AS installments
         FROM profiles p
         LEFT JOIN loan_requests lr ON lr.profile_id = p.id
         LEFT JOIN repayments r ON r.loan_request_id = lr.id
         GROUP BY p.id
         ORDER BY outstanding_balance DESC, p.created_at DESC`
      ),
    ]);

    res.json({
      summary: summaryResult.rows[0],
      members: byMemberResult.rows,
    });
  } catch (err) {
    next(err);
  }
});

module.exports = {
  profilesRouter,
  contributionsRouter,
  loanRequestsRouter,
  repaymentsRouter,
  adminRouter,
};
