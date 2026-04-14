function unauthorized(res) {
  res.set("WWW-Authenticate", 'Basic realm="Admin Area"');
  return res.status(401).json({ message: "Authentication required" });
}

function parseBasicAuth(headerValue) {
  if (!headerValue || !headerValue.startsWith("Basic ")) return null;
  const encoded = headerValue.slice(6).trim();
  let decoded = "";
  try {
    decoded = Buffer.from(encoded, "base64").toString("utf8");
  } catch (_err) {
    return null;
  }
  const separatorIndex = decoded.indexOf(":");
  if (separatorIndex < 0) return null;
  return {
    username: decoded.slice(0, separatorIndex),
    password: decoded.slice(separatorIndex + 1),
  };
}

function createBasicAuthMiddleware(options) {
  const { username, password } = options;
  if (!username || !password) {
    throw new Error("ADMIN_USERNAME and ADMIN_PASSWORD are required for basic auth.");
  }

  return function basicAuth(req, res, next) {
    const credentials = parseBasicAuth(req.headers.authorization);
    if (!credentials) return unauthorized(res);

    const userOk = credentials.username === username;
    const passOk = credentials.password === password;
    if (!userOk || !passOk) return unauthorized(res);

    return next();
  };
}

module.exports = createBasicAuthMiddleware;
