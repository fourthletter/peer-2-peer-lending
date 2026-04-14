const dotenv = require("dotenv");

dotenv.config();

const config = {
  port: Number(process.env.PORT || 4000),
  databaseUrl: process.env.DATABASE_URL,
  adminUsername: process.env.ADMIN_USERNAME,
  adminPassword: process.env.ADMIN_PASSWORD,
};

if (!config.databaseUrl) {
  throw new Error("DATABASE_URL is required. Add it to your environment.");
}

if (!config.adminUsername || !config.adminPassword) {
  throw new Error("ADMIN_USERNAME and ADMIN_PASSWORD are required. Add them to your environment.");
}

module.exports = config;
