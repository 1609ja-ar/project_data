// Turns any API/network error into a short, friendly message. Never shows raw JSON or stack traces.
const STATUS_MESSAGES = {
  400: 'That request could not be processed.',
  401: 'Please sign in to continue.',
  403: 'You do not have permission to do that.',
  404: 'We could not find that. It may have been deleted.',
  409: 'That conflicts with something that already exists.',
  413: 'That file is too large.',
  422: 'Some fields need attention.',
  429: 'Too many requests. Please wait a moment and try again.',
  500: 'Something went wrong on our side. Please try again.',
  502: 'The server is unavailable right now. Please try again shortly.',
  503: 'The server is unavailable right now. Please try again shortly.',
  504: 'The request took too long. Please try again.',
};

export function getErrorInfo(err) {
  if (!err) return { message: 'Unknown error', code: 'unknown' };
  if (err.code === 'ECONNABORTED') return { message: 'The request timed out. Please try again.', code: 'timeout' };
  const res = err.response;
  if (!res) return { message: 'Cannot reach the server. Check that the backend is running and try again.', code: 'network' };
  const body = res.data;
  const e = body && typeof body === 'object' ? body.error : null;
  if (e && typeof e.message === 'string') {
    return { message: e.message, code: e.code, details: e.details, status: res.status };
  }
  return { message: STATUS_MESSAGES[res.status] || 'Request failed. Please try again.', code: `http_${res.status}`, status: res.status };
}

export function errorMessage(err) {
  return getErrorInfo(err).message;
}

// For 422 validation errors: { fieldName: message }
export function fieldErrors(err) {
  const info = getErrorInfo(err);
  if (info.code !== 'validation_error' || !Array.isArray(info.details)) return {};
  const out = {};
  for (const d of info.details) {
    const k = String(d.field || '').split('.').pop();
    if (k && !out[k]) out[k] = String(d.message || '').replace(/^Value error, /, '');
  }
  return out;
}
