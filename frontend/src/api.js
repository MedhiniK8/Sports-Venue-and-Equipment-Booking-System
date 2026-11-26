export const TOKEN_STORAGE_KEY = "sportsVenueAccessToken";
export const AUTH_EXPIRED_EVENT = "sports-venue-auth-expired";

export class ApiError extends Error {
  constructor(message, status, body) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

async function request(path, { method = "GET", body, auth = true, token } = {}) {
  const headers = { Accept: "application/json" };
  const options = { method, headers };

  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }

  const accessToken =
    token ?? (auth ? window.sessionStorage.getItem(TOKEN_STORAGE_KEY) : null);
  if (auth && accessToken) {
    headers.Authorization = `Bearer ${accessToken}`;
  }

  let response;
  try {
    response = await fetch(`/api${path}`, options);
  } catch {
    throw new ApiError(
      "Unable to reach the booking service. Check your connection and try again.",
      null,
      null,
    );
  }

  const responseText = response.status === 204 ? "" : await response.text();
  let responseBody = null;
  if (responseText) {
    try {
      responseBody = JSON.parse(responseText);
    } catch {
      responseBody = responseText;
    }
  }

  if (!response.ok) {
    if (response.status === 401 && auth) {
      window.dispatchEvent(new Event(AUTH_EXPIRED_EVENT));
    }
    throw new ApiError(
      getApiErrorMessage(response.status, responseBody),
      response.status,
      responseBody,
    );
  }

  return { status: response.status, data: responseBody };
}

export const api = {
  register(payload) {
    return request("/auth/register", {
      method: "POST",
      body: payload,
      auth: false,
    });
  },

  login(payload) {
    return request("/auth/login", {
      method: "POST",
      body: payload,
      auth: false,
    });
  },

  getProfile(token) {
    return request("/auth/me", { token });
  },

  getSports() {
    return request("/catalog/sports");
  },

  getCourts(sportId) {
    return request(`/catalog/sports/${encodeURIComponent(sportId)}/courts`);
  },

  getEquipment() {
    return request("/catalog/equipment");
  },

  createBooking(payload) {
    return request("/bookings", { method: "POST", body: payload });
  },

  getBookings() {
    return request("/bookings");
  },

  cancelBooking(bookingId) {
    return request(`/bookings/${encodeURIComponent(bookingId)}`, {
      method: "DELETE",
    });
  },
};

export function getApiErrorMessage(status, body) {
  const detail = body && typeof body === "object" ? body.detail : null;

  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        const field = Array.isArray(item.loc) ? item.loc.at(-1) : null;
        return field ? `${field}: ${item.msg}` : item.msg;
      })
      .filter(Boolean)
      .join(" ");
  }

  if (typeof detail === "string") {
    return detail;
  }

  if (detail && typeof detail === "object") {
    if (detail.code === "availability_conflict") {
      return "That court interval is no longer available. Choose another date or time.";
    }
    if (detail.code === "booking_start_time_passed") {
      return "The booking interval has already started or passed.";
    }
    if (detail.code === "equipment_unavailable") {
      return `Equipment availability changed. ${detail.requested_quantity} requested, ${detail.available_quantity} currently available. Review your request and try again.`;
    }
    if (detail.code === "booking_committed_refresh_failed") {
      return "The booking was saved, but availability could not be refreshed.";
    }
    if (detail.code === "cancellation_committed_refresh_failed") {
      return "The cancellation was saved, but availability could not be refreshed.";
    }
    if (detail.message) {
      return detail.message;
    }
  }

  if (body && typeof body === "object" && body.message) {
    return body.message;
  }
  if (status === 401) {
    return "Your session has expired. Please sign in again.";
  }
  if (status === 409) {
    return "The request conflicts with current booking information.";
  }
  if (status === 423) {
    return "This court is being updated. Please retry shortly.";
  }
  if (status === 429) {
    return "The booking queue is busy. Please retry shortly.";
  }
  if (status === 503) {
    return "The booking service is temporarily unavailable. Please try again.";
  }
  if (status === null) {
    return "Unable to reach the booking service. Check your connection and try again.";
  }
  return "The request could not be completed. Please try again.";
}
