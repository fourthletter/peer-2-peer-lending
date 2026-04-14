#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:4000}"
ADMIN_USER="${ADMIN_USER:-admin}"
ADMIN_PASS="${ADMIN_PASS:-cookie-tin-admin}"
STAMP="$(date +%s)"
EMAIL="smoke.${STAMP}@example.com"

echo "== Health =="
curl -s "${BASE_URL}/health"
echo

echo "== Create profile =="
PROFILE_JSON="$(
  curl -s "${BASE_URL}/api/profiles" \
    -H "Content-Type: application/json" \
    -d "{
      \"fullName\":\"Smoke Tester\",
      \"email\":\"${EMAIL}\",
      \"city\":\"Test City\",
      \"workerType\":\"Freelancer\",
      \"contributionTier\":\"core\",
      \"monthlyContribution\":50
    }"
)"
echo "${PROFILE_JSON}"
PROFILE_ID="$(python3 -c "import json,sys; print(json.loads(sys.stdin.read())['id'])" <<< "${PROFILE_JSON}")"

echo "== Create contribution =="
curl -s "${BASE_URL}/api/contributions" \
  -H "Content-Type: application/json" \
  -d "{
    \"profileId\":${PROFILE_ID},
    \"contributionMonth\":\"2026-04-01\",
    \"amount\":50
  }"
echo

echo "== Create loan request =="
LOAN_JSON="$(
  curl -s "${BASE_URL}/api/loan-requests" \
    -H "Content-Type: application/json" \
    -d "{
      \"profileId\":${PROFILE_ID},
      \"amount\":300,
      \"purpose\":\"Rent support\",
      \"repaymentMonths\":3
    }"
)"
echo "${LOAN_JSON}"
LOAN_ID="$(python3 -c "import json,sys; print(json.loads(sys.stdin.read())['id'])" <<< "${LOAN_JSON}")"

echo "== Admin approve loan =="
curl -s -u "${ADMIN_USER}:${ADMIN_PASS}" \
  -X PATCH "${BASE_URL}/api/admin/loan-requests/${LOAN_ID}/status" \
  -H "Content-Type: application/json" \
  -d '{"status":"approved","reviewedBy":"smoke-test","notes":"approved via script"}'
echo

echo "== Schedule repayments =="
curl -s "${BASE_URL}/api/repayments/schedule" \
  -H "Content-Type: application/json" \
  -d "{
    \"loanRequestId\":${LOAN_ID},
    \"startDate\":\"2026-04-01\"
  }"
echo

echo "== Admin profiles/payment summaries =="
curl -s -u "${ADMIN_USER}:${ADMIN_PASS}" "${BASE_URL}/api/admin/profiles"
echo
curl -s -u "${ADMIN_USER}:${ADMIN_PASS}" "${BASE_URL}/api/admin/payments"
echo

echo "Smoke test complete."
