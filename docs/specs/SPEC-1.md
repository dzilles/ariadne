# SPEC-1: Create Daily Revenue Dashboard Widget

## 1. Overview
Implementation of a secure, real-time aggregate revenue data provider and a responsive frontend component to visualize daily financial performance and period-over-period growth metrics.

## 2. Data Models

### RevenueSnapshot
| Field | Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `current_total` | Decimal(18, 2) | Non-negative | Total revenue generated from 00:00:00 UTC to current system time. |
| `previous_total` | Decimal(18, 2) | Non-negative | Total revenue generated from 00:00:00 UTC to (Current Time - 24h) yesterday. |
| `trend_percentage` | Float | Rounded to 2 decimal places | Percentage difference between `current_total` and `previous_total`. |
| `currency_code` | String (ISO 4217) | Length = 3, Uppercase | The currency unit (e.g., "USD", "EUR"). |
| `last_updated` | Timestamp (ISO 8601) | Must be UTC | The exact moment the aggregation was last calculated. |
| `refresh_interval_ms` | Integer | Min: 60000, Max: 900000 | The TTL/Cache duration for the client-side polling. |

## 3. API Contract

### Backend Endpoint
- **Endpoint:** `/api/v1/finance/dashboard/daily-revenue`
- **Method:** `GET`
- **Request Headers:**
  - `Authorization: Bearer <JWT>`
- **Response Body (Success):**
```json
{
  "data": {
    "current_total": 15420.50,
    "previous_total": 14100.00,
    "trend_percentage": 9.37,
    "currency_code": "USD",
    "last_updated": "2023-10-27T14:30:00Z",
    "refresh_interval_ms": 900000
  },
  "status": "success"
}
```
- **Status Codes:**
  - `200 OK`: Request successful.
  - `401 Unauthorized`: Missing or invalid authentication token.
  - `403 Forbidden`: User lacks `FINANCE_VIEW` or `ADMIN` permissions.
  - `500 Internal Server Error`: Database or aggregation service failure.

### Frontend Component Props
- **Component:** `DailyRevenueWidget`
- **Props:**
  - `refreshStrategy`: `"poll" | "websocket"` (Default: `"poll"`)
  - `showTrend`: `Boolean` (Default: `true`)
  - `locale`: `String` (e.g., `"en-US"`)

## 4. Validation Rules

1.  **Temporal Consistency:** The "Same time yesterday" comparison must use a sliding window logic. If the current time is 14:00, the comparison value must represent revenue from 00:00 to 14:00 of the previous calendar day.
2.  **Access Control:** The API must implement Role-Based Access Control (RBAC). Requests from users without the `ROLE_ADMIN` or `ROLE_FINANCE_MANAGER` scopes must be rejected with a `403 Forbidden` response.
3.  **Data Freshness:** The backend cache must not exceed 15 minutes (900,000ms). The `last_updated` field must be validated by the frontend to ensure data is not stale.
4.  **Numerical Precision:** All currency calculations must be performed using arbitrary-precision arithmetic (Decimal/BigDecimal) to prevent floating-point rounding errors.
5.  **Responsiveness:** The UI component must adhere to a grid-based layout, collapsing to a single-column view on viewports `< 768px`.
6.  **Trend Calculation:** In the event that `previous_total` is 0, `trend_percentage` should return `null` or `100.00` based on business logic for "new growth" scenarios.